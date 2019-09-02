#!/bin/zsh
# reads out one-wire ds18b20 temperature sensors

datadir=/run/sensors/ds18b20
buffer=$datadir/last

sysbus="/sys/bus/w1/devices/"
class="28"

function finish {
  rm -rf ${buffer}
}

trap finish EXIT

devices=$(find $sysbus -name "$class*"|sed -z 's/\n/ /')

if [ ! "$devices" ]; then
  echo "ds18b20 service: no devices found, exiting"
  exit 1
fi

mkdir -p $datadir

touch ${buffer}
chown www-data ${buffer}

echo "ds18b20 starting, found devices: $devices"

while true; do
  
  i=1
  buffercontent=""
  for device in $(find $sysbus -name "$class*"|sed -z 's/\n/ /'); do
    value=$(cat $device/w1_slave)
    if [ "$(echo $value|head -1|tail -c 4)" = "YES" ]; then
      temp="$(echo $value|tail -1|cut -d"=" -f 2).0" #.0 for switching zsh arithmethics to float
      temp=$((temp/1000))
      buffercontent="$buffercontent$(printf "temperature_degC{sensor=\"ds18b20\",id=\"%s\"} %g" $i $temp)\n"  #printf because zsh evaluates often to eg 27.437000000000001
    fi
    let i=i+1
  done

  echo -n "$buffercontent" > ${buffer}
  # echo -n "."

done
