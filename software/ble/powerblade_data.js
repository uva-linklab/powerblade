var async = require('async');
var noble = require('noble');
var BitArray = require('node-bitarray');

// default to the Squall we are testing with
var peripheralUuid = 'e602dc1bdbfa';
if (process.argv.length >= 3) {
    peripheralUuid = process.argv[2].replace(/:/g, '').toLowerCase();
}
console.log('Looking for ' + peripheralUuid);

noble.on('stateChange', function(state) {
  if (state === 'poweredOn') {
    console.log("Starting scan...");
    noble.startScanning([], true);
  } else {
    noble.stopScanning();
  }
});

noble.on('discover', function(peripheral) {
  //console.log("Peripheral found: UUID " + peripheral.uuid);
  if (peripheral.uuid === peripheralUuid) {

    //console.log('Found peripheral: UUID ' + peripheralUuid + ' found');
    var advertisement = peripheral.advertisement;
    //console.log('  Advertising Data = ' + JSON.stringify(advertisement, null, 0));

    // get data after the manufacturer ID
    var data = advertisement.manufacturerData.slice(2);

    // get data values from the powerblade
    var sequence_num = BitArray.toNumber(BitArray.fromBuffer(data.slice(0,4)).reverse());
    var time = BitArray.toNumber(BitArray.fromBuffer(data.slice(4,8)).reverse());
    var v_rms = BitArray.toNumber(BitArray.fromBuffer(data.slice(8,9)).reverse());
    var true_power = BitArray.toNumber(BitArray.fromBuffer(data.slice(9,11)).reverse());
    var apparent_power = BitArray.toNumber(BitArray.fromBuffer(data.slice(11,13)).reverse());
    var watt_hours = BitArray.toNumber(BitArray.fromBuffer(data.slice(13,17)).reverse());

    // print to user
    console.log('Data:');
    console.log('       Sequence Number: ' + sequence_num +   ' (0x' + sequence_num.toString(16) + ')');
    console.log('                  Time: ' + time +           ' (0x' + time.toString(16) + ')');
    console.log('           RMS Voltage: ' + v_rms +          ' (0x' + v_rms.toString(16) + ')');
    console.log('    Current True Power: ' + true_power +     ' (0x' + true_power.toString(16) + ')');
    console.log('Current Apparent Power: ' + apparent_power + ' (0x' + apparent_power.toString(16) + ')');
    console.log(' Cumulative Watt Hours: ' + watt_hours +     ' (0x' + watt_hours.toString(16) + ')');

    console.log('');
  }
});


// lists all services, characteristics, and values when connected
function explore(peripheral) {
  console.log('services and characteristics:');

  peripheral.on('disconnect', function() {
    process.exit(0);
  });

  peripheral.connect(function(error) {
    peripheral.discoverServices([], function(error, services) {
      var serviceIndex = 0;

      async.whilst(
        function () {
          return (serviceIndex < services.length);
        },
        function(callback) {
          var service = services[serviceIndex];
          var serviceInfo = service.uuid;

          if (service.name) {
            serviceInfo += ' (' + service.name + ')';
          }
          console.log(serviceInfo);

          service.discoverCharacteristics([], function(error, characteristics) {
            var characteristicIndex = 0;

            async.whilst(
              function () {
                return (characteristicIndex < characteristics.length);
              },
              function(callback) {
                var characteristic = characteristics[characteristicIndex];
                var characteristicInfo = '  ' + characteristic.uuid;

                if (characteristic.name) {
                  characteristicInfo += ' (' + characteristic.name + ')';
                }

                async.series([
                  function(callback) {
                    characteristic.discoverDescriptors(function(error, descriptors) {
                      async.detect(
                        descriptors,
                        function(descriptor, callback) {
                          return callback(descriptor.uuid === '2901');
                        },
                        function(userDescriptionDescriptor){
                          if (userDescriptionDescriptor) {
                            userDescriptionDescriptor.readValue(function(error, data) {
                              if (data) {
                                characteristicInfo += ' (' + data.toString() + ')';
                              }
                              callback();
                            });
                          } else {
                            callback();
                          }
                        }
                      );
                    });
                  },
                  function(callback) {
                        characteristicInfo += '\n    properties  ' + characteristic.properties.join(', ');

                    if (characteristic.properties.indexOf('read') !== -1) {
                      characteristic.read(function(error, data) {
                        if (data) {
                          var string = data.toString('ascii');

                          characteristicInfo += '\n    value       ' + data.toString('hex') + ' | \'' + string + '\'';
                        }
                        callback();
                      });
                    } else {
                      callback();
                    }
                  },
                  function() {
                    console.log(characteristicInfo);
                    characteristicIndex++;
                    callback();
                  }
                ]);
              },
              function(error) {
                serviceIndex++;
                callback();
              }
            );
          });
        },
        function (err) {
          peripheral.disconnect();
        }
      );
    });
  });
}
