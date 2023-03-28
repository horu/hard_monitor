#!/bin/bash
while true; do
  python3 /home/anslyshik/tmp/py_proj/hard_monitor/ui.py -f /tmp/hard_monitor_ui_autorun --logfile syslog
  sleep 1
done
