import argparse
import logging
import os
import pathlib
import signal
import time
import typing

from PyQt5.QtCore import QTimer, QDateTime, QPoint, QRect
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import *
from PyQt5.QtGui import QFont, QMouseEvent

import sys
import hard_monitor

TRANSPARENCY = 0.5


def create_form() -> QFormLayout:
    form = QFormLayout()
    form.setHorizontalSpacing(0)
    form.setVerticalSpacing(0)
    return form


def create_widget() -> QWidget:
    widget = QWidget()
    widget.setStyleSheet('padding :0px; background-color: rgba(0,0,0,{}%); color: white'
                         .format(int(TRANSPARENCY * 100)))
    return widget


class Window(QMainWindow):
    """Main Window."""
    def __init__(self, parent=None):
        """Initializer."""
        super().__init__(parent)
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

        self.central_widget = create_widget()
        self.setCentralWidget(self.central_widget)

        # position for move window
        self.drag_position = QPoint()

        self.main_form = QStackedLayout()
        self.main_form.setStackingMode(QStackedLayout.StackingMode.StackAll)
        self.central_widget.setLayout(self.main_form)

        self.main_label = QLabel("")
        self.main_label.setFont(QFont('Monospace', 10))
        self.main_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.main_label.setStyleSheet('padding :0px; background-color: rgba(0,0,0,0%); color: lightgreen')
        self.main_label.setVisible(True)
        self.main_form.addWidget(self.main_label)

        self.notify_label = QLabel("")
        self.notify_label.setFont(QFont('Monospace', 10))
        self.notify_label.setAlignment(Qt.AlignCenter)
        self.notify_label.setStyleSheet('background-color: rgba(0,0,0,0%); color: rgb(255,0,0)')
        self.notify_label.setVisible(False)
        self.main_form.addWidget(self.notify_label)

    def set_main_label_text(self, text: str) -> None:
        self.main_label.setText(text)
        #logging.debug(self.central_widget.geometry().size().height())
        #logging.debug(self.main_form.totalMinimumSize().height())
        #logging.debug(self.main_form.sizeConstraint().)

    def notify(self, text: typing.Optional[str]):
        if text:
            self.notify_label.setFont(QFont('Monospace', 36))
        else:
            text = ''
            self.notify_label.setFont(QFont('Monospace', 10))
        self.notify_label.setVisible(True if text else False)
        self.notify_label.setText(text)


class Backend:
    def __init__(self, window: Window, period_s: float):
        self.window = window
        self.reset_geometry()

        self.hard_monitor = hard_monitor.HardMonitor(period_s)
        self.hard_monitor.update_counters()

        self.print_timer = QTimer()
        self.print_timer.timeout.connect(self.print)
        self.print_timer.start(round(period_s * 1000))

        self.test_notify_timer = QTimer()
        self.test_notify_timer.timeout.connect(self.test_notify)
        self.test_notify_timer.start(4500)
        self.test_notify_temp_crit_c = hard_monitor.Cpu.TEMP_CRIT_C
        hard_monitor.Cpu.TEMP_CRIT_C = 30

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
        hard_monitor.Cpu.TEMP_CRIT_C = self.test_notify_temp_crit_c
        self.test_notify_timer.stop()

    def print(self):
        info = self.hard_monitor.get_info()
        self.window.set_main_label_text(str(info))

        if info.alarms:
            self.window.notify(' '.join(info.alarms))
        else:
            self.window.notify(None)
        self.reset_geometry()

    def reset_geometry(self):
        monitor = QDesktopWidget().screenGeometry(0)
        self.window.move(monitor.left(), monitor.top())
        self.window.resize(1, 1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog='hard_monitor', description='Show hardware monitor')
    parser.add_argument('-p', '--period', type=float, default=2.0, help='Timeout for collecting counters.')
    parser.add_argument('-f', '--pidfile', type=pathlib.Path, default='/tmp/hard_monitor_ui_default',
                        help='File to save pid.')
    parser.add_argument('-l', '--log', type=str, default='ERROR', help='Log level.')
    args = parser.parse_args()

    if args.pidfile:
        try:
            with args.pidfile.open('r') as file:
                pid = int(file.readline())
                logging.info('pid: {}'.format(pid))
                os.kill(pid, signal.SIGKILL)
        except:
            pass

        with args.pidfile.open('w') as file:
            file.write(str(os.getpid()))

    logging.basicConfig(format='%(asctime)s: %(message)s', level=logging.getLevelName(args.log))

    app = QApplication(sys.argv)
    win = Window()
    win.show()

    back = Backend(win, args.period)

    sys.exit(app.exec_())