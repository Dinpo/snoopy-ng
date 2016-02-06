#!/bin/bash
# This script puts the wireless interface in monitor mode and starts Snoopy

at 10 PM -f `pwd`/suspend.sh         > /dev/null &

IFACE=`ifconfig -a | sed 's/[ \t].*//;/^$/d' | grep wlan`;
sudo ifconfig $IFACE down;

mkdir -p /tmp/Snoopy/

bash "$PWD/monitor_mode.sh" &
bash "$PWD/start_snooping.sh" &