from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import *
from PyQt5.QtGui import QFont, QMouseEvent

import numpy as np
import pyqtgraph as pg

import hard_monitor

TRANSPARENCY = 0.7
HEIGHT = 17
SYMBOL_WEIGHT = 8

TEST = 0


def create_widget() -> QWidget:
    widget = QWidget()
    widget.setStyleSheet('background-color: rgba(0,0,0,0%)')
    return widget


def create_graph(graph_height: int) -> pg.PlotWidget:
    graph: pg.PlotItem = pg.PlotWidget()
    graph.setBackground((0, 255 if TEST else 0, 0, 255 * TRANSPARENCY))
    graph.setFixedHeight(graph_height)
    #graph.setFixedWidth(SYMBOL_WEIGHT)

    graph.hideAxis('bottom')
    graph.hideAxis('left')
    graph.getViewBox().autoRange(padding=0)
    graph.getViewBox().setYRange(0, 0)

    return graph


def create_empty_label(size_symbols: int):
    label = QLabel(' ' * size_symbols)
    label.setFont(QFont('Monospace', 10))
    label.setStyleSheet('background-color: rgba(0,0,0,{}%)'.format(int(TRANSPARENCY * 100)))
    label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
    label.setVisible(True)
    return label


class Plot:
    def __init__(self, impl: pg.PlotDataItem, x: np.array, values_size: int):
        self.impl = impl
        self.x = x
        self.values_size = values_size

        self.values = []
        self.y = np.zeros(np.size(self.x))

    def add_value(self, value):
        self.values.append(value)

        if len(self.values) >= self.values_size:
            self.y = np.append(self.y, sum(self.values))
            self.y = np.delete(self.y, 0)
            self.impl.setData(x=self.x, y=self.y)

            self.values = []

    def get_y_max(self, initial):
        return self.y.max(initial=initial)


class Graph:
    TIME_S = 600

    def __init__(self, period_s: float, graph_height: int, sum_value=2):
        self.sum_value = sum_value
        self.x_limit = int(Graph.TIME_S / self.sum_value / period_s)
        self.x = np.arange(0, self.x_limit, dtype=int)
        self.impl = create_graph(graph_height)

    def create_plot(self, fill=pg.mkBrush(255, 0, 0, 255 * TRANSPARENCY), fill_level=0):
        x = []
        y = []

        plot_impl: pg.PlotDataItem = self.impl.plot(
            x, y, pen=pg.mkPen(0, 0, 0, 0),
            fillBrush=fill,
            fillLevel=fill_level,
        )
        return Plot(plot_impl, self.x, self.sum_value)

    def set_x_range(self):
        self.impl.getViewBox().setXRange(self.x[0], self.x[-1], padding=0)


class Label:
    def __init__(self, *args, **kwargs):
        self.impl = QLabel("")
        self.impl.setFont(QFont('Monospace', 10))
        self.impl.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.impl.setStyleSheet('background-color: rgba(0,0,0,0%); color: lightgreen')
        self.impl.setVisible(True)

        self.graph = Graph(*args, **kwargs)

        self.stacked_layout = QStackedLayout()
        self.stacked_layout.setStackingMode(QStackedLayout.StackingMode.StackAll)

        self.graph_layout = QHBoxLayout()
        self.graph_layout.setSpacing(0)
        self.graph_layout.setContentsMargins(0, 0, 0, 0)
        self.graph_layout.setAlignment(Qt.AlignLeft)

        self.graph_layout.addWidget(create_empty_label(1), alignment=Qt.AlignLeft)
        self.graph_layout.addWidget(self.graph.impl)
        self.graph_layout.addWidget(create_empty_label(1), alignment=Qt.AlignRight)

        self.graph_widget = create_widget()
        self.graph_widget.setLayout(self.graph_layout)

        self.stacked_layout.addWidget(self.graph_widget)
        self.stacked_layout.addWidget(self.impl)

        self.range_is_set = False

    def set_y_range(self, y_min, y_max):
        if not self.range_is_set:
            self.graph.impl.getViewBox().setYRange(y_min, y_max * self.graph.sum_value, padding=0)
            self.graph.set_x_range()
            self.range_is_set = True

    def set_y_log_range(self, y_min, y_max):
        if not self.range_is_set:
            self.graph.impl.setLogMode(y=True)
            self.graph.impl.getViewBox().setYRange(y_min, y_max, padding=0)
            self.graph.set_x_range()
            self.range_is_set = True

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
        self.label.set_y_log_range(-1, 1.3)
        self.recv_plot = self.label.graph.create_plot(fill_level=-1)
        self.send_plot = self.label.graph.create_plot(fill=pg.mkBrush(100, 100, 255, 255 * TRANSPARENCY), fill_level=-1)

    def update(self, net: hard_monitor.Network):
        self.label.update(str(net))

        self.recv_plot.add_value(net.recv_mbps)
        self.send_plot.add_value(net.send_mbps)


class GraphList:

    def __init__(self, period_s: float, graph_height: int):
        self.period_s = period_s
        self.graph_height = graph_height

        self.graph_layout = QHBoxLayout()
        self.graph_layout.setSpacing(0)
        self.graph_layout.setContentsMargins(0, 0, 0, 0)
        self.graph_layout.setAlignment(Qt.AlignLeft)

        self.cpu = self._create_label(Cpu)
        self.memory = self._create_label(DefaultLabel)
        self.gpu = self._create_label(Gpu)
        self.network = self._create_label(Network)
        self.disk = self._create_label(DefaultLabel)
        self.battery = self._create_label(DefaultLabel)
        self.common = self._create_label(DefaultLabel)
        self.top_process = self._create_label(DefaultLabel)

    def _create_label(self, label_type):
        label = label_type(self.period_s, self.graph_height)
        self.graph_layout.addLayout(label.label.stacked_layout)
        return label

    def update(self, info: hard_monitor.HardMonitorInfo):
        for attr, value in info.__dict__.items():
            if attr == 'alarms':
                continue

            label = getattr(self, attr)
            label.update(value)
