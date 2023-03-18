import os
import threading
import time
import psutil
import json
import pathlib
import typing
import collections
import sensors
import ping3
from threading import Thread

def get_freq_list() -> typing:
    time.sleep(0.05)
    freqs = psutil.cpu_freq(percpu=True)
    freqs_cur = sorted(freq.current for freq in freqs)
    freq_list_size = 4
    freq_list = []
    el_size = len(freqs_cur) / freq_list_size

    el_sum = 0
    for i, f in enumerate(freqs_cur):
        el_sum += f
        if i % el_size == el_size - 1:
            freq_list.append(el_sum / el_size)
            el_sum = 0
    return [round(f / 1000, 1) for f in freq_list]


def convert_net_speed(speed: float) -> str:
    if speed < 0:
        speed = 0
    elif speed >= 100:
        speed = 99

    if speed < 10:
        return '{:3}'.format(round(speed, 1))
    return '·{}'.format(round(speed))


def convert_speed(speed: float) -> str:
    if speed < 0:
        speed = 0
    elif speed >= 1000:
        speed = 999

    if speed < 10:
        speed = round(speed, 1)
    else:
        speed = round(speed)

    return '{:3}'.format(speed)


def get_bat(sensors_list) -> str:
    sensors_chip = [f for f in [chip for chip in sensors_list if chip.prefix == b'BAT1'][0]]
    bat_cur = [f.get_value() for f in sensors_chip if f.label == 'curr1'][0]
    bat_volt = [f.get_value() for f in sensors_chip if f.label == 'in0'][0]
    bat_pow = round(bat_cur * bat_volt)

    sensors_bat = psutil.sensors_battery()
    return '{}{:2} W'.format(' ' if sensors_bat.power_plugged else '-', bat_pow)


def get_gpu_pow(sensors_list) -> str:
    sensors_chip = [f for f in [chip for chip in sensors_list
                                if chip.prefix == b'amdgpu' and chip.path == b'/sys/class/hwmon/hwmon5'][0]]
    gpu_pow = round([f.get_value() for f in sensors_chip if f.label == 'PPT'][0])

    return '{:2} W'.format(gpu_pow)


class HardMonitorInfo:
    def __init__(self):
        self.line: str = ""
        self.alarms: typing.List[str] = []

    def show_temp(self, temp: float, limit: int, name: str) -> str:
        round_temp = round(temp)
        if round_temp < 0:
            round_temp = 0
        if round_temp > limit:
            self.alarms.append('{} critical temp {}/{} °C'.format(name, round_temp, limit))
        return '{:02} °C'.format(round_temp)


class HardMonitor():
    def __init__(self, period_s: float):
        sensors.init()
        self.cpu_counters = None
        self.net_counters = None
        self.disk_counters = None
        self.counters_time = None
        self.ping = None
        self.period_s = period_s
        self.ping_theead = threading.Thread(target=self.update_ping)
        self.ping_theead.start()

    def update_ping(self):
        TIMEOUT = 5

        while True:
            try:
                self.ping = round(ping3.ping('8.8.8.8', unit='ms', timeout=TIMEOUT))
            except:
                self.ping = None
            time.sleep(self.period_s)

    def update_counters(self):
        self.cpu_counters = psutil.cpu_times()
        self.net_counters = psutil.net_io_counters()
        self.disk_counters = psutil.disk_io_counters()
        self.counters_time = time.time()

    def load_json(self, file: pathlib.Path) -> bool:
        try:
            with file.open('r') as output:
                dump = json.load(output)
            CpuCounters = collections.namedtuple('CpuCounters', dump['cpu_counters'])
            self.cpu_counters = CpuCounters(**dump['cpu_counters'])
            NetCounters = collections.namedtuple('NetCounters', dump['net_counters'])
            self.net_counters = NetCounters(**dump['net_counters'])
            DiskCounters = collections.namedtuple('DiskCounters', dump['disk_counters'])
            self.disk_counters = DiskCounters(**dump['disk_counters'])
            self.counters_time = dump['counters_time']
        except Exception:
            return False
        return True

    def save_json(self, file: pathlib.Path) -> None:
        dump = {
            'counters_time': self.counters_time,
            'cpu_counters': self.cpu_counters._asdict(),
            'net_counters': self.net_counters._asdict(),
            'disk_counters': self.disk_counters._asdict(),
        }
        json_dump = json.dumps(dump, sort_keys=True, indent=4)

        with file.open('w') as outfile:
            outfile.write(json_dump)

    def get_info(self) -> HardMonitorInfo:
        cpu_freq_list = get_freq_list()

        cpu_counters_prev = self.cpu_counters
        net_counters_prev = self.net_counters
        disk_counters_prev = self.disk_counters
        counters_time_prev = self.counters_time

        self.update_counters()

        time_diff = self.counters_time - counters_time_prev

        cpu_counters_sum_next = sum(v for k, v in self.cpu_counters._asdict().items() if k != 'idle')
        cpu_counters_sum_prev = sum(v for k, v in cpu_counters_prev._asdict().items() if k != 'idle')
        cpu_diff = round((cpu_counters_sum_next - cpu_counters_sum_prev) / time_diff, 1)
        net_recv = (self.net_counters.bytes_recv - net_counters_prev.bytes_recv) / time_diff / 1024 / 1024
        net_send = (self.net_counters.bytes_sent - net_counters_prev.bytes_sent) / time_diff / 1024 / 1024
        disk_r = (self.disk_counters.read_bytes - disk_counters_prev.read_bytes) / time_diff / 1024 / 1024
        disk_w = (self.disk_counters.write_bytes - disk_counters_prev.write_bytes) / time_diff / 1024 / 1024
        #disk_r_t = disk_counters.read_time - self.disk_counters.read_time
        #disk_w_t = disk_counters.write_time - self.disk_counters.write_time

        loadavg = round(os.getloadavg()[0], 1)

        sensors_list = [c for c in sensors.iter_detected_chips()]
        bat_pow = get_bat(sensors_list)
        gpu_pow = get_gpu_pow(sensors_list)

        sensors_temp = psutil.sensors_temperatures()
        cpu_temp = [t.current for t in sensors_temp['k10temp'] if t.label == 'Tctl'][0]
        nvme_temp = [t.current for t in sensors_temp['nvme'] if t.label == 'Sensor 1'][0]
        gpu_temp = [t.current for t in sensors_temp['amdgpu'] if t.label == 'junction'][0]

        memory = psutil.virtual_memory()
        used_memory = round(memory.used / 1024 / 1024 / 1024, 1)
        swap = psutil.swap_memory()
        used_swap = round(swap.used / 1024 / 1024 / 1024, 1)

        info = HardMonitorInfo()
        info.line = '[{:4} {:4} ({}) Ghz {}] ({:3}) {:4} GB [{} MB/s {} MB/s {:4} ms] ' \
                    '[{} MB/s {} MB/s {}] {} [{} {}]'.format(
            cpu_diff, loadavg, ' '.join('{:03}'.format(f) for f in cpu_freq_list),
            info.show_temp(cpu_temp, 95, 'CPU'),
            used_swap, used_memory,
            convert_speed(net_recv), convert_speed(net_send), self.ping if self.ping else '****',
            convert_speed(disk_r), convert_speed(disk_w), info.show_temp(nvme_temp, 65, 'NVME'),
            bat_pow, gpu_pow, info.show_temp(gpu_temp, 95, 'GPU'),
        )
        return info
