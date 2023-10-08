import fcntl
import struct
import socket
import array
import bluetooth_battery
import re
import ping3
import threading
import time
import psutil
import typing
import netifaces
import subprocess
import pulsectl
import pulsectl.lookup
import tailer

import common
import systemd.journal


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


class _Bluetooth:
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


class Bluetooth:
    def __init__(self, period_s: float, force_reload_bt: bool = False):
        self.connected = False
        self.bat_level = 0.0
        self.period_s = period_s

        self.stopping = threading.Event()
        self.theead = threading.Thread(target=self._loop)
        self.theead.start()

    def _loop(self):
        journal = systemd.journal.Reader()
        journal.this_boot()
        journal.seek_tail()
        journal.log_level(systemd.journal.LOG_DEBUG)
        journal.add_match('SYSLOG_IDENTIFIER=pulseaudio', 'SYSLOG_IDENTIFIER=bluetoothd')

        while not self.stopping.is_set():
            try:
                journal.wait(self.period_s)
                for line in journal:
                    if self.stopping.is_set():
                        break

                    message = line['MESSAGE']
                    id = line['SYSLOG_IDENTIFIER']

                    # prevent recursive syslog loop
                    if common.SERVICE_NAME in message:
                        continue

                    common.log.info(id, message)

                    if 'pulseaudio' in id:
                        bat_lvl_array = re.findall('Battery Level: ([0-9]+)%', message)
                        if bat_lvl_array:
                            self.bat_level = int(bat_lvl_array[0]) / 100
                            self.connected = True
                            common.log.info('bt device bat lvl', self.bat_level)
                    elif 'bluetoothd' in id:
                        if 'disconnected' in message:
                            self.connected = False
                            common.log.info('disconnected bt device')
                        elif 'ready' in message:
                            self.connected = True
                            common.log.info('connected bt device')

            except Exception as e:
                common.log.error(e)

    def is_connected(self) -> bool:
        return self.connected

    def get_bat_level(self) -> float:
        return self.bat_level

    def stop(self):
        self.stopping.set()


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
                self.ping_ms = ping3.ping('8.8.8.8', unit='ms', timeout=timeout)
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
        return '[{} MB/s {} MB/s {:4} ms {:3} MB]'.format(
            common.convert_4(self.recv_mbps),
            common.convert_4(self.send_mbps),
            round(self.ping_ms) if self.ping_ms else '****',
            round(self.wlan.bitrate_mbitps) if self.wlan.bitrate_mbitps else '***'
        )
