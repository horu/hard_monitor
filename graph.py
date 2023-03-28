import copy

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import *
from PyQt5.QtGui import QFont, QMouseEvent

import math

import numpy as np
import pyqtgraph as pg

import common
import hard_monitor
import network

FONT_SIZE = 10
TRANSPARENCY = 0.7
GRAPH_TR = 0.5


def create_widget() -> QWidget:
    widget = QWidget()
    widget.setStyleSheet('background-color: rgba(0,0,0,0%)')
    return widget


def create_empty_label(size_symbols: int, trans: float = TRANSPARENCY):
    label = QLabel(' ' * size_symbols)
    label.setFont(QFont('Monospace', FONT_SIZE))
    label.setStyleSheet('background-color: rgba(0,0,0,{}%)'.format(int(trans * 100)))
    label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
    label.setVisible(True)
    return label


class Plot:
    def __init__(self, impl: pg.PlotDataItem, x: np.array, accum_size: int, y_min):
        self.impl = impl
        self.x = x
        self.accum_size = accum_size

        self.values = []
        self.y_min = y_min
        self.y = np.full(np.size(self.x), self.y_min)

    def add_value(self, value):
        self.values.append(value)

        if len(self.values) >= self.accum_size:
            y_value = max(sum(self.values) / self.accum_size, self.y_min)
            self.y = np.append(self.y, y_value)
            self.y = np.delete(self.y, 0)
            self.impl.setData(x=self.x, y=self.y)

            self.values = []

    def get_y_max(self, initial):
        return self.y.max(initial=initial)

    def set_fill_level(self, fill_level):
        self.impl.setFillLevel(fill_level)

    def override_all_y(self, y_value):
        self.y = np.full(np.size(self.x), y_value)
        self.impl.setData(x=self.x, y=self.y)


class GraphConfig:
    def __init__(
            self,
            period_s: float,
            graph_height: int,
            accum_size: int = 2,
            total_time_s: int = 600,
            y_min: float=0.0001,
            debug: bool = False):
        self.period_s = period_s
        self.graph_height = graph_height
        self.accum_size = accum_size
        self.total_time_s = total_time_s
        self.y_min = y_min
        self.debug = debug
        common.log.info(common.object_to_str(self))


class Graph:
    def __init__(self, config: GraphConfig):
        self.config = config
        self.x_limit = int(self.config.total_time_s / self.config.accum_size / self.config.period_s)
        self.x = np.arange(0, self.x_limit, dtype=int)
        self.impl = self._create_graph()

        # self.range_is_set = False

        self.y_range_min = None
        self.y_range_max = None

    def create_plot(self, fill=pg.mkBrush(255, 0, 0, 255 * GRAPH_TR), fill_level=0) -> Plot:
        x = []
        y = []

        plot_impl: pg.PlotDataItem = self.impl.plot(
            x=x,
            y=y,
            pen=pg.mkPen(0, 0, 0, 0),
            fillBrush=fill,
            fillLevel=fill_level,
        )
        return Plot(plot_impl, self.x, self.config.accum_size, self.config.y_min)

    # def set_x_range(self):
    #     self.impl.getViewBox().setXRange(self.x[0], self.x[-1], padding=0)
    #
    # def set_y_range(self, y_min, y_max, force: bool = False):
    #     if not self.range_is_set or force:
    #         self.impl.getViewBox().setYRange(y_min, y_max, padding=0)
    #         self.set_x_range()
    #         self.range_is_set = True
    #         return True
    #     return False
    #
    # def set_y_log_range(self, y_min, y_max):
    #     if not self.range_is_set:
    #         self.impl.setLogMode(x=False, y=True)
    #         self.impl.getViewBox().setYRange(y_min, y_max, padding=0)
    #         self.set_x_range()
    #         self.range_is_set = True
    #         return True
    #     return False

    def set_log_mode(self, *args, **kwargs):
        self.impl.setLogMode(*args, **kwargs)

    def update_y_range(self, y_min, y_max):
        if self.y_range_min != y_min or self.y_range_max != y_max:
            self.impl.getViewBox().setYRange(y_min, y_max, padding=0)
            self.impl.getViewBox().setXRange(self.x[0], self.x[-1], padding=0)
            self.y_range_min = y_min
            self.y_range_max = y_max
            return True
        return False

    def _create_graph(self) -> pg.PlotItem:
        graph: pg.PlotItem = pg.PlotWidget()
        graph.setBackground((0, 50 if self.config.debug else 0, 0, 255 * TRANSPARENCY))
        graph.setFixedHeight(self.config.graph_height)

        graph.hideAxis('bottom')
        if not self.config.debug:
            graph.hideAxis('left')
        graph.hideButtons()

        return graph


class Label:
    def __init__(self, *args, **kwargs):
        self.impl = QLabel("")
        self.impl.setFont(QFont('Monospace', FONT_SIZE))
        self.impl.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.impl.setStyleSheet('background-color: rgba(0,0,0,0%); color: lightgreen')
        self.impl.setVisible(True)

        self.graph = Graph(*args, **kwargs)

        self.stacked_layout = QStackedLayout()
        self.stacked_layout.setStackingMode(QStackedLayout.StackingMode.StackAll)

        # self.graph_layout = QHBoxLayout()
        # self.graph_layout.setSpacing(0)
        # self.graph_layout.setContentsMargins(0, 0, 0, 0)
        # self.graph_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        #
        # self.graph_layout.addWidget(create_empty_label(1), alignment=Qt.AlignLeft)
        # self.graph_layout.addWidget(self.graph.impl)
        # self.graph_layout.addWidget(create_empty_label(1), alignment=Qt.AlignRight)
        #
        # self.graph_widget = create_widget()
        # self.graph_widget.setLayout(self.graph_layout)
        #
        # self.stacked_layout.addWidget(self.graph_widget)
        self.stacked_layout.addWidget(self.graph.impl)
        self.stacked_layout.addWidget(self.impl)

    # def set_y_range(self, *args, **kwargs):
    #     return self.graph.set_y_range(*args, **kwargs)
    #
    # def set_y_log_range(self, *args, **kwargs):
    #     return self.graph.set_y_log_range(*args, **kwargs)

    def update_y_range(self, *args, **kwargs):
        return self.graph.update_y_range(*args, **kwargs)

    def set_log_mode(self, *args, **kwargs):
        return self.graph.set_log_mode(*args, **kwargs)

    def update(self, text: str):
        self.impl.setText(text)


class DefaultLabel:
    def __init__(self, *args, **kwargs):
        self.label = Label(*args, **kwargs)
        self.label.update_y_range(0, 0)

    def update(self, info):
        self.label.update(str(info))


class Cpu:
    def __init__(self, *args, **kwargs):
        self.label = Label(*args, **kwargs)
        self.plot = self.label.graph.create_plot()

    def update(self, cpu: hard_monitor.Cpu):
        self.label.update(str(cpu))
        self.label.update_y_range(0, cpu.cpu_count)
        self.plot.add_value(cpu.loadavg_current)


class Memory:
    def __init__(self, *args, **kwargs):
        self.label = Label(*args, **kwargs)
        # self.cache_plot = self.label.graph.create_plot(fill=pg.mkBrush(255, 255, 0, 255 * GRAPH_TR / 3))
        self.used_plot = self.label.graph.create_plot()

    def update(self, memory: hard_monitor.Memory):
        self.label.update(str(memory))
        if self.label.update_y_range(0, memory.total_gb):
            # self.cache_plot.override_all_y(memory.used_gb + memory.cached_gb + memory.buffers_gb)
            self.used_plot.override_all_y(memory.used_gb)
        self.used_plot.add_value(memory.used_gb)
        # self.cache_plot.add_value(memory.used_gb + memory.cached_gb + memory.buffers_gb)


class Gpu:
    def __init__(self, *args, **kwargs):
        self.label = Label(*args, **kwargs)
        self.plot = self.label.graph.create_plot()

        self.power_average_max_w = 0

    def update(self, gpu: hard_monitor.Gpu):
        self.label.update(str(gpu))

        # power1_cap_w can show invalid value
        self.power_average_max_w = max(gpu.power1_cap_w, gpu.power1_average_w, self.power_average_max_w)
        self.label.update_y_range(0, self.power_average_max_w)
        self.plot.add_value(gpu.power1_average_w)


class Network:
    def __init__(self, *args, **kwargs):
        self.label = Label(*args, **kwargs)

        y_min = -1  # 0.1 mbps
        y_max = 1  # 10 mbps
        self.label.set_log_mode(y=True)
        self.label.update_y_range(y_min, y_max)
        self.recv_plot = self.label.graph.create_plot(fill_level=y_min)
        self.send_plot = self.label.graph.create_plot(
            fill=pg.mkBrush(100, 100, 255, 255 * GRAPH_TR),
            fill_level=y_min)

    def update(self, net: network.Network):
        self.label.update(str(net))

        self.recv_plot.add_value(net.recv_mbps)
        self.send_plot.add_value(net.send_mbps)


class Disk:
    def __init__(self, *args, **kwargs):
        self.label = Label(*args, **kwargs)

        y_min = 0  # 1 mbps
        y_max = 2  # 100 mbps
        self.label.set_log_mode(y=True)
        self.label.update_y_range(y_min, y_max)
        self.write_plot = self.label.graph.create_plot(fill_level=y_min)
        self.read_plot = self.label.graph.create_plot(
            fill=pg.mkBrush(100, 100, 255, 255 * GRAPH_TR),
            fill_level=y_min)

    def update(self, disk: hard_monitor.Disk):
        self.label.update(str(disk))

        self.write_plot.add_value(disk.write_mbps)
        self.read_plot.add_value(disk.read_mbps)


class Battery:
    def __init__(self, config: GraphConfig):
        battery_dur_multiplier = 12
        config.accum_size = config.accum_size * battery_dur_multiplier
        config.total_time_s = config.total_time_s * battery_dur_multiplier

        self.label = Label(config)
        self.plot = self.label.graph.create_plot()

        self.first_update = True

    def update(self, battery: hard_monitor.Battery):
        self.label.update(str(battery))

        if self.label.update_y_range(0, battery.charge_full_wh):
            self.plot.set_fill_level(battery.charge_full_wh)

        if self.first_update:
            self.plot.override_all_y(battery.charge_now_wh)
            self.first_update = False

        self.plot.add_value(battery.charge_now_wh)


class GraphList:

    def __init__(self, config: GraphConfig):
        self.config = config

        self.graph_layout = QHBoxLayout()
        self.graph_layout.setSpacing(0)
        self.graph_layout.setContentsMargins(0, 0, 0, 0)
        self.graph_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        self.cpu = self._create_label(Cpu, first=True)
        self.memory = self._create_label(Memory)
        self.gpu = self._create_label(Gpu)
        self.network = self._create_label(Network)
        self.disk = self._create_label(Disk)
        self.battery = self._create_label(Battery)
        self.common = self._create_label(DefaultLabel)
        self.top_process = self._create_label(DefaultLabel)

    def _create_label(self, label_type, first=False):
        if not first:
            empty_label = create_empty_label(1, trans=0)
            empty_label.setFixedHeight(self.config.graph_height)
            self.graph_layout.addWidget(empty_label, alignment=Qt.AlignLeft | Qt.AlignTop)
        label = label_type(copy.deepcopy(self.config))
        self.graph_layout.addLayout(label.label.stacked_layout)
        return label

    def update(self, info: hard_monitor.HardMonitorInfo):
        for attr, value in info.__dict__.items():
            if attr == 'alarms':
                continue

            label = getattr(self, attr)
            label.update(value)
