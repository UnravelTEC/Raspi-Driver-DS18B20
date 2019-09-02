# DS18B20

Software to read out DS18B20 sensor values over onewire on Raspberry Pi.

This software is licenced under GPLv3 by [UnravelTEC OG](https://unraveltec.com) (https://unraveltec.com), 2019.

## Prerequisites

You might need to run the following commands as root e.g. by typing `sudo` before running a specific command.

### Enable onewire interface

add `dtoverlay=w1-gpio,gpiopin=4` to `/boot/config.txt`

Note: Standard pin is 4 - argument may be omitted then.

### Wiring DS18B20 to Raspberry Pi
- DS18B20: VIN -> Pi: 3.3V
- DS18B20: Singal -> Pi: pin 4 (or else) - and add a pullup Resistor (e.g. 10K) between this pin and 3v3, or else it wont work!
- DS18B20: GND -> Pi: GND (use one of GND pinouts)


## installing as a service

```
./install.sh
```

the service writes a file `/run/sensors/ds18b20/last` and updates it every second (which resides in RAM) - it is meant to be read out by prometheus.
