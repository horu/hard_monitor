import fcntl
import os
import struct
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
import netifaces
import socket
import array
import subprocess


class Wlan:
    SIOCGIWRATE = 0x8B21  # get default bit rate (bps)
    IFNAMSIZE = 16

    def __init__(self, iface: str):
        self.iface = iface
        self.sockfd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.fmt = "ibbH"

    def iw_get_bitrate(self) -> typing.Optional[int]:
        try:
            status, result = self._iw_get_ext(self.iface, Wlan.SIOCGIWRATE)
            return self._parse_data(self.fmt, result)[0]
        except:
            pass
        return None

    def _parse_data(self, fmt, data):
        """ Unpacks raw C data. """
        size = struct.calcsize(fmt)
        idx = 0

        datastr = data[idx:idx + size]
        self.idx = idx+size
        value = struct.unpack(fmt, datastr)

        # take care of a tuple like (int, )
        if len(value) == 1:
            return value[0]
        else:
            return value

    def _iw_get_ext(self, ifname, request, data=None):
        """ Read information from ifname. """
        buff = Wlan.IFNAMSIZE-len(ifname)
        ifreq = array.array('b', ifname.encode('utf-8') + b'\0'*buff)
        # put some additional data behind the interface name
        if data is not None:
            ifreq.extend(data)
        else:
            # extend to 32 bytes for ioctl payload
            ifreq.extend(b'\0'*16)

        result = fcntl.ioctl(self.sockfd.fileno(), request, ifreq)
        return result, ifreq[Wlan.IFNAMSIZE:]


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


def get_invalid_mark(size: int) -> str:
    return '*' * size


def print_invalid_maybe(value: typing.Optional, size: int) -> str:
    if value is None:
        return get_invalid_mark(size)
    return value


class Battery:
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


class Cpu:
    def __init__(self):
        self.cpu_counters = psutil.cpu_times()
        self.counters_time = time.time()

        self.loadavg_current = 0
        self.loadavg_1m = 0
        self.freq_list_ghz = []
        self.temp_c = 0
        self.temp_crit_c = 90

        self.alarm = None

    def calculate(self):
        self.freq_list_ghz = self._get_freq_list()

        cpu_counters_prev = self.cpu_counters
        counters_time_prev = self.counters_time

        self.cpu_counters = psutil.cpu_times()
        self.counters_time = time.time()

        time_diff = self.counters_time - counters_time_prev

        cpu_counters_sum_next = sum(v for k, v in self.cpu_counters._asdict().items() if k != 'idle')
        cpu_counters_sum_prev = sum(v for k, v in cpu_counters_prev._asdict().items() if k != 'idle')
        self.loadavg_current = round((cpu_counters_sum_next - cpu_counters_sum_prev) / time_diff, 1)

        self.loadavg_1m = round(os.getloadavg()[0], 1)

        sensors_temp = psutil.sensors_temperatures()
        try:
            self.temp_c = [t.current for t in sensors_temp['k10temp'] if t.label == 'Tctl'][0]
        except:
            self.temp_c = 0

        self.alarm = create_temp_alarm('CPU', self.temp_c, self.temp_crit_c)

    def _get_freq_list(self) -> typing.List[float]:
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
        return [f / 1000 for f in freq_list]

    def __str__(self):
        return '[{:4} {:4} ({}) Ghz {:2} °C]'.format(
            round(self.loadavg_current, 1),
            round(self.loadavg_1m, 1),
            ' '.join('{:03}'.format(round(f, 1)) for f in self.freq_list_ghz),
            round(self.temp_c),
        )


class Gpu:
    def __init__(self):
        hwmon_path = self._find_hwmon()
        try:
            with (hwmon_path / 'power1_average').open('r') as file:
                self.power1_average_w = int(file.readline()) / 1000000
            with (hwmon_path / 'temp2_input').open('r') as file:
                self.temp2_input_c = int(file.readline()) / 1000
            with (hwmon_path / 'temp2_crit').open('r') as file:
                self.temp2_crit_c = int(file.readline()) / 1000 - 10
            # with (hwmon_path / 'freq1_input').open('r') as file:
            #     self.freq1_input_ghz = int(file.readline()) / 1000000000
            # with (hwmon_path / 'freq2_input').open('r') as file:
            #     self.freq2_input_ghz = int(file.readline()) / 1000000000
        except:
            self.power1_average_w = 0
            self.temp2_input_c = 0
            self.temp2_crit_c = 90

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


class Memory:
    def __init__(self):
        memory = psutil.virtual_memory()
        self.used_gb = memory.used / 1024 / 1024 / 1024
        swap = psutil.swap_memory()
        self.swap_gb = swap.used / 1024 / 1024 / 1024

    def __str__(self):
        return '[{:3} {:4} GB]'.format(round(self.swap_gb, 1), round(self.used_gb, 1))


class Network:
    def __init__(self, period_s: float):
        self.net_counters = psutil.net_io_counters()
        self.counters_time = time.time()

        self.ping_ms = None
        self.period_s = period_s
        self.stopping = threading.Event()
        self.ping_theead = threading.Thread(target=self._ping_loop)
        self.ping_theead.start()

        self.recv_mbps = 0
        self.send_mbps = 0

        self.wlan = None
        self.wlan_bitrate_mbitps = None

    def _ping_loop(self):
        TIMEOUT = 5

        while not self.stopping.is_set():
            try:
                self.ping_ms = round(ping3.ping('8.8.8.8', unit='ms', timeout=TIMEOUT))
            except:
                self.ping_ms = None
            time.sleep(self.period_s)

    def calculate(self):
        net_counters_prev = self.net_counters
        counters_time_prev = self.counters_time

        self.net_counters = psutil.net_io_counters()
        self.counters_time = time.time()

        time_diff = self.counters_time - counters_time_prev

        self.recv_mbps = (self.net_counters.bytes_recv - net_counters_prev.bytes_recv) / time_diff / 1024 / 1024
        self.send_mbps = (self.net_counters.bytes_sent - net_counters_prev.bytes_sent) / time_diff / 1024 / 1024

        self._calculate_wlan_bitrate()

    def _calculate_wlan_bitrate(self):
        if self._calculate_wlan_bitrate_for_iface():
            return

        for iface in netifaces.interfaces():
            self.wlan = Wlan(iface)
            if self._calculate_wlan_bitrate_for_iface():
                return
        self.wlan_bitrate_mbitps = None

    def _calculate_wlan_bitrate_for_iface(self) -> bool:
        if self.wlan:
            bitrate = self.wlan.iw_get_bitrate()
            if bitrate:
                self.wlan_bitrate_mbitps = bitrate / 1000000
                return True
        return False


    def stop(self):
        self.stopping.set()

    def __str__(self):
        return '[{} MB/s {} MB/s {:4} ms {:3} MBit]'.format(
            convert_speed(self.recv_mbps),
            convert_speed(self.send_mbps),
            self.ping_ms if self.ping_ms else '****',
            round(self.wlan_bitrate_mbitps) if self.wlan_bitrate_mbitps else '***'
        )


class Disk:
    def __init__(self):
        self.disk_counters = psutil.disk_io_counters()
        self.counters_time = time.time()

        self.read_mbps = 0
        self.write_mbps = 0
        self.temp_c = 0
        self.temp_crit_c = 65

        self.alarm = None

    def calculate(self):
        disk_counters_prev = self.disk_counters
        counters_time_prev = self.counters_time

        self.disk_counters = psutil.disk_io_counters()
        self.counters_time = time.time()

        time_diff = self.counters_time - counters_time_prev

        self.read_mbps = (self.disk_counters.read_bytes - disk_counters_prev.read_bytes) / time_diff / 1024 / 1024
        self.write_mbps = (self.disk_counters.write_bytes - disk_counters_prev.write_bytes) / time_diff / 1024 / 1024
        # disk_r_t = disk_counters.read_time - self.disk_counters.read_time
        # disk_w_t = disk_counters.write_time - self.disk_counters.write_time

        sensors_temp = psutil.sensors_temperatures()
        try:
            self.temp_c = max([t.current for t in sensors_temp['nvme']])
        except:
            self.temp_c = 0

        self.alarm = create_temp_alarm('NVME', self.temp_c, self.temp_crit_c)

    def __str__(self):
        return '[{} MB/s {} MB/s {:2} °C]'.format(
            convert_speed(self.read_mbps),
            convert_speed(self.write_mbps),
            round(self.temp_c),
        )


class Common:
    def __init__(self):
        self.date_time = datetime.datetime.now().strftime("%a %d.%m.%y %H:%M:%S")
        self.keyboard_layout = '**'
        try:
            output = subprocess.check_output('xset -q | grep -A 0 \'LED\' | cut -c59-67', shell=True)
            if b'1' in output:
                self.keyboard_layout = 'ru'
            else:
                self.keyboard_layout = 'en'
        except:
            pass

    def __str__(self):
        return '[{} {}]'.format(self.date_time, self.keyboard_layout)


class HardMonitorInfo:
    def __init__(self, network_: Network, disk: Disk, cpu: Cpu):
        self.cpu = cpu
        self.memory = Memory()
        self.gpu = Gpu()
        self.network = network_
        self.disk = disk
        self.battery = Battery()
        self.common = Common()

        self.alarms = [alarm for alarm in (self.gpu.alarm, self.disk.alarm, self.cpu.alarm) if alarm]

    def __str__(self):
        return '{} {} {} {} {} {} {}'.format(
            self.cpu,
            self.memory,
            self.gpu,
            self.network,
            self.disk,
            self.battery,
            self.common,
        )


class HardMonitor:
    def __init__(self, period_s: float):
        sensors.init()
        self.cpu = Cpu()
        self.network = Network(period_s)
        self.disk = Disk()

    def stop(self):
        self.network.stop()

    def update_counters(self):
        self.cpu.calculate()
        self.network.calculate()
        self.disk.calculate()

    def load_json(self, file: pathlib.Path) -> bool:
        try:
            with file.open('r') as output:
                dump = json.load(output)
            counters_time = dump['counters_time']

            CpuCounters = collections.namedtuple('CpuCounters', dump['cpu_counters'])
            self.cpu.cpu_counters = CpuCounters(**dump['cpu_counters'])
            self.cpu.counters_time = counters_time

            NetCounters = collections.namedtuple('NetCounters', dump['net_counters'])
            self.network.net_counters = NetCounters(**dump['net_counters'])
            self.network.counters_time = counters_time

            DiskCounters = collections.namedtuple('DiskCounters', dump['disk_counters'])
            self.disk.disk_counters = DiskCounters(**dump['disk_counters'])
            self.disk.counters_time = counters_time
        except Exception:
            return False
        return True

    def save_json(self, file: pathlib.Path) -> None:
        dump = {
            'counters_time': self.cpu.counters_time,
            'cpu_counters': self.cpu.cpu_counters._asdict(),
            'disk_counters': self.disk.disk_counters._asdict(),
            'net_counters': self.network.net_counters._asdict(),
        }
        json_dump = json.dumps(dump, sort_keys=True, indent=4)

        with file.open('w') as outfile:
            outfile.write(json_dump)

    def get_info(self) -> HardMonitorInfo:
        self.update_counters()

        info = HardMonitorInfo(self.network, self.disk, self.cpu)
        return info
