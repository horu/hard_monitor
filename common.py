import argparse
import logging
import os
import pathlib
import signal
from logging.handlers import SysLogHandler

import typing

SERVICE_NAME = 'hard_monitor'


class log:
    logger = logging.getLogger(SERVICE_NAME)

    @staticmethod
    def init(level, filename):
        handler = logging.StreamHandler()
        if str(filename) == 'syslog':
            handler = logging.handlers.SysLogHandler(facility=SysLogHandler.LOG_DAEMON, address='/dev/log')
        elif filename is not None:
            handler = logging.FileHandler(filename)

        log.logger.setLevel(logging.getLevelName(level))
        f = logging.Formatter(
            '{}: %(asctime)s: %(levelname)s: %(funcName)s (%(filename)s:%(lineno)d): %(message)s', SERVICE_NAME)
        handler.setFormatter(f)
        log.logger.addHandler(handler)

    @staticmethod
    def get_level():
        return log.logger.getEffectiveLevel()

    @staticmethod
    def _log_call(level, *args, **kwargs):
        msg = '{} | {}'.format(
            ' | '.join(str(value) for value in args),
            ' | '.join('{}={}'.format(key, value) for key, value in kwargs.items()),
        )
        log_c = getattr(log.logger, level)
        log_c(msg, stacklevel=3)

    @staticmethod
    def debug(*args, **kwargs):
        log._log_call('debug', *args, **kwargs)

    @staticmethod
    def info(*args, **kwargs):
        log._log_call('info', *args, **kwargs)

    @staticmethod
    def error(*args, **kwargs):
        log._log_call('error', *args, **kwargs)


def object_to_str(obj) -> str:
    return '{}: {}'.format(
        type(obj).__name__,
        ', '.join('{}={}'.format(name, value) for name, value in obj.__dict__.items()),
    )


PID_FILE = pathlib.Path('/tmp/hard_monitor_ui_default')
SAVE_FILE = pathlib.Path('/tmp/hard_monitor_default.json')


def init():
    parser = argparse.ArgumentParser(prog='hard_monitor', description='Show hardware monitor')
    parser.add_argument('-p', '--period', type=float, default=2.0, help='Timeout for collecting counters.')
    parser.add_argument('-f', '--pidfile', type=pathlib.Path, default=None, help='File to save pid.')
    parser.add_argument('-s', '--savefile', type=pathlib.Path, default=SAVE_FILE, help='File to save prev results.')
    parser.add_argument('-l', '--log', type=str, default='INFO', help='Log level.')
    parser.add_argument('--logfile', type=pathlib.Path, default=None,
                        help='File to log. Default stderr. Set "syslog" to log to syslog')
    parser.add_argument('--height', type=int, default=None, help='Location height of panel.')
    parser.add_argument('-g', '--graph_height', type=int, default=17, help='Location height of graph pixels')
    parser.add_argument('-t', '--graph_time', type=int, default=600, help='Total graph timeline sec')
    parser.add_argument('-d', '--graph_debug', action='store_true', help='Debug output for graph')
    parser.add_argument('-c', '--count', type=int, default=0, help='Repeat output.')
    args = parser.parse_args()

    log.init(args.log, args.logfile)

    current_pid = os.getpid()
    log.info('init 0xff00f1f1. current pid', current_pid)
    if args.pidfile:
        try:
            with args.pidfile.open('r') as file:
                pid = int(file.readline())
                log.info('pid to kill', pid)
                os.kill(pid, signal.SIGKILL)
        except Exception as e:
            log.error('kill pid error', e)

        with args.pidfile.open('w') as file:
            file.write(str(current_pid))
    return args


def convert_speed(speed: float) -> str:
    if speed < 0:
        speed = 0
    elif speed >= 1000:
        speed = 999

    if speed <= 9.9:
        speed = round(speed, 1)
    else:
        speed = round(speed)

    return '{:3}'.format(speed)


def create_temp_alarm(name: str, temp: float, limit: float) -> typing.Optional[str]:
    if temp >= limit:
        return '{} crit t {:2}/{:2} °C'.format(name, round(temp), round(limit))
    return None
