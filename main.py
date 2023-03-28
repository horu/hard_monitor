import time
import pathlib
import subprocess

import hard_monitor
import common


TMP_FILE = pathlib.Path('/tmp/hard_monitor_default.json')


def send_message(message: str):
    subprocess.Popen(['notify-send', message])
    return


def main():
    args = common.init()

    monitor = hard_monitor.HardMonitor(args.period)
    if not monitor.load_json(args.savefile):
        monitor.update_counters()
        time.sleep(args.period)

    i = args.count
    while True:
        info = monitor.get_info()
        print(info)
        for alarm in info.alarms:
            send_message(alarm)

        i -= 1
        if i <= 0 and args.count:
            break
        time.sleep(args.period)
    monitor.save_json(args.savefile)
    monitor.stop()
    pass


if __name__ == '__main__':
    main()
