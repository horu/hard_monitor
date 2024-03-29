import os
import signal
import typing

from PyQt5.QtCore import QTimer, QDateTime, QPoint, QRect
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import *
from PyQt5.QtGui import QFont, QMouseEvent

import sys
import hard_monitor
import graph
import common


class Window(QMainWindow):
    """Main Window."""
    def __init__(self, config: graph.GraphConfig):
        """Initializer."""
        super().__init__(None)
        self.setWindowTitle("Hw monitor")

        self.setWindowOpacity(1)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowFlags(Qt.FramelessWindowHint |
                            Qt.WindowStaysOnTopHint |
                            Qt.BypassWindowManagerHint |
                            Qt.X11BypassWindowManagerHint |
                            Qt.WindowTransparentForInput |
                            Qt.WindowDoesNotAcceptFocus |
                            Qt.BypassGraphicsProxyWidget)

        self.central_widget = graph.create_widget()
        self.setCentralWidget(self.central_widget)

        # position for move window
        self.drag_position = QPoint()

        self.main_layout = QFormLayout()
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setHorizontalSpacing(0)
        self.main_layout.setVerticalSpacing(0)
        self.central_widget.setLayout(self.main_layout)

        self.graph_list = graph.GraphList(config)
        self.main_layout.addRow(self.graph_list.graph_layout)

        self.notify_label = QLabel("")
        self.notify_label.setFont(QFont('Monospace', 40))
        self.notify_label.setAlignment(Qt.AlignCenter)
        self.notify_label.setStyleSheet('background-color: rgba(0,0,0,0%); color: rgb(255,0,0)')
        self.notify_label.setVisible(False)
        self.main_layout.addRow(self.notify_label)

    def notify(self, text: typing.Optional[str]):
        if not text:
            text = ''
        else:
            common.log.info('alarm', text)
        self.notify_label.setVisible(True if text else False)
        self.notify_label.setText(text)


class Backend:
    def __init__(self, window: Window, period_s: float, height: typing.Optional[int]):
        self.window = window
        self.height = height
        self.reset_geometry()

        self.hard_monitor = hard_monitor.HardMonitor(period_s, force_reload_bt=True)
        self.hard_monitor.update_counters()

        self.print_timer = QTimer()
        self.print_timer.timeout.connect(self.print)
        self.print_timer.start(round(period_s * 1000))

        self.test_notify_timer = QTimer()
        self.test_notify_timer.timeout.connect(self.test_notify)
        self.test_notify_timer.start(4500)
        self.test_notify_temp_crit_c = hard_monitor.CPU_TEMP_CRIT_C
        hard_monitor.CPU_TEMP_CRIT_C = 30

        #self.window.centralWidget().mousePressEvent = self.on_press_event
        #self.window.centralWidget().mouseDoubleClickEvent = self.on_double_click_event
        #self.window.centralWidget().mouseMoveEvent = self.on_move_event

    def on_double_click_event(self, event: QMouseEvent):
        button = event.button()
        if button == Qt.MouseButton.LeftButton:
            self.window.showMinimized()
        event.accept()

    def on_press_event(self, event: QMouseEvent):
        self.window.drag_position = event.globalPos()

        button = event.button()
        #if button == Qt.MouseButton.RightButton:
            #self.printer.change_print_mode()
        #elif button == Qt.MouseButton.MidButton:
            #self.parser.reset_statistic()
        event.accept()

    def on_move_event(self, event: QMouseEvent):
        if event.buttons() == Qt.LeftButton:
            self.window.move(self.window.pos() + event.globalPos() - self.window.drag_position)
            self.window.drag_position = event.globalPos()
            event.accept()

    def test_notify(self):
        hard_monitor.CPU_TEMP_CRIT_C = self.test_notify_temp_crit_c
        self.test_notify_timer.stop()

    def print(self):
        self.reset_geometry()
        info = self.hard_monitor.get_info()
        self.window.graph_list.update(info)

        if info.alarms:
            self.window.notify(' '.join(info.alarms))
        else:
            self.window.notify(None)

    def reset_geometry(self):
        # 1 - show on upper monitor
        # 0 - show on bottom monitor
        monitor = QDesktopWidget().screenGeometry(1)
        if self.height is None:
            self.window.move(monitor.left(), monitor.top())
        else:
            self.window.move(monitor.left(), self.height)
        self.window.resize(1, 1)


if __name__ == "__main__":
    args = common.init()

    app = QApplication(sys.argv)

    default_graph_config = graph.GraphConfig(
        period_s=args.period,
        graph_height=args.graph_height,
        total_time_s=args.graph_time,
        debug=args.graph_debug,
    )

    win = Window(default_graph_config)
    win.show()

    back = Backend(win, args.period, args.height)

    sys.exit(app.exec_())