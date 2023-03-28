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
import bluetooth_battery
import re

import common


class BluetoothDevice:
    BAT_UPDATE_PERIOD_S = 3 * 3600

    def __init__(self, mac_address: str):
        self.mac_address = mac_address
        self.bat_level: float = 0.0  # 0.0-1.0
        self.bat_update_time = 0

    def update_bat_level(self):
        update_time = time.time()
        if update_time - self.bat_update_time < self.BAT_UPDATE_PERIOD_S:
            return

        common.log.info('update bat level for', self.mac_address)
        try:
            o = subprocess.check_output('bluetoothctl disconnect {}'.format(self.mac_address), shell=True, text=True)
            common.log.debug('disconnect bt device', o.splitlines())
            for i in range(1, 11):
                try:
                    b = bluetooth_battery.BatteryStateQuerier('{}'.format(self.mac_address), i)
                    result = int(b) / 100
                    self.bat_level = result
                    self.bat_update_time = update_time
                    common.log.info('bat level is', result)
                    break
                except Exception as e:
                    common.log.debug('port error', i, e)
        except Exception as e:
            common.log.error('update bt error', e)

        o = subprocess.check_output('bluetoothctl connect {}'.format(self.mac_address), shell=True, text=True)
        common.log.debug('connect bt device', o.splitlines())


class Bluetooth:
    MAX_DEVICE_SIZE = 5

    def __init__(self, period_s: float, force_reload_bt: bool = False):
        self.device_list: typing.List[BluetoothDevice] = []
        self.current_device: typing.Optional[BluetoothDevice] = None

        self.force_reload_bt = force_reload_bt
        self.period_s = period_s
        self.stopping = threading.Event()
        self.check_theead = threading.Thread(target=self._check_loop)
        self.check_theead.start()

    def is_connected(self) -> bool:
        return self.current_device is not None

    def get_bat_level(self) -> float:
        if self.current_device:
            return self.current_device.bat_level
        return 0

    def stop(self):
        self.stopping.set()

    def _get_current_mac(self):
        try:
            p = subprocess.run('bluetoothctl info | grep Device',
                               shell=True, text=True, check=False, stdout=subprocess.PIPE)
            if p.returncode == 0:
                output = p.stdout.splitlines()
                mac = re.findall('[:0-9A-F]{17}', output[0])
                return mac[0]
        except Exception as e:
            common.log.error(e)
        return None

    def _update_current_device(self):
        mac_address = self._get_current_mac()
        if mac_address:
            if self.current_device and self.current_device.mac_address == mac_address:
                return

            for device in self.device_list:
                if device.mac_address == mac_address:
                    common.log.info('found old device', device.mac_address)
                    break
            else:
                if len(self.device_list) >= Bluetooth.MAX_DEVICE_SIZE:
                    to_remove = self.device_list.pop(0)
                    common.log.info('removed device', to_remove.mac_address)

                device = BluetoothDevice(mac_address)
                common.log.info('add new device', device.mac_address)
                self.device_list.append(device)

            self.current_device = device
            common.log.info('current device', self.current_device.mac_address)
        else:
            self.current_device = None

    def _check_loop(self):
        while not self.stopping.is_set():
            try:
                prev_device = self.current_device
                self._update_current_device()
                if self.current_device and prev_device != self.current_device:
                    common.log.info('connected device', self.current_device.mac_address)
                    if self.force_reload_bt:
                        self.current_device.update_bat_level()
                elif prev_device != self.current_device:
                    common.log.info('disconnected device', prev_device.mac_address)
            except Exception as e:
                common.log.error(e)
            time.sleep(self.period_s)


class WlanDevice:
    SIOCGIWRATE = 0x8B21  # get default bit rate (bps)
    IFNAMSIZE = 16

    def __init__(self, iface: str):
        self.iface = iface
        self.sockfd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.fmt = "ibbH"

    def iw_get_bitrate(self) -> typing.Optional[int]:
        try:
            status, result = self._iw_get_ext(self.iface, self.SIOCGIWRATE)
            return self._parse_data(self.fmt, result)[0]
        except Exception as e:
            common.log.debug('iface error', self.iface, e)
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
        buff = self.IFNAMSIZE-len(ifname)
        ifreq = array.array('b', ifname.encode('utf-8') + b'\0'*buff)
        # put some additional data behind the interface name
        if data is not None:
            ifreq.extend(data)
        else:
            # extend to 32 bytes for ioctl payload
            ifreq.extend(b'\0'*16)

        result = fcntl.ioctl(self.sockfd.fileno(), request, ifreq)
        return result, ifreq[self.IFNAMSIZE:]

    def __str__(self):
        return self.iface


class Wlan:
    def __init__(self):
        self.device = None
        self.bitrate_mbitps = None

    def calculate_wlan_bitrate(self):
        if self._calculate_wlan_bitrate_for_iface():
            return

        for iface in netifaces.interfaces():
            self.device = WlanDevice(iface)
            if self._calculate_wlan_bitrate_for_iface():
                common.log.info('found wlan divece', self.device)
                return
        self.bitrate_mbitps = None

    def _calculate_wlan_bitrate_for_iface(self) -> bool:
        if self.device:
            bitrate = self.device.iw_get_bitrate()
            if bitrate:
                self.bitrate_mbitps = bitrate / 1000000
                return True
        return False


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


class Battery:
    BAT_PATH = pathlib.Path('/sys/class/power_supply/BAT1')

    def __init__(self):
        try:
            with (Battery.BAT_PATH / 'voltage_now').open('r') as file:
                self.voltage_now_v = int(file.readline()) / 1000000
            with (Battery.BAT_PATH / 'voltage_min_design').open('r') as file:
                self.voltage_min_design_v = int(file.readline()) / 1000000
            with (Battery.BAT_PATH / 'charge_now').open('r') as file:
                self.charge_now_ah = int(file.readline()) / 1000000
            with (Battery.BAT_PATH / 'charge_full').open('r') as file:
                self.charge_full_ah = int(file.readline()) / 1000000
            with (Battery.BAT_PATH / 'current_now').open('r') as file:
                self.current_now_a = int(file.readline()) / 1000000
            with (Battery.BAT_PATH / 'status').open('r') as file:
                self.charge_status = False if 'Discharging' in file.readline() else True
        except Exception as e:
            common.log.error(e)
            self.voltage_now_v = 0
            self.voltage_min_design_v = 0
            self.charge_now_ah = 0
            self.current_now_a = 0
            self.charge_status = False

        self.power_w = self.voltage_now_v * self.current_now_a
        self.charge_now_wh = self.charge_now_ah * self.voltage_min_design_v
        self.charge_full_wh = self.charge_full_ah * self.voltage_min_design_v

    def __str__(self):

        return '[{}{:2} W {:4} Wh]'.format(
            '+' if self.charge_status else ' ',
            round(self.power_w),
            round(self.charge_now_wh, 1),
        )


class Cpu:
    TEMP_SENSOR_NAME = 'k10temp'
    TEMP_CRIT_C = 90

    def __init__(self, period_s: float):
        self.cpu_count = psutil.cpu_count()

        self.cpu_counters = psutil.cpu_times()
        self.counters_time = time.time()

        self.loadavg_current = 0
        self.loadavg_1m = 0
        self.temp_c = 0

        self.alarm = None

        # take readings for graq list inside another thread to prevent any affects to cpy freq
        self.period_s = period_s
        self.stopping = threading.Event()
        self.freq_list_theead = threading.Thread(target=self._take_freq_list)
        self.freq_list_theead.start()
        self.freq_list_ghz = []

    def stop(self):
        self.stopping.set()

    def calculate(self):
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
            self.temp_c = max(t.current for t in sensors_temp[Cpu.TEMP_SENSOR_NAME])
        except Exception as e:
            common.log.error(e)
            self.temp_c = 0

        self.alarm = create_temp_alarm('CPU', self.temp_c, Cpu.TEMP_CRIT_C)

    def _take_freq_list(self) -> None:
        count = 5
        freq_list_size = 4

        while not self.stopping.is_set():
            try:
                # sleep before psutil.cpu_freq call
                freq_list_min = [9999.9] * freq_list_size
                for _ in range(0, count):
                    time.sleep(self.period_s / count / 2)
                    freqs = psutil.cpu_freq(percpu=True)
                    freqs_cur = sorted(freq.current for freq in freqs)
                    el_size = len(freqs_cur) / freq_list_size

                    freq_list = []
                    el_sum = 0
                    for i, f in enumerate(freqs_cur):
                        el_sum += f
                        if i % el_size == el_size - 1:
                            freq_list.append(el_sum / el_size)
                            el_sum = 0

                    for i, f in enumerate(freq_list):
                        freq_list_min[i] = min(f, freq_list_min[i])

                self.freq_list_ghz = [f / 1000 for f in freq_list_min]
            except Exception as e:
                common.log.error(e)

    def __str__(self):
        return '[{:4} {:4} ({}) Ghz {:2} °C]'.format(
            round(self.loadavg_current, 1),
            round(self.loadavg_1m, 1),
            ' '.join('{:03}'.format(round(f, 1)) for f in self.freq_list_ghz),
            round(self.temp_c),
        )


class Gpu:
    GPU_DEVICE_ID = '0x7340'
    HWMON_PATH = pathlib.Path('/sys/class/hwmon/')

    def __init__(self):
        try:
            hwmon_path = self._find_hwmon()
            with (hwmon_path / 'power1_average').open('r') as file:
                self.power1_average_w = int(file.readline()) / 1000000
            with (hwmon_path / 'power1_cap').open('r') as file:
                self.power1_cap_w = int(file.readline()) / 1000000
            with (hwmon_path / 'temp2_input').open('r') as file:
                self.temp2_input_c = int(file.readline()) / 1000
            with (hwmon_path / 'temp2_crit').open('r') as file:
                self.temp2_crit_c = int(file.readline()) / 1000 - 10
            # with (hwmon_path / 'freq1_input').open('r') as file:
            #     self.freq1_input_ghz = int(file.readline()) / 1000000000
            # with (hwmon_path / 'freq2_input').open('r') as file:
            #     self.freq2_input_ghz = int(file.readline()) / 1000000000
        except Exception as e:
            common.log.error(e)
            self.power1_average_w = 0
            self.power1_cap_w = 0
            self.temp2_input_c = 0
            self.temp2_crit_c = 90

        self.alarm = create_temp_alarm('GPU', self.temp2_input_c, self.temp2_crit_c)

    def _find_hwmon(self) -> typing.Optional[pathlib.Path]:
        for hwmon in Gpu.HWMON_PATH.iterdir():
            hwmon_device = hwmon / 'device' / 'device'
            if hwmon_device.exists() and hwmon_device.is_file():
                with hwmon_device.open('r') as file:
                    if Gpu.GPU_DEVICE_ID in file.readline():
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
        self.cached_gb = memory.cached / 1024 / 1024 / 1024
        self.buffers_gb = memory.buffers / 1024 / 1024 / 1024
        self.total_gb = memory.total / 1024 / 1024 / 1024
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

        self.wlan = Wlan()

    def _ping_loop(self):
        timeout = 5

        while not self.stopping.is_set():
            try:
                self.ping_ms = round(ping3.ping('8.8.8.8', unit='ms', timeout=timeout))
            except Exception as e:
                common.log.debug('ping error', e)
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

        self.wlan.calculate_wlan_bitrate()

    def stop(self):
        self.stopping.set()

    def __str__(self):
        return '[{} MB/s {} MB/s {:4} ms {:3} MBit]'.format(
            convert_speed(self.recv_mbps),
            convert_speed(self.send_mbps),
            self.ping_ms if self.ping_ms else '****',
            round(self.wlan.bitrate_mbitps) if self.wlan.bitrate_mbitps else '***'
        )


class Disk:
    TEMP_SENSOR_NAME = 'nvme'
    TEMP_CRIT_C = 65

    def __init__(self):
        self.disk_counters = psutil.disk_io_counters()
        self.counters_time = time.time()

        self.read_mbps = 0
        self.write_mbps = 0
        self.temp_c = 0

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
            self.temp_c = max(t.current for t in sensors_temp[Disk.TEMP_SENSOR_NAME])
        except Exception as e:
            common.log.error(e)
            self.temp_c = 0

        self.alarm = create_temp_alarm('NVME', self.temp_c, Disk.TEMP_CRIT_C)

    def __str__(self):
        return '[{} MB/s {} MB/s {:2} °C]'.format(
            convert_speed(self.read_mbps),
            convert_speed(self.write_mbps),
            round(self.temp_c),
        )


class Common:
    def __init__(self, bt: Bluetooth):
        self.date_time = datetime.datetime.now()
        self.hour_utc = datetime.datetime.now(datetime.timezone.utc).hour
        self.hour_msc = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3))).hour

        self.keyboard_layout = '**'
        try:
            output = subprocess.check_output('xset -q | grep -A 0 \'LED\' | cut -c59-67', shell=True)
            if b'1' in output:
                self.keyboard_layout = 'RU'
            else:
                self.keyboard_layout = 'EN'
        except Exception as e:
            common.log.error(e)

        self.vpn_connected = any('ppp' in iface for iface in netifaces.interfaces())
        self.bt = bt

    def __str__(self):
        bt_status = 'B/{:03}'.format(round(self.bt.get_bat_level(), 1))
        return '[{} {:02}/{:02}/{} {} {} {}]'.format(
            self.date_time.strftime("%a %d.%m.%y"),
            self.hour_utc,
            self.hour_msc,
            self.date_time.strftime("%H:%M:%S"),
            self.keyboard_layout,
            'V' if self.vpn_connected else ' ',
            bt_status if self.bt.is_connected() else ' ' * len(bt_status),
        )


class TopProcess:
    def __init__(self):
        self.process_list_size = 0

        proc_list = [proc.info for proc in psutil.process_iter(['name', 'cpu_percent']) if proc.info['cpu_percent'] > 0]
        self.process_list_size = len(proc_list)
        proc_dict = {}
        for proc in proc_list:
            proc_dict.setdefault(proc['name'], 0)
            proc_dict[proc['name']] += proc['cpu_percent']

        top_size = 2
        self.top_process_list = sorted(proc_dict.items(), key=lambda p: p[1], reverse=True)[:top_size]
        while len(self.top_process_list) < top_size:
            self.top_process_list.append(('', 0))

    def __str__(self):
        return '[{} {:3}]'.format(
            ' '.join('{}/{:10}'.format(convert_speed(proc[1] / 100), proc[0][:10]) for proc in self.top_process_list),
            self.process_list_size,
        )


class HardMonitorInfo:
    def __init__(self, network: Network, disk: Disk, cpu: Cpu, bt: Bluetooth):
        self.cpu = cpu
        self.memory = Memory()
        self.gpu = Gpu()
        self.network = network
        self.disk = disk
        self.battery = Battery()
        self.common = Common(bt)
        self.top_process = TopProcess()

        self.alarms = [alarm for alarm in (self.gpu.alarm, self.disk.alarm, self.cpu.alarm) if alarm]

    def __str__(self):
        return ' '.join(str(value) for attr, value in self.__dict__.items() if attr != 'alarms')


class HardMonitor:
    def __init__(self, period_s: float, force_reload_bt: bool = False):
        sensors.init()
        self.cpu = Cpu(period_s)
        self.network = Network(period_s)
        self.disk = Disk()
        self.bt = Bluetooth(period_s, force_reload_bt)
        common.log.info(period_s, force_reload_bt)

    def stop(self):
        self.cpu.stop()
        self.network.stop()
        self.bt.stop()

    def update_counters(self):
        self.cpu.calculate()
        self.network.calculate()
        self.disk.calculate()

    def load_json(self, file: pathlib.Path) -> bool:
        common.log.info('read json', file)
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
        except Exception as e:
            common.log.error('read json error', e)
            return False
        common.log.info('read json success', file)
        return True

    def save_json(self, file: pathlib.Path) -> None:
        common.log.info('write json', file)
        dump = {
            'counters_time': self.cpu.counters_time,
            'cpu_counters': self.cpu.cpu_counters._asdict(),
            'disk_counters': self.disk.disk_counters._asdict(),
            'net_counters': self.network.net_counters._asdict(),
        }
        json_dump = json.dumps(dump, sort_keys=True, indent=4)

        with file.open('w') as outfile:
            try:
                outfile.write(json_dump)
            except Exception as e:
                common.log.error('write json error', e)
                return
        common.log.info('write json success', file)

    def get_info(self) -> HardMonitorInfo:
        self.update_counters()

        info = HardMonitorInfo(self.network, self.disk, self.cpu, self.bt)
        return info
