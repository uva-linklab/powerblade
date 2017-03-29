alter table dat_powerblade add index devEnergy (timestamp, deviceMAC, energy);
alter table dat_powerblade add index devPower (timestamp, deviceMAC, power);

alter table dat_powerblade add index devDevPower (deviceMAC, power, timestamp);

alter table dat_powerblade add index devTimePower (deviceMAC, timestamp, power);

alter table dat_powerblade add index devTimeEnergy (deviceMAC, timestamp, energy);

alter table dat_blees add index devLux (deviceMAC, lux, timestamp);

