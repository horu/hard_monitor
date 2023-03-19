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
import datetime


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


def create_temp_alarm(name: str, temp: float, limit: float) -> typing.Optional[str]:
    if temp >= limit:
        return '{} critical temp {}/{} °C'.format(name, temp, limit)
    return None


class BatteryInfo:
    def __init__(self):

        bat_path = pathlib.Path('/sys/class/power_supply/BAT1')
        try:
            with (bat_path / 'voltage_now').open('r') as file:
                self.voltage_now_v = int(file.readline()) / 1000000
            with (bat_path / 'voltage_min_design').open('r') as file:
                self.voltage_min_design_v = int(file.readline()) / 1000000
            with (bat_path / 'charge_now').open('r') as file:
                self.charge_now_ah = int(file.readline()) / 1000000
            with (bat_path / 'current_now').open('r') as file:
                self.current_now_a = int(file.readline()) / 1000000
            with (bat_path / 'status').open('r') as file:
                self.charge_status = False if 'Discharging' in file.readline() else True
        except:
            self.voltage_now_v = 0
            self.voltage_min_design_v = 0
            self.charge_now_ah = 0
            self.current_now_a = 0
            self.charge_status = False

    def __str__(self):
        power_w = self.voltage_now_v * self.current_now_a
        capacity_wh = self.charge_now_ah * self.voltage_min_design_v

        return '[{}{:2} W {:4} Wh]'.format('+' if self.charge_status else ' ', round(power_w), round(capacity_wh, 1))


class GpuInfo:
    def __init__(self):
        hwmon_path = self._find_hwmon()
        try:
            with (hwmon_path / 'power1_average').open('r') as file:
                self.power1_average_w = int(file.readline()) / 1000000
            with (hwmon_path / 'temp2_input').open('r') as file:
                self.temp2_input_c = int(file.readline()) / 1000
            with (hwmon_path / 'temp2_crit').open('r') as file:
                self.temp2_crit_c = int(file.readline()) / 1000 - 5
            # with (hwmon_path / 'freq1_input').open('r') as file:
            #     self.freq1_input_ghz = int(file.readline()) / 1000000000
            # with (hwmon_path / 'freq2_input').open('r') as file:
            #     self.freq2_input_ghz = int(file.readline()) / 1000000000
        except:
            self.power1_average_w = 0
            self.temp2_input_c = 0
            self.temp2_crit_c = 100

        self.alarm = create_temp_alarm('GPU', self.temp2_input_c, self.temp2_crit_c)

    def _find_hwmon(self) -> typing.Optional[pathlib.Path]:
        hwmon_dir = pathlib.Path('/sys/class/hwmon/')
        for hwmon in hwmon_dir.iterdir():
            hwmon_device = hwmon / 'device' / 'device'
            if hwmon_device.exists() and hwmon_device.is_file():
                with hwmon_device.open('r') as file:
                    if '0x7340' in file.readline():
                        return hwmon
        return None

    def __str__(self):
        return '[{:2} W {:2} °C]'.format(
        # return '[({:3} {:3}) Ghz {:2} W {:2} °C]'.format(
            # round(self.freq1_input_ghz, 1),
            # round(self.freq2_input_ghz, 1),
            round(self.power1_average_w),
            round(self.temp2_input_c),
        )


class HardMonitorInfo:
    def __init__(self):
        self.battery = BatteryInfo()
        self.gpu = GpuInfo()

        self.line: str = ""
        self.alarms: typing.List[str] = []

        if self.gpu.alarm:
            self.alarms.append(self.gpu.alarm)

    def show_temp(self, temp: float, limit: int, name: str) -> str:
        round_temp = round(temp)
        if round_temp < 0:
            round_temp = 0
        alarm = create_temp_alarm(name, round_temp, limit)
        if alarm:
            self.alarms.append(alarm)
        return '{:2} °C'.format(round_temp)


class HardMonitor():
    def __init__(self, period_s: float):
        sensors.init()
        self.cpu_counters = None
        self.net_counters = None
        self.disk_counters = None
        self.counters_time = None
        self.ping = None
        self.period_s = period_s
        self.stopping = threading.Event()
        self.ping_theead = threading.Thread(target=self.update_ping)
        self.ping_theead.start()

    def update_ping(self):
        TIMEOUT = 5

        while not self.stopping.is_set():
            try:
                self.ping = round(ping3.ping('8.8.8.8', unit='ms', timeout=TIMEOUT))
            except:
                self.ping = None
            time.sleep(self.period_s)

    def stop(self):
        self.stopping.set()

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

        sensors_temp = psutil.sensors_temperatures()
        cpu_temp = [t.current for t in sensors_temp['k10temp'] if t.label == 'Tctl'][0]
        nvme_temp = [t.current for t in sensors_temp['nvme'] if t.label == 'Sensor 1'][0]

        memory = psutil.virtual_memory()
        used_memory = round(memory.used / 1024 / 1024 / 1024, 1)
        swap = psutil.swap_memory()
        used_swap = round(swap.used / 1024 / 1024 / 1024, 1)

        d_time = datetime.datetime.now().strftime("%a %d.%m.%y %H:%M:%S")
        info = HardMonitorInfo()
        info.line = '[{:4} {:4} ({}) Ghz {}] [{:3} {:4} GB] {} [{} MB/s {} MB/s {:4} ms] ' \
                    '[{} MB/s {} MB/s {}] {} [{}]'.format(
            cpu_diff, loadavg, ' '.join('{:03}'.format(f) for f in cpu_freq_list),
            info.show_temp(cpu_temp, 95, 'CPU'),
            used_swap, used_memory,
            info.gpu,
            convert_speed(net_recv), convert_speed(net_send), self.ping if self.ping else '****',
            convert_speed(disk_r), convert_speed(disk_w), info.show_temp(nvme_temp, 65, 'NVME'),
            info.battery,
            d_time,
        )
        return info
