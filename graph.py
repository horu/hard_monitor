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


def create_graph():
    graph: pg.PlotItem = pg.PlotWidget()
    graph.setBackground((0, 255 if TEST else 0, 0, 255 * TRANSPARENCY))
    graph.setMaximumHeight(HEIGHT)
    graph.setMaximumWidth(SYMBOL_WEIGHT)

    x = []
    y = []
    plot: pg.PlotDataItem = graph.plot(x, y, pen=pg.mkPen(0, 0, 0, 0),
                                       fillBrush=pg.mkBrush(255, 0, 0, 255 * TRANSPARENCY),
                                       fillLevel=True,
                                       )
    graph.hideAxis('bottom')
    graph.hideAxis('left')
    graph.getViewBox().autoRange(padding=0)
    #graph.getViewBox().setXRange(0, 10)
    graph.getViewBox().setYRange(0, 0)

    return graph, plot


def create_empty_label(size_symbols: int):
    label = QLabel(' ' * size_symbols)
    label.setFont(QFont('Monospace', 10))
    label.setStyleSheet('background-color: rgba(0,0,0,{}%)'.format(int(TRANSPARENCY * 100)))
    label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
    label.setVisible(True)
    return label


class Load:
    SUM_VALUE = 2
    TIME_S = 600

    def __init__(self, period_s: float):
        limit = int(Load.TIME_S / Load.SUM_VALUE / period_s)
        self.x = np.arange(0, limit, dtype=int)
        self.y = np.zeros(limit)
        (self.graph, self.plot) = create_graph()
        self.graph_width = 0
        self.values = []

    def update_graph(self, size: int, y_min, y_max):
        if not self.graph_width:
            self.graph_width = size
            self.graph.setFixedWidth(SYMBOL_WEIGHT * self.graph_width)
            self.graph.getViewBox().setYRange(y_min, y_max * Load.SUM_VALUE, padding=0)
            self.graph.getViewBox().setXRange(self.x[0], self.x[-1], padding=0)

    def add_value(self, value):
        self.values.append(value)

        if len(self.values) >= CpuLoad.SUM_VALUE:
            self.y = np.append(self.y, sum(self.values))
            self.y = np.delete(self.y, 0)
            self.plot.setData(x=self.x, y=self.y)

            self.values = []


class CpuLoad(Load):
    def __init__(self, period_s: float):
        Load.__init__(self, period_s)

    def update(self, cpu: hard_monitor.Cpu):
        if not self.graph_width:
            self.update_graph(len(str(cpu)) - 3, 0, cpu.cpu_count)

        self.add_value(cpu.loadavg_current)


class GpuLoad(Load):
    def __init__(self, period_s: float):
        Load.__init__(self, period_s)

    def update(self, gpu: hard_monitor.Gpu):
        if not self.graph_width:
            self.update_graph(len(str(gpu)) - 2, 0, gpu.power1_cap_w)

        self.add_value(gpu.power1_average_w)


class Graph:

    def __init__(self, period_s: float):
        self.widget = create_widget()

        self.graph_layout = QHBoxLayout()
        self.graph_layout.setSpacing(0)
        self.graph_layout.setContentsMargins(0, 0, 0, 0)
        self.graph_layout.setAlignment(Qt.AlignLeft)

        self.widget.setLayout(self.graph_layout)

        self.graph_layout.addWidget(create_empty_label(1), alignment=Qt.AlignLeft)

        self.cpu_load = CpuLoad(period_s)
        self.graph_layout.addWidget(self.cpu_load.graph, alignment=Qt.AlignLeft)

        self.graph_layout.addWidget(create_empty_label(17), alignment=Qt.AlignLeft)

        self.gpu_load = GpuLoad(period_s)
        self.graph_layout.addWidget(self.gpu_load.graph, alignment=Qt.AlignLeft)

        self.graph_layout.addWidget(create_empty_label(1), stretch=1)

    def update(self, info: hard_monitor.HardMonitorInfo):
        self.cpu_load.update(info.cpu)
        self.gpu_load.update(info.gpu)
