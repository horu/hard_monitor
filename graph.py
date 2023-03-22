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
    graph.setFixedWidth(SYMBOL_WEIGHT)

    graph.hideAxis('bottom')
    graph.hideAxis('left')
    graph.getViewBox().autoRange(padding=0)
    #graph.getViewBox().setXRange(0, 10)
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
    def __init__(self, graph: pg.PlotWidget, fill, x, sum_value):
        self.graph_impl = graph
        self.x = x
        self.sum_value = sum_value

        x = []
        y = []

        self.impl: pg.PlotDataItem = self.graph_impl.plot(
            x, y, pen=pg.mkPen(0, 0, 0, 0),
            fillBrush=fill,
            fillLevel=0,
        )

        self.values = []
        self.y = np.zeros(np.size(self.x))

    def add_value(self, value):
        self.values.append(value)

        if len(self.values) >= self.sum_value:
            self.y = np.append(self.y, sum(self.values))
            self.y = np.delete(self.y, 0)
            self.impl.setData(x=self.x, y=self.y)

            self.values = []

    def update_graph(self, y_min):
        self.impl.setFillLevel(y_min)

    def get_y_max(self, initial):
        return self.y.max(initial=initial)


class Graph:
    TIME_S = 600

    def __init__(self, period_s: float, graph_height: int, sum_value=2):
        self.sum_value = sum_value
        self.limit = int(Graph.TIME_S / self.sum_value / period_s)
        self.x = np.arange(0, self.limit, dtype=int)
        self.impl = create_graph(graph_height)
        self.graph_width = 0

    def create_plot(self, fill=pg.mkBrush(255, 0, 0, 255 * TRANSPARENCY)):
        return Plot(self.impl, fill, self.x, self.sum_value)

    def update_graph(self, width: int, y_min, y_max):
        self.graph_width = width
        self.impl.setFixedWidth(SYMBOL_WEIGHT * self.graph_width)
        self.impl.getViewBox().setYRange(y_min, y_max * self.sum_value, padding=0)
        self.impl.getViewBox().setXRange(self.x[0], self.x[-1], padding=0)


class CpuLoad(Graph):
    def __init__(self, *args, **kwargs):
        Graph.__init__(self, *args, **kwargs)
        self.plot = self.create_plot()

    def update(self, cpu: hard_monitor.Cpu):
        if not self.graph_width:
            self.update_graph(len(str(cpu)) - 3, 0, cpu.cpu_count)

        self.plot.add_value(cpu.loadavg_current)


class GpuLoad(Graph):
    def __init__(self, *args, **kwargs):
        Graph.__init__(self, *args, **kwargs)
        self.plot = self.create_plot()

    def update(self, gpu: hard_monitor.Gpu):
        if not self.graph_width:
            self.update_graph(len(str(gpu)) - 2, 0, gpu.power1_cap_w)

        self.plot.add_value(gpu.power1_average_w)


class NetLoad(Graph):
    def __init__(self, *args, **kwargs):
        Graph.__init__(self, *args, **kwargs)
        self.max_mbps = 5
        self.recv_plot = self.create_plot()
        self.send_plot = self.create_plot(fill=pg.mkBrush(100, 100, 255, 255 * TRANSPARENCY))

    def update(self, net: hard_monitor.Network):
        max_mbps = max(self.recv_plot.get_y_max(0), self.send_plot.get_y_max(0), 5)
        if not self.graph_width or max_mbps != self.max_mbps:
            self.max_mbps = max_mbps
            self.update_graph(len(str(net)) - 3, 0, self.max_mbps)

        self.recv_plot.add_value(net.recv_mbps)
        self.send_plot.add_value(net.send_mbps)


class GraphList:

    def __init__(self, period_s: float, graph_height: int):
        self.widget = create_widget()

        self.graph_layout = QHBoxLayout()
        self.graph_layout.setSpacing(0)
        self.graph_layout.setContentsMargins(0, 0, 0, 0)
        self.graph_layout.setAlignment(Qt.AlignLeft)

        self.widget.setLayout(self.graph_layout)

        self.graph_layout.addWidget(create_empty_label(1), alignment=Qt.AlignLeft)

        self.cpu_graph = CpuLoad(period_s, graph_height)
        self.graph_layout.addWidget(self.cpu_graph.impl, alignment=Qt.AlignLeft)

        self.graph_layout.addWidget(create_empty_label(17), alignment=Qt.AlignLeft)

        self.gpu_graph = GpuLoad(period_s, graph_height)
        self.graph_layout.addWidget(self.gpu_graph.impl, alignment=Qt.AlignLeft)

        self.graph_layout.addWidget(create_empty_label(3), alignment=Qt.AlignLeft)

        self.network_graph = NetLoad(period_s, graph_height)
        self.graph_layout.addWidget(self.network_graph.impl, alignment=Qt.AlignLeft)

        self.graph_layout.addWidget(create_empty_label(1), stretch=1)

    def update(self, info: hard_monitor.HardMonitorInfo):
        self.cpu_graph.update(info.cpu)
        self.gpu_graph.update(info.gpu)
        self.network_graph.update(info.network)
