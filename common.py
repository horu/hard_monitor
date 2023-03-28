import argparse
import logging
import pathlib


def init_log(level):
    logging.basicConfig(format='%(asctime)s: %(funcName)s (%(filename)s:%(lineno)d): %(message)s',
                        level=logging.getLevelName(level))


PID_FILE = pathlib.Path('/tmp/hard_monitor_ui_default')
SAVE_FILE = pathlib.Path('/tmp/hard_monitor_default.json')


def init():
    parser = argparse.ArgumentParser(prog='hard_monitor', description='Show hardware monitor')
    parser.add_argument('-p', '--period', type=float, default=2.0, help='Timeout for collecting counters.')
    parser.add_argument('-f', '--pidfile', type=pathlib.Path, default=PID_FILE, help='File to save pid.')
    parser.add_argument('-s', '--savefile', type=pathlib.Path, default=SAVE_FILE, help='File to save prev results.')
    parser.add_argument('-l', '--log', type=str, default='ERROR', help='Log level.')
    parser.add_argument('--height', type=int, default=None, help='Location height of panel.')
    parser.add_argument('-g', '--graph_height', type=int, default=17, help='Location height of graph pixels')
    parser.add_argument('-t', '--graph_time', type=int, default=600, help='Total graph timeline sec')
    parser.add_argument('-d', '--graph_debug', action='store_true', help='Debug output for graph')
    parser.add_argument('-c', '--count', type=int, default=0, help='Repeat output.')
    args = parser.parse_args()

    init_log(args.log)
    return args
