import argparse
import hard_monitor
import time
import pathlib


TMP_FILE = pathlib.Path('/tmp/hard_monitor4234324234324.json')


def main():
    parser = argparse.ArgumentParser(prog='hard_monitor', description='Show hardware monitor')
    parser.add_argument('-t', '--timeout', type=float, default=1.0, help='Timeout for collecting counters.')
    parser.add_argument('-c', '--count', type=int, default=1, help='Repeat output.')
    parser.add_argument('-f', '--file', type=pathlib.Path, default=TMP_FILE, help='File to save prev results.')
    args = parser.parse_args()

    monitor = hard_monitor.HardMonitor()
    if not monitor.load_json(args.file):
        monitor.update_counters()
        time.sleep(args.timeout)

    for i in range(0, args.count):
        print(monitor.get_info())
        if i + 1 < args.count:
            time.sleep(args.timeout)
    monitor.save_json(args.file)


if __name__ == '__main__':
    main()
