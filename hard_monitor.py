import logging
import os
import threading
import time
import psutil
import json
import pathlib
import typing
import collections
import sensors
import datetime
import netifaces
import subprocess

import common
import network


BAT_PATH = pathlib.Path('/sys/class/power_supply/BAT1')

CPU_TEMP_SENSOR_NAME = 'k10temp'  # DEBUG mode grep 'Sensor names'
CPU_TEMP_CRIT_C = 90

GPU_DEVICE_ID = '0x7340'  # DEBUG mode grep 'GPU device'
HWMON_PATH = pathlib.Path('/sys/class/hwmon/')

DISK_TEMP_SENSOR_NAME = 'nvme'  # DEBUG mode grep 'Sensor names'
DISK_TEMP_CRIT_C = 65

PRINT_TO_LOG_PERIOD_S = 60


def get_sensors_temperatures():
    sensors_temp = psutil.sensors_temperatures()

    common.log.debug('Sensor names: {}'.format(sensors_temp.keys()))
    return sensors_temp


class Battery:
    def __init__(self):
        try:
            with (BAT_PATH / 'voltage_now').open('r') as file:
                self.voltage_now_v = int(file.readline()) / 1000000
            with (BAT_PATH / 'voltage_min_design').open('r') as file:
                self.voltage_min_design_v = int(file.readline()) / 1000000
            with (BAT_PATH / 'charge_now').open('r') as file:
                self.charge_now_ah = int(file.readline()) / 1000000
            with (BAT_PATH / 'charge_full').open('r') as file:
                self.charge_full_ah = int(file.readline()) / 1000000
            with (BAT_PATH / 'current_now').open('r') as file:
                self.current_now_a = int(file.readline()) / 1000000
            with (BAT_PATH / 'status').open('r') as file:
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

        sensors_temp = get_sensors_temperatures()
        try:
            self.temp_c = max(t.current for t in sensors_temp[CPU_TEMP_SENSOR_NAME])
        except Exception as e:
            common.log.error(e)
            self.temp_c = 0

        self.alarm = common.create_temp_alarm('CPU', self.temp_c, CPU_TEMP_CRIT_C)

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

        self.alarm = common.create_temp_alarm('GPU', self.temp2_input_c, self.temp2_crit_c)

    def _find_hwmon(self) -> typing.Optional[pathlib.Path]:
        for hwmon in HWMON_PATH.iterdir():
            hwmon_device = hwmon / 'device' / 'device'
            if hwmon_device.exists() and hwmon_device.is_file():
                with hwmon_device.open('r') as file:
                    device_id = file.read().splitlines()[0]
                    common.log.debug('GPU device: {} {}'.format(hwmon_device, device_id))
                    if GPU_DEVICE_ID in device_id:
                        return hwmon
        raise Exception('gpu device {} not found. change id.'.format(GPU_DEVICE_ID))

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


class Disk:
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

        sensors_temp = get_sensors_temperatures()
        try:
            self.temp_c = max(t.current for t in sensors_temp[DISK_TEMP_SENSOR_NAME])
        except Exception as e:
            common.log.error(e)
            self.temp_c = 0

        self.alarm = common.create_temp_alarm('NVME', self.temp_c, DISK_TEMP_CRIT_C)

    def __str__(self):
        return '[{} MB/s {} MB/s {:2} °C]'.format(
            common.convert_speed(self.read_mbps),
            common.convert_speed(self.write_mbps),
            round(self.temp_c),
        )


class Common:
    def __init__(self, bt: network.Bluetooth):
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
            ' '.join('{}/{:10}'.format(common.convert_speed(
                    proc[1] / 100), proc[0][:10]) for proc in self.top_process_list),
            self.process_list_size,
        )


class HardMonitorInfo:
    def __init__(self, net: network.Network, disk: Disk, cpu: Cpu, bt: network.Bluetooth):
        self.cpu = cpu
        self.memory = Memory()
        self.gpu = Gpu()
        self.network = net
        self.disk = disk
        self.battery = Battery()
        self.common = Common(bt)
        self.top_process = TopProcess()

        self.alarms = [alarm for alarm in (self.gpu.alarm, self.disk.alarm, self.cpu.alarm) if alarm]

    def get_time(self) -> float:
        return self.cpu.counters_time

    def __str__(self):
        return ' '.join(str(value) for attr, value in self.__dict__.items() if attr != 'alarms')


class HardMonitor:
    def __init__(self, period_s: float, force_reload_bt: bool = False):
        sensors.init()
        self.cpu = Cpu(period_s)
        self.network = network.Network(period_s)
        self.disk = Disk()
        self.bt = network.Bluetooth(period_s, force_reload_bt)
        self.last_log_time: float = 0
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
        if info.get_time() - self.last_log_time > PRINT_TO_LOG_PERIOD_S:
            self.last_log_time = info.get_time()
            common.log.info(info)
        return info
