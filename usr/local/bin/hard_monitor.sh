#!/bin/bash

USER=anslyshik

chmod 444 /sys/class/powercap/intel-rapl\:0/energy_uj
export DISPLAY=":0.0"
sudo -u $USER python3 /home/anslyshik/tmp/py_proj/hard_monitor/ui.py -f /tmp/hard_monitor_ui_autorun --logfile syslog
