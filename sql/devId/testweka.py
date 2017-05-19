#!/usr/bin/env python

import mylogin
import MySQLdb
import yagmail
from datetime import datetime, timedelta
import os
import sys
import subprocess
from sh import epstopdf, gnuplot, mkdir, cp, mv
from os.path import expanduser

import copy

sys.path.append('../plot/')
import pytch

from gen_arff_v2 import gen_arff

from math import floor

import weka.core.jvm as jvm
from weka.classifiers import Classifier, Evaluation
from weka.core.converters import Loader, Saver
from weka.core.classes import Random

def chop_microseconds(delta):
    return delta - timedelta(microseconds=delta.microseconds)

def is_number(s):
    try:
        float(s)
        return True
    except:
        return False

def print_conf_matrix(conf_matrix, stream, latex, plusSign, textCol):
	# print header:
	correct = 0
	total = 0
	if latex:
		colStr = '| '
		for col in range(0, len(conf_matrix)):
			colStr += 'c | '
		if textCol:
			colStr += '| c |'
		stream.write('\\begin{' + 'tabular}{' + colStr + '} \\hline \n')
		for idx, name in enumerate(conf_matrix):
			stream.write('$\\hskip 0.7em$' + chr(ord('a') + idx) + '$\\hskip 0.7em$\t')
			if not textCol and (idx+1) == len(conf_matrix):
				stream.write('\\\\ \\hline % & ')
			else:
				stream.write('& ')
		stream.write('$<$- Classified as\t\\\\ \\hline \n')
	else:
		stream.write('\n=== Confusion Matrix ===\n\n')
		for idx, name in enumerate(conf_matrix):
			value = chr(ord('a') + idx)
			stream.write('   ' + str(value))
		stream.write('   <-- classified as\n')
	stream.flush()

	for idx, testName in enumerate(conf_matrix):
		if latex:
			stream.write('\t')
		for idy, predName in enumerate(conf_matrix):
			if predName in conf_matrix[testName]:
				value = conf_matrix[testName][predName]
			else:
				value = 0

			if latex:
				if plusSign:
					if value > 0:
						writeVal = '+' + str(value)
					else:
						writeVal = value
				else:
					writeVal = value
				if predName == testName:
					stream.write('\cellcolor{' + 'goodgreen} ' + str(writeVal) + '\t')
				else:
					stream.write(str(writeVal) + '\t')

				if not textCol and (idy+1) == len(conf_matrix):
					stream.write('\\\\ \\hline % & ')
				else:
					stream.write('& ')
			else:
				if value < 10:
					stream.write('  ')
				elif value < 100:
					stream.write(' ')
				stream.write(' ' + str(value))

			if predName == testName:
				correct += value
			total += value

		writeStr = str(chr(ord('a') + idx)) + ' = ' + str(testName)
		if latex:
			stream.write(writeStr + '\t\\\\ \\hline \n\t')
		else:
			stream.write(' |   ' + writeStr + '\n')
	
	if latex:
		stream.write('\\end{' + 'tabular}\n')
	stream.flush()

	return correct, total

def sub_conf_matrix(orig, subtract):

	output = {}

	for testName in orig:
		orig_test = orig[testName]
		if testName in subtract:
			sub_test = subtract[testName]
		else:
			sub_test = {}

		output[testName] = {}

		for predName in orig:
			if predName in orig_test:
				orig_val = orig_test[predName]
			else:
				orig_val = 0
			if predName in sub_test:
				sub_val = sub_test[predName]
			else:
				sub_val = 0

			output[testName][predName] = orig_val - sub_val

	return output


item_start = datetime.utcnow()

# Set up connection
aws_login = mylogin.get_login_info('aws')
aws_db = MySQLdb.connect(aws_login['host'], aws_login['user'], aws_login['passwd'], 'powerblade')
aws_c = aws_db.cursor()

query_startDay = datetime.utcnow().strftime('%Y_%m_%d_%H_%M_%S')
master_saveDir = os.environ['PB_DATA'] + "/savetest/" + str(query_startDay) + '_classify'
mkdir(master_saveDir)

# Get list of devices:
aws_c.execute('select deviceMAC, count(*) as count from mr_dat_occ_vector ' \
	'where count>0 and duty!=0 and deviceMAC not in (select * from vector_reject) ' \
	'group by deviceMAC;')
devList = [x[0] for x in aws_c.fetchall()]

# Get small list of devices:
aws_c.execute('select deviceMAC, count(*) as count from mr_dat_occ_vector ' \
	'where count>0 and duty!=0 and deviceMAC not in (select * from vector_reject) ' \
	'and deviceType in (select * from id_fewcats) '
	'group by deviceMAC;')
smallList = [x[0] for x in aws_c.fetchall()]



jvm.start()
loader = Loader(classname="weka.core.converters.ArffLoader")

total_results = {}
total_conf = open('conf_matrix.txt', 'w')

totalDevs = 0
devCount = 0

save_orig = ''
save_subtract = ''

def process_classifier(runType, cls, occ, devList, fewCats, label, subtract):
	global devCount
	global save_orig
	global save_subtract
	conf_matrix = {}

	writeStr = '=========================================================================================\n' + \
		'Running ' + runType + ' classifier for \'' + label + '\''
	sys.stdout.write(writeStr + '\r')
	total_conf.write(writeStr + '\n')
	sys.stdout.flush()

	if runType == 'unseen':
		i = 0
		for dev in devList:
			devCount += 1
			remaining = chop_microseconds(((datetime.utcnow() - item_start)*totalDevs/devCount)-(datetime.utcnow() - item_start))
			sys.stdout.write('Running ' + runType + ' classifier for \'' + label + '\' - ' + \
				str(round(100*float(devCount)/totalDevs,2)) + ' pct complete (' + str(remaining) + ' remaining)                 \r')
			sys.stdout.flush()

			if fewCats:
				aws_c.execute('select * from mr_dat_occ_vector ' \
					'where duty!=0 and deviceMAC not in (select * from vector_reject) ' \
					'and deviceType in (select * from id_fewcats) '
					'and deviceMAC!=\'' + dev + '\';')
			else:
				aws_c.execute('select * from mr_dat_occ_vector ' \
					'where duty!=0 and deviceMAC not in (select * from vector_reject) ' \
					'and deviceMAC!=\'' + dev + '\';')
			results = aws_c.fetchall()

			# Generate type list
			total_types = ['{']
			for data in results:
				if(data[-1] not in total_types):
					total_types.append('\"')
					total_types.append(data[-1])
					total_types.append('\"')
					total_types.append(',')
			total_types[-1] = '}'
			typeStr = ''.join(total_types)

			arff_train = label + '_' + dev + '_train'
			arff_test = label + '_' + dev + '_test'

			gen_arff(arff_train, typeStr, results, occ)

			if fewCats:
				aws_c.execute('select * from mr_dat_occ_vector ' \
					'where duty!=0 and deviceMAC not in (select * from vector_reject) ' \
					'and deviceType in (select * from id_fewcats) '
					'and deviceMAC=\'' + dev + '\';')
			else:
				aws_c.execute('select * from mr_dat_occ_vector ' \
					'where duty!=0 and deviceMAC not in (select * from vector_reject) ' \
					'and deviceMAC=\'' + dev + '\';')
			gen_arff(arff_test, typeStr, aws_c.fetchall(), occ)

			train = loader.load_file(arff_train + '.arff')
			train.class_is_last()
			mv(arff_train + '.arff', master_saveDir)
			test = loader.load_file(arff_test + '.arff')
			test.class_is_last()
			mv(arff_test + '.arff', master_saveDir)

			cls.build_classifier(train)

			# output predictions
			testName = ''
			for index, inst in enumerate(test):
				testName = inst.get_string_value(inst.class_index)
				if testName not in conf_matrix:
					conf_matrix[testName] = {}

				pred = cls.classify_instance(inst)
				# dist = cls.distribution_for_instance(inst)
				# if(pred == inst.get_value(inst.class_index)):
				predName = inst.class_attribute.value(int(pred))
				if predName not in conf_matrix[testName]:
					conf_matrix[testName][predName] = 0
				conf_matrix[testName][predName] += 1

			total = 0
			for predName in conf_matrix[testName]:
				if predName == testName:
					correct = conf_matrix[testName][predName]
					total += correct
				else:
					total += conf_matrix[testName][predName]
			
			#print(str(testName) + ' ' + str(correct) + ' ' + str(total) + ' ' + str(float(correct)/total))

			# i += 1
			# if i == 10:
			# 	break


		correct, total = print_conf_matrix(conf_matrix, sys.stdout, False, False, False)
		correct, total = print_conf_matrix(conf_matrix, total_conf, False, False, False)

		if subtract == 'orig':
			save_orig = copy.deepcopy(conf_matrix)
		elif subtract == 'subtract':
			save_subtract = copy.deepcopy(conf_matrix)

		final_reslut = round(100*float(correct)/total,2)

		writeStr = '\nCorrectly Classified Instances\t\t' + str(correct) + '\t\t' + str(final_reslut) + '\n' + \
			'Incorrectly Classified Instances\t' + str(total-correct) + '\t\t' + str(round(100*float(total-correct)/total,2)) + '\n' + \
			'Total Number of Instances\t\t' + str(total) + '\n'
		print(writeStr)
		total_conf.write(writeStr + '\n')

	else:
		if fewCats:
			aws_c.execute('select * from mr_dat_occ_vector ' \
				'where duty!=0 and deviceMAC not in (select * from vector_reject) ' \
				'and deviceType in (select * from id_fewcats);')
		else:
			aws_c.execute('select * from mr_dat_occ_vector ' \
				'where duty!=0 and deviceMAC not in (select * from vector_reject);')
		results = aws_c.fetchall()

		devCount += 1
		remaining = chop_microseconds(((datetime.utcnow() - item_start)*totalDevs/devCount)-(datetime.utcnow() - item_start))
		sys.stdout.write('Running ' + runType + ' classifier for \'' + label + '\' - ' + \
			str(round(100*float(devCount)/totalDevs,2)) + ' pct complete (' + str(remaining) + ' remaining)                 \r')
		sys.stdout.flush()

		# Generate type list
		total_types = ['{']
		for data in results:
			if(data[-1] not in total_types):
				total_types.append('\"')
				total_types.append(data[-1])
				total_types.append('\"')
				total_types.append(',')
		total_types[-1] = '}'
		typeStr = ''.join(total_types)

		arff_file = label + '_train'

		gen_arff(arff_file, typeStr, results, occ)

		train = loader.load_file(arff_file + '.arff')
		train.class_is_last()
		mv(arff_file + '.arff', master_saveDir)

		cls.build_classifier(train)

		evl = Evaluation(train)
		evl.crossvalidate_model(cls, train, 10, Random(1))

		print('\n')
		#print(evl.percent_correct)
		#print(evl.class_details())
		print(evl.matrix())
		total_conf.write('\n' + evl.matrix())
		print(evl.summary())
		total_conf.write(evl.summary() + '\n')

		final_reslut = round(evl.percent_correct, 2)

	if label in total_results:
		print('Warning label ' + label + ' exists twice, overwriting...')
	total_results[label] = final_reslut

process_list = []
def preprocess_classifier(runType, cls, occ, thisDevList, fewcats, label, subtract):
	global totalDevs
	if runType == 'seen':
		totalDevs += 1
	else:
		totalDevs += len(thisDevList)
	process_list.append([runType, cls, occ, thisDevList, fewcats, label, subtract])


clsTree = Classifier(classname="weka.classifiers.trees.J48", options=["-C", "0.25", "-M", "2"])
clsBayes = Classifier(classname="weka.classifiers.bayes.NaiveBayes")


# # US Seen Bayes
# preprocess_classifier('seen', clsBayes, False, devList, False, 'full_seen_bayes')

# # US Seen J48
# preprocess_classifier('seen', clsTree, False, devList, False, 'full_seen_j48')

# # US Unseen Bayes
# preprocess_classifier('unseen', clsBayes, False, devList, False, 'full_unseen_bayes')

# US Unseen J48
preprocess_classifier('unseen', clsTree, False, devList, False, 'full_unseen_j48', 'subtract')

# # Small Seen Bayes
# preprocess_classifier('seen', clsBayes, False, smallList, True, 'small_seen_bayes')

# # # Small Seen J48
# preprocess_classifier('seen', clsTree, False, smallList, True, 'small_seen_j48')

# # Small Unseen Bayes
# preprocess_classifier('unseen', clsBayes, False, smallList, True, 'small_unseen_bayes')

# # Small Unseen J48
# preprocess_classifier('unseen', clsTree, False, smallList, True, 'small_unseen_j48')

# # Occ Seen Bayes
# preprocess_classifier('seen', clsBayes, True, devList, False, 'occ_seen_bayes')

# # Occ Seen J48
# preprocess_classifier('seen', clsTree, True, devList, False, 'occ_seen_j48')

# # Occ Unseen Bayes
# preprocess_classifier('unseen', clsBayes, True, devList, False, 'occ_unseen_bayes')

# Occ Unseen J48
# preprocess_classifier('unseen', clsTree, True, devList, False, 'occ_unseen_j48', 'orig')

# # Occ Small Seen Bayes
# preprocess_classifier('seen', clsBayes, True, smallList, True, 'occ_small_seen_bayes')

# # Occ Small Seen J48
# preprocess_classifier('seen', clsTree, True, smallList, True, 'occ_small_seen_j48')

# # Occ Small Unseen Bayes
# preprocess_classifier('unseen', clsBayes, True, smallList, True, 'occ_small_unseen_bayes')

# # Occ Small Unseen J48
# preprocess_classifier('unseen', clsTree, True, smallList, True, 'occ_small_unseen_j48')

item_start = datetime.utcnow()
for rT, cL, oC, dL, fc, lA, sT in process_list:
	process_classifier(rT, cL, oC, dL, fc, lA, sT)


jvm.stop()

# conf_new = sub_conf_matrix(save_orig, save_subtract)
# print('\nFull Unseen J48\n')
# print_conf_matrix(save_orig, sys.stdout, True, False, True)
# print('\nOcc Unseen J48\n')
# print_conf_matrix(conf_new, sys.stdout, True, True, True)

total_conf.close()
mv('conf_matrix.txt', master_saveDir)

for label in sorted(total_results):
	print(label + ': ' + str(total_results[label]) + ' pct correct')

def print_data(outfile, labels, bayesValues, treeValues):
	outfile.write('\n\n\"Naive Bayes\"\n')
	for idx, value in enumerate(bayesValues):
		outfile.write(str(idx) + '\t\"' + labels[idx] + '\"\t' + str(value) + '\n')

	outfile.write('\n\n\"J48\"\n')
	for idx, value in enumerate(treeValues):
		outfile.write(str(idx) + '\t\"' + labels[idx] + '\"\t' + str(value) + '\n')

	outfile.close()

def rep_none(key):
	if key in total_results:
		return total_results[key]
	else:
		return ''

# Create basic output
print_data(open('classify_basic.dat', 'w'), \
	['SMART, Seen', 'PB Small, Seen', 'SMART Unseen', 'PB Small, Unseen'], \
	[70, rep_none('small_seen_bayes'), 65, rep_none('small_unseen_bayes')], \
	[90, rep_none('small_seen_j48'), 60, rep_none('small_unseen_j48')])
mv('classify_basic.dat', master_saveDir)

# Create full output
print_data(open('classify_full.dat', 'w'),
	['Small, Seen', 'Full, Seen', 'Small, Unseen', 'Full, Unseen'],
	[rep_none('small_seen_bayes'), rep_none('full_seen_bayes'), rep_none('small_unseen_bayes'), rep_none('full_unseen_bayes')],
	[rep_none('small_seen_j48'), rep_none('full_seen_j48'), rep_none('small_unseen_j48'), rep_none('full_unseen_j48')])
mv('classify_full.dat', master_saveDir)

# Craete small occ output
print_data(open('classify_occ_small.dat', 'w'),
	['Small, Seen', 'Occ Sm, Seen', 'Small, Unseen', 'Occ Sm, Unseen'],
	[rep_none('small_seen_bayes'), rep_none('occ_small_seen_bayes'), rep_none('small_unseen_bayes'), rep_none('occ_small_unseen_bayes')],
	[rep_none('small_seen_j48'), rep_none('occ_small_seen_j48'), rep_none('small_unseen_j48'), rep_none('occ_small_unseen_j48')])
mv('classify_occ_small.dat', master_saveDir)

# Create full occ output
print_data(open('classify_occ_full.dat', 'w'),
	['Full, Seen', 'Occ, Seen', 'Full, Unseen', 'Occ, Unseen'],
	[rep_none('full_seen_bayes'), rep_none('occ_seen_bayes'), rep_none('full_unseen_bayes'), rep_none('occ_unseen_bayes')],
	[rep_none('full_seen_j48'), rep_none('occ_seen_j48'), rep_none('full_unseen_j48'), rep_none('occ_unseen_j48')])
mv('classify_occ_full.dat', master_saveDir)

