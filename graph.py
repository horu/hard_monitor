import copy

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import *
from PyQt5.QtGui import QFont, QMouseEvent

import math

import numpy as np
import pyqtgraph as pg

import hard_monitor

FONT_SIZE = 10
TRANSPARENCY = 0.7
GRAPH_TR = 0.5

TEST = 0


def create_widget() -> QWidget:
    widget = QWidget()
    widget.setStyleSheet('background-color: rgba(0,0,0,0%)')
    return widget


def create_graph(graph_height: int) -> pg.PlotItem:
    graph: pg.PlotItem = pg.PlotWidget()
    graph.setBackground((0, 255 if TEST else 0, 0, 255 * TRANSPARENCY))
    graph.setFixedHeight(graph_height)

    graph.hideAxis('bottom')
    graph.hideAxis('left')
    graph.hideButtons()

    return graph


def create_empty_label(size_symbols: int, trans: float = TRANSPARENCY):
    label = QLabel(' ' * size_symbols)
    label.setFont(QFont('Monospace', FONT_SIZE))
    label.setStyleSheet('background-color: rgba(0,0,0,{}%)'.format(int(trans * 100)))
    label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
    label.setVisible(True)
    return label


class Plot:
    def __init__(self, impl: pg.PlotDataItem, x: np.array, values_size: int, y_min):
        self.impl = impl
        self.x = x
        self.values_size = values_size

        self.values = []
        self.y_min = y_min
        self.y = np.full(np.size(self.x), self.y_min)

    def add_value(self, value):
        self.values.append(value)

        if len(self.values) >= self.values_size:
            y_value = max(sum(self.values), self.y_min)
            self.y = np.append(self.y, y_value)
            self.y = np.delete(self.y, 0)
            self.impl.setData(x=self.x, y=self.y)

            self.values = []

    def get_y_max(self, initial):
        return self.y.max(initial=initial)

    def set_fill_level(self, fill_level):
        self.impl.setFillLevel(fill_level * self.values_size)

    def override_all_y(self, y_value):
        self.y = np.full(np.size(self.x), y_value * self.values_size)
        self.impl.setData(x=self.x, y=self.y)


class GraphConfig:
    def __init__(self, period_s: float, graph_height: int, sum_value: int = 2, total_time_s: int = 600, y_min=0.0001):
        self.period_s = period_s
        self.graph_height = graph_height
        self.sum_value = sum_value
        self.total_time_s = total_time_s
        self.y_min = y_min


class Graph:
    def __init__(self, config: GraphConfig):
        self.config = config
        self.x_limit = int(self.config.total_time_s / self.config.sum_value / self.config.period_s)
        self.x = np.arange(0, self.x_limit, dtype=int)
        self.impl = create_graph(self.config.graph_height)

        self.range_is_set = False

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
        return Plot(plot_impl, self.x, self.config.sum_value, self.config.y_min)

    def set_x_range(self):
        self.impl.getViewBox().setXRange(self.x[0], self.x[-1], padding=0)

    def set_y_range(self, y_min, y_max, force: bool = False):
        if not self.range_is_set or force:
            self.impl.getViewBox().setYRange(y_min, y_max * self.config.sum_value, padding=0)
            self.set_x_range()
            self.range_is_set = True
            return True
        return False

    def set_y_log_range(self, y_min, y_max):
        if not self.range_is_set:
            self.impl.setLogMode(x=False, y=True)
            self.impl.getViewBox().setYRange(y_min, y_max + math.log10(self.config.sum_value), padding=0)
            self.set_x_range()
            self.range_is_set = True
            return True
        return False


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

    def set_y_range(self, *args, **kwargs):
        return self.graph.set_y_range(*args, **kwargs)

    def set_y_log_range(self, *args, **kwargs):
        return self.graph.set_y_log_range(*args, **kwargs)

    def update(self, text: str):
        self.impl.setText(text)


class DefaultLabel:
    def __init__(self, *args, **kwargs):
        self.label = Label(*args, **kwargs)
        self.label.set_y_range(0, 0)

    def update(self, info):
        self.label.update(str(info))


class Cpu:
    def __init__(self, *args, **kwargs):
        self.label = Label(*args, **kwargs)
        self.plot = self.label.graph.create_plot()

    def update(self, cpu: hard_monitor.Cpu):
        self.label.update(str(cpu))
        self.label.set_y_range(0, cpu.cpu_count)
        self.plot.add_value(cpu.loadavg_current)


class Memory:
    def __init__(self, *args, **kwargs):
        self.label = Label(*args, **kwargs)
        self.cache_plot = self.label.graph.create_plot(fill=pg.mkBrush(255, 255, 0, 255 * GRAPH_TR / 3))
        self.used_plot = self.label.graph.create_plot()

    def update(self, memory: hard_monitor.Memory):
        self.label.update(str(memory))
        if self.label.set_y_range(0, memory.total_gb):
            self.cache_plot.override_all_y(memory.used_gb + memory.cached_gb + memory.buffers_gb)
            self.used_plot.override_all_y(memory.used_gb)
        self.used_plot.add_value(memory.used_gb)
        self.cache_plot.add_value(memory.used_gb + memory.cached_gb + memory.buffers_gb)


class Gpu:
    def __init__(self, *args, **kwargs):
        self.label = Label(*args, **kwargs)
        self.plot = self.label.graph.create_plot()

    def update(self, gpu: hard_monitor.Gpu):
        self.label.update(str(gpu))
        self.label.set_y_range(0, gpu.power1_cap_w)
        self.plot.add_value(gpu.power1_average_w)


class Network:
    def __init__(self, *args, **kwargs):
        self.label = Label(*args, **kwargs)

        y_min = -1  # 0.1 mbps
        y_max = 1  # 10 mbps
        self.label.set_y_log_range(y_min, y_max)
        self.recv_plot = self.label.graph.create_plot(fill_level=y_min)
        self.send_plot = self.label.graph.create_plot(
            fill=pg.mkBrush(100, 100, 255, 255 * GRAPH_TR),
            fill_level=y_min)

    def update(self, net: hard_monitor.Network):
        self.label.update(str(net))

        self.recv_plot.add_value(net.recv_mbps)
        self.send_plot.add_value(net.send_mbps)


class Disk:
    def __init__(self, *args, **kwargs):
        self.label = Label(*args, **kwargs)

        y_min = 0  # 1 mbps
        y_max = 2  # 100 mbps
        self.label.set_y_log_range(y_min, y_max)
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
        battary_dur_multiplier = 12
        config = copy.deepcopy(config)
        config.sum_value = config.sum_value * battary_dur_multiplier
        config.total_time_s = config.total_time_s * battary_dur_multiplier

        self.label = Label(config)
        self.plot = self.label.graph.create_plot()

        self.charge_full_wh = 0

    def update(self, battery: hard_monitor.Battery):
        self.label.update(str(battery))

        if self.label.set_y_range(0, battery.charge_full_wh):
            self.plot.override_all_y(battery.charge_now_wh)

        if self.charge_full_wh != battery.charge_full_wh:
            self.charge_full_wh = battery.charge_full_wh
            self.plot.set_fill_level(self.charge_full_wh)
            self.label.set_y_range(0, self.charge_full_wh, force=True)

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
        label = label_type(self.config)
        self.graph_layout.addLayout(label.label.stacked_layout)
        return label

    def update(self, info: hard_monitor.HardMonitorInfo):
        for attr, value in info.__dict__.items():
            if attr == 'alarms':
                continue

            label = getattr(self, attr)
            label.update(value)
