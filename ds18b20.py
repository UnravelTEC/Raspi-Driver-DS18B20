#!/usr/bin/python3
# coding=utf-8
#
# Copyright © 2018 UnravelTEC
# Michael Maier <michael.maier+github@unraveltec.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# If you want to relicense this code under another license, please contact info+github@unraveltec.com.

import sdnotify
n = sdnotify.SystemdNotifier()
n.notify("WATCHDOG=1")

import time
starttime = time.time()
print('started at', starttime)
import json
import sys
import os, signal
from subprocess import call

from argparse import ArgumentParser, RawTextHelpFormatter
import textwrap

import pprint
import json

from copy import deepcopy
import paho.mqtt.client as mqtt

print('after imports', time.time() - starttime)
n.notify("WATCHDOG=1")

def eprint(*args, **kwargs):
  print(*args, file=sys.stderr, **kwargs)
  sys.stderr.flush()

# config order (later overwrites newer)
# 1. default cfg
# 2. config file
# 3. cmdline args
# 4. runtime cfg via MQTT $host/sensors/$name/config

name = "DS18B20" # Uppercase
cfg = {
  "interval": 1,
  "gpio": -1,
  "brokerhost": "localhost",
  "prometheus": False,
  "configfile": "/etc/lcars/" + name.lower() + ".yml"
}

parser = ArgumentParser(description=name + ' driver.\n\nDefaults in {curly braces}', formatter_class=RawTextHelpFormatter)
parser.add_argument("-i", "--interval", type=float, default=cfg['interval'],
                            help="measurement interval in s (float, default "+str(cfg['interval'])+")", metavar="x")
parser.add_argument("-D", "--debug", action='store_true', #cmdline arg only, not in config
                            help="print debug messages")

# for sensors/actuators on GPIOs
parser.add_argument("-g", "--gpio", type=int, default=cfg['gpio'],
                            help="use gpio number {"+str(cfg['gpio'])+"} (BCM) for 1-w line (used for reset)", metavar="ii")

# if using MQTT
parser.add_argument("-o", "--brokerhost", type=str, default=cfg['brokerhost'],
                            help="use mqtt broker (addr: {"+cfg['brokerhost']+"})", metavar="addr")

parser.add_argument("-p", "--prometheus", dest="prometheus", action='store_true',
                        help="enable output to prometheus scrapefile")

parser.add_argument("-r", "--reset", dest="reset", action='store_true',
                        help="enable reset on start")

# if using configfiles
parser.add_argument("-c", "--configfile", type=str, default=cfg['configfile'],
                            help="load configfile ("+cfg['configfile']+")", metavar="nn")

args = parser.parse_args()
print('after args', time.time() - starttime)
n.notify("WATCHDOG=1")
DEBUG = args.debug

fcfg = deepcopy(cfg) # final config used
if os.path.isfile(args.configfile) and os.access(args.configfile, os.R_OK):
  with open(args.configfile, 'r') as ymlfile:
    import yaml
    filecfg = yaml.load(ymlfile)
    print("opened configfile", args.configfile)
    for key in cfg:
      if key in filecfg:
        value = filecfg[key]
        fcfg[key] = value
        print("used file setting", key, value)
    for key in filecfg:
      if not key in cfg:
        value = filecfg[key]
        fcfg[key] = value
        print("loaded file setting", key, value)
else:
  print("no configfile found at", args.configfile)
DEBUG and print('config from default & file', fcfg)

argdict = vars(args)
for key in cfg:
  if key in argdict and argdict[key] != cfg[key]:
    value = argdict[key]
    fcfg[key] = value
    print('cmdline param', key, 'used with', value)

cfg = fcfg
required_params = ['brokerhost']
for param in required_params:
  if not param in cfg or not cfg[param]:
    eprint('param', param, 'missing from config, exit')
    exit(1)


print("config used:", cfg)
print('after cfg', time.time() - starttime)
n.notify("WATCHDOG=1")

gpioline = ""
with open("/boot/config.txt") as lines:
  for line in lines:
    if line.startswith("dtoverlay=w1-gpio"):
      gpioline = line
      break

if not gpioline:
  eprint("w1 not found in /boot/config.txt, is it enabled?")

if "gpio" in cfg and cfg['gpio'] == -1 :
  splitscomma = gpioline.split(",",1)
  if len(splitscomma) > 1:
    kv = splitscomma[1].split("=",1)
    v = kv[1].split("#",1)
    cfg['gpio'] = int(v[0].strip())
    print("using gpio", cfg['gpio'], "from /boot/config.txt")
  else:
    cfg['gpio'] = 4
    print("using gpio", cfg['gpio'], "(default)")

if "gpio" in cfg:
  print("using gpio", cfg['gpio'], "for sensor")

  import RPi.GPIO as IO
  IO.setmode (IO.BCM)
  IO.setwarnings(False)

SENSOR_NAME = name.lower()

hostname = os.uname()[1]

brokerhost = cfg['brokerhost']

customsensors = None
if cfg['sensors']:
  customsensors = cfg['sensors']

def mqttConnect():
  while True:
    try:
      print("mqtt: Connecting to", brokerhost)
      client.connect(brokerhost,1883,60)
      print('mqtt: connect successful')
      break
    except Exception as e:
      eprint('mqtt: Exception in client.connect to "' + brokerhost + '", E:', e)
      print('mqtt: next connect attempt in 3s... ', end='')
      time.sleep(3)
      print('retry.')

def mqttReconnect():
  print('mqtt: attempting reconnect')
  while True:
    try:
      client.reconnect()
      print('mqtt: reconnect successful')
      break
    except ConnectionRefusedError as e:
      eprint('mqtt: ConnectionRefusedError', e, '\nnext attempt in 3s')
      time.sleep(3)

def onConnect(client, userdata, flags, rc):
  try:
    if rc != 0:
      eprint('mqtt: failure on connect to broker "'+ brokerhost+ '", result code:', str(rc))
      if rc == 3:
        eprint('mqtt: broker "'+ brokerhost+ '" unavailable')
    else:
      print("mqtt: Connected to broker", brokerhost, "with result code", str(rc))
      return
  except Exception as e:
    eprint('mqtt: Exception in onConnect', e)
  mqttConnect()

MQTT_ERR_SUCCESS = mqtt.MQTT_ERR_SUCCESS
MQTT_ERR_NO_CONN = mqtt.MQTT_ERR_NO_CONN
def mqttPub(topic, payload, retain = True):
  try:
    (DEBUG or first_run) and print(topic, payload, "retain =", retain)
    ret = client.publish(topic, payload, retain=retain)
    if ret[0] == MQTT_ERR_SUCCESS:
      n.notify("WATCHDOG=1")
    elif ret[0] == MQTT_ERR_NO_CONN:
      eprint('no mqtt connnection')
      mqttReconnect()
    else:
      eprint('mqtt publishing not successful,', ret)
  except Exception as e:
    eprint('Exception in client.publish', e, topic, payload_json)

def mqttJsonPub(topic, payload_json, retain=True):
  mqttPub(topic, json.dumps(payload_json, separators=(',', ':'), sort_keys=True), retain)

client = mqtt.Client(client_id=name, clean_session=True) # client id only useful if subscribing, but nice in logs # clean_session if you don't want to collect messages if daemon stops
client.on_connect = onConnect
mqttConnect()
client.loop_start()

topic_json = hostname + '/sensors/' + SENSOR_NAME.upper() + '/temperature'

jsontags = {
  "interval_s": int(cfg['interval'])
  }
n.notify("WATCHDOG=1")
print('after mqtt', time.time() - starttime)

def exit_gracefully(a=False,b=False):
  print("exit gracefully...")
  client.disconnect()
  exit(0)

def exit_hard():
  print("exiting hard...")
  exit(1)

signal.signal(signal.SIGINT, exit_gracefully)
signal.signal(signal.SIGTERM, exit_gracefully)

first_run = True

MEAS_INTERVAL = cfg['interval']

if(cfg['prometheus']):
  LOGFOLDER = '/run/sensors/ds18b20'
  LOGFILE = LOGFOLDER+'/last'
  call(["mkdir", "-p", LOGFOLDER])

sysbus="/sys/bus/w1/devices/"
onewclass="28"

searchfile=sysbus + "w1_bus_master1/w1_master_search"
def disable_search():
  try:
    with open(searchfile,'w+') as lines:
      for line in lines:
        if line.strip() != "0":
          print("w1 search active (",line.strip(),") disabling")
          lines.write("0")
        else:
          print("w1 search already disabled, OK")
  except Exception as e:
    eprint('error opening', searchfile, ":", e)

disable_search()

def reset():
  global first_run
  print("reset called")
  first_run = True
  disable_search()
  if not 'gpio' in cfg or cfg['gpio'] == -1:
    eprint("gpio unknown, cannot reset")
    exit_gracefully()
  for sensorfolder in os.listdir(sysbus):
    if sensorfolder.startswith(onewclass):
      print("removing", sensorfolder, "…")
      try:
        with open(sysbus + "w1_bus_master1/w1_master_remove",'w') as lines:
          lines.write(sensorfolder)
      except Exception as e:
        eprint('error removing', sensorfolder, ":", e)
    time.sleep(0.5)
  for sensorfolder in os.listdir(sysbus):
    if sensorfolder.startswith(onewclass):
      eprint("error,", sensorfolder, "still here")

  print("forcing w1-line down")
  IO.setup(cfg['gpio'], IO.OUT)
  IO.output(cfg['gpio'], False)
  time.sleep(0.5)
  IO.output(cfg['gpio'], True)
  time.sleep(1)
  print("starting search")
  with open(searchfile,'w+') as lines:
    lines.write("1")

  print("search in progress - ", end='')
  for i in range(12):
    print(12-i, end=' ')
    time.sleep(1)
  print('\nwaiting for sensor ', end='')

  found_sensors = []
  for sensorfolder in os.listdir(sysbus):
    if sensorfolder.startswith(onewclass):
      found_sensors.append(sensorfolder)

  if customsensors:
    extra_sensors = []
    missing_sensors = []
    for csensor in customsensors:
      if csensor not in found_sensors:
        missing_sensors.append(csensor)
    for fsensor in found_sensors:
      if fsensor not in customsensors:
        extra_sensors.append(fsensor)
    if missing_sensors:
      print("These sensors from config not found:", missing_sensors)
    else:
      print("All configured sensors found.")
    if extra_sensors:
      print("These sensors are there, but not in config", extra_sensors)

  if len(found_sensors) == 0:
    eprint("no sensors appeared after reset, exit")
    exit_gracefully()

if args.reset:
  reset()

sensorlist = {}
# sensorlist = { "sensorid" : "checked|to_check", ... }

error_counts = {}  # { "sensorid" : <int> }

n.notify("READY=1") #optional after initializing
n.notify("WATCHDOG=1")
print('starting loop', time.time() - starttime)
while True:
  run_started_at = time.time()

  handled_sensors = 0

  foundsensor = False
  for sensorid in sensorlist:
    sensorlist[sensorid] = "to_check"

  DEBUG and print('opening', sysbus, ":", os.listdir(sysbus))
  for sensorfolder in os.listdir(sysbus):
    if sensorfolder.startswith(onewclass):
      DEBUG and print('opening', sysbus + sensorfolder +'/w1_slave')
      try:
        with open(''.join([sysbus, sensorfolder, "/w1_slave"])) as lines:
          DEBUG and print('opened', sysbus + sensorfolder +'/w1_slave')

          foundsensor = True
          if sensorfolder in sensorlist:
            sensorlist[sensorfolder] = "checked"
          else:
            sensorlist[sensorfolder] = "new"

          is_ok = False
          temperature = -4747
          for line in lines:
            content = line.strip()
            if is_ok: # reached line2 successful
              # line 2
              splitcontent = content.split("=")
              if len(splitcontent) == 2:
                stags = jsontags.copy()
                stags['id'] = "1w-" + sensorfolder
                temperature = round(float(splitcontent[1])/1000, 3)
                error_counts[sensorfolder] = 0
                break
            if content.endswith("YES"): # still at line 1
              DEBUG and print(sensorfolder, "OK")
              is_ok = True

          if temperature == -4747: # checksum NOK or other error
            if sensorfolder in error_counts:
              error_counts[sensorfolder] += 1
            else:
              error_counts[sensorfolder] = 1
            eprint("DS18B20 readout error for", sensorfolder, ", error count:",error_counts[sensorfolder],"content:", *lines, '.')
            temperature = -42 # to let it ignored in next if statement

          if temperature == 85.0 or temperature < -55 or temperature > 125: # error condition
            if sensorfolder in error_counts:
              error_counts[sensorfolder] += 1
            else:
              error_counts[sensorfolder] = 1
            eprint("DS18B20 readout error for", sensorfolder, ", error count:", error_counts[sensorfolder], "t =", temperature, '.')

          if error_counts[sensorfolder] > 4:
            reset()
            break

          if not is_ok:
            continue

          handled_sensors += 1

          # print(temperature)
          datafield = "air_degC"
          if customsensors and sensorfolder in customsensors:
            csenscfg = customsensors[sensorfolder]
            if "tags" in csenscfg:
              for key in csenscfg["tags"]:
                stags[key] = csenscfg["tags"][key]
            if "fieldname" in csenscfg:
              datafield = csenscfg["fieldname"]

          payload = {
            "tags": stags,
            "values": {
              datafield: temperature
              },
            "UTS": round(run_started_at, 3)
            }
          mqttJsonPub(topic_json, payload)
          if(cfg['prometheus']):
            logfilehandle = open(LOGFILE, "w",1)
            prometh_string = 'temperature_degC{sensor="DS18B20",id="1w-' + sensorfolder + '"} ' + str(temperature) + '\n'
            logfilehandle.write(prometh_string)
            logfilehandle.close()
      except Exception as e:
        print(''.join([sysbus, sensorfolder, " vanished, continue"]))

      time.sleep(0.1) # give bus/voltage supply time to settle

  if handled_sensors == 0:
    print("no sensor yielded valid data, reset")
    reset()
    continue


  # FIXXME rework
  for sensorid in sensorlist:
    if sensorlist[sensorid] == "checked":
      continue
    if sensorlist[sensorid] == "new":
      print("New Sensor", sysbus + sensorid, "found")
    if sensorlist[sensorid] == "to_check":
      print("Sensor with id", sensorid, "vanished")
      sensorlist[sensorid] = "to_delete"

  delete = [key for key in sensorlist if sensorlist[key] == "to_delete"]
  for key in delete: del sensorlist[key]

  if not customsensors: ## FIXME
    broken = False
    for csensorid in customsensors:
      if not csensorid in sensorlist:
        eprint("sensor", csensorid, "from config missing, reset")
        reset()
        broken = True
        break
    if broken:
      continue


  # if not foundsensor:
  #   if first_run:
  #     eprint('no DS18B20 sensors found on initial start', sysbus, ":", os.listdir(sysbus))
  # else:
  #     eprint('all DS18B20 sensors vanished', sysbus, ":", os.listdir(sysbus))
  #  eprint("try reset")
    # reset()
    # exit_gracefully()


  first_run = False

  run_finished_at = time.time()
  run_duration = run_finished_at - run_started_at

  DEBUG and print("duration of run: {:10.4f}s.".format(run_duration))

  to_wait = MEAS_INTERVAL - run_duration
  if to_wait > 0.002:
    DEBUG and print("wait for {0:4f}s".format(to_wait))
    time.sleep(to_wait - 0.002)
  else:
    DEBUG and print("no wait, {0:4f}ms over".format(- to_wait*1000))
