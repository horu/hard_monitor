import logging
import os

from PyQt5.QtCore import QTimer, QDateTime, QPoint
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import *
from PyQt5.QtGui import QFont, QMouseEvent

import sys

import hard_monitor

LOG_LEVEL = os.environ.get('LOG_LEVEL', default='DEBUG')
TRANSPARENCY = 0.5
DAMAGE_PRINT_LIMIT = 1000


def create_form() -> QFormLayout:
    form = QFormLayout()
    form.setHorizontalSpacing(0)
    form.setVerticalSpacing(0)
    form.setRowWrapPolicy(QFormLayout.DontWrapRows)
    return form


def convert_long_int(value: int) -> str:
    if abs(value) > DAMAGE_PRINT_LIMIT:
        return '{:.1f}'.format(value / DAMAGE_PRINT_LIMIT)
    return str(value)


def create_label(value: str = '', color: str = 'white') -> QLabel:
    label = QLabel(value)
    label.setFont(QFont('Monospace', 10))
    label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
    label.setStyleSheet('background-color: rgba(0,0,0,0%); color: {}'.format(color))
    return label


class Window(QMainWindow):
    """Main Window."""
    def __init__(self, parent=None):
        """Initializer."""
        super().__init__(parent)
        self.setWindowTitle("Hw monitor")
        self.move(600, 0)
        self.setWindowOpacity(1)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)

        self.central_widget = QWidget()
        self.central_widget.setStyleSheet('background-color: rgba(0,0,0,{}%); color: white'.format(int(TRANSPARENCY * 100)))

        self.setCentralWidget(self.central_widget)

        # position for move window
        self.drag_position = QPoint()


class UserInterface:
    def __init__(self, widget: QWidget):
        self.main_form = create_form()
        widget.setLayout(self.main_form)

        self.notify_label = QLabel("")
        self.notify_label.setFont(QFont('Monospace', 32))
        self.notify_label.setAlignment(Qt.AlignCenter)
        self.notify_label.setStyleSheet('background-color: rgba(0,0,0,0%); color: red')
        self.notify_label.setVisible(False)
        self.main_form.addRow(self.notify_label)

        self.main_label = QLabel("")
        self.main_label.setFont(QFont('Monospace', 10))
        self.main_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.main_label.setStyleSheet('background-color: rgba(0,0,0,0%); color: white')
        self.main_label.setVisible(False)
        self.main_form.addRow(self.main_label)

    def set_main_label_text(self, text: str, visible: bool) -> None:
        self.main_label.setVisible(visible)
        self.main_label.setText(text)

    def notify(self, text: str, visible: bool):
        self.notify_label.setVisible(visible)
        self.notify_label.setText(text)


class Backend:
    def __init__(self, window: Window, ui: UserInterface):
        self.window = window
        self.ui = ui
        self.reset_geometry()

        self.hard_monitor = hard_monitor.HardMonitor()
        self.hard_monitor.update_counters()

        self.read_log_timer = QTimer()
        self.read_log_timer.timeout.connect(self.print)
        self.read_log_timer.start(1000)

        self.data_save_timer = QTimer()
        self.data_save_timer.timeout.connect(self.save_data)
        self.data_save_timer.start(6000)

        self.window.centralWidget().mousePressEvent = self.on_press_event
        self.window.centralWidget().mouseDoubleClickEvent = self.on_double_click_event
        self.window.centralWidget().mouseMoveEvent = self.on_move_event

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

    def save_data(self):
        #data_saver = DataSaver(DATA_FILE_PATH)
        #data_saver.save(self.parser)
        pass

    def print(self):
        text = self.hard_monitor.get_info()
        self.ui.set_main_label_text(text, True)

    def reset_geometry(self):
        self.window.resize(400, 40)


if __name__ == "__main__":
    logging.basicConfig(format='%(asctime)s: %(message)s', level=logging.getLevelName(LOG_LEVEL))

    app = QApplication(sys.argv)
    win = Window()
    win.show()

    ui = UserInterface(win.central_widget)
    back = Backend(win, ui)

    sys.exit(app.exec_())