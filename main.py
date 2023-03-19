import argparse
import hard_monitor
import time
import pathlib
import subprocess


TMP_FILE = pathlib.Path('/tmp/hard_monitor4234324234324.json')


def send_message(message: str):
    subprocess.Popen(['notify-send', message])
    return


def main():
    parser = argparse.ArgumentParser(prog='hard_monitor', description='Show hardware monitor')
    parser.add_argument('-p', '--period', type=float, default=1.0, help='Timeout for collecting counters.')
    parser.add_argument('-c', '--count', type=int, default=1, help='Repeat output.')
    parser.add_argument('-f', '--file', type=pathlib.Path, default=TMP_FILE, help='File to save prev results.')
    args = parser.parse_args()

    monitor = hard_monitor.HardMonitor(args.period)
    if not monitor.load_json(args.file):
        monitor.update_counters()
        time.sleep(args.period)

    for i in range(0, args.count):
        info = monitor.get_info()
        print(info.line)
        for alarm in info.alarms:
            send_message(alarm)

        if i + 1 < args.count:
            time.sleep(args.period)
    monitor.save_json(args.file)
    monitor.stop()


if __name__ == '__main__':
    main()
