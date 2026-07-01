"""Main window — shell hosting the Generate + Drop-audio views (Phase 5a/5b).

A left mode rail switches a QStackedWidget between modes (Generate / Drop audio;
Groove browser lands in 5c). Both views share ONE Controller. The status bar
surfaces messages from both views so a missing soundfont / audio device / analysis
error never crashes the window.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap, QAction
from PySide6.QtWidgets import (
    QMainWindow, QMessageBox, QWidget, QHBoxLayout, QListWidget, QStackedWidget,
)

from app.controller import Controller
from . import theme
from .generate_view import GenerateView
from .drop_view import DropView

APP_NAME = "Kickflip Shuffle"


class MainWindow(QMainWindow):
    def __init__(self, controller=None, parent=None):
        super().__init__(parent)
        self._c = controller or Controller()
        self.setWindowTitle(APP_NAME)

        icon_png = theme.asset_path("art", "keyart.png")  # .icns can render blank
        if icon_png.exists():
            self.setWindowIcon(QIcon(str(icon_png)))

        central = QWidget()
        root = QHBoxLayout(central)
        self.rail = QListWidget()
        self.rail.setFixedWidth(120)
        self.rail.addItems(["Generate", "Drop audio"])
        self.rail.setCurrentRow(0)
        root.addWidget(self.rail)

        self.stack = QStackedWidget()
        self.generate_view = GenerateView(self._c)
        self.drop_view = DropView(self._c)
        self.stack.addWidget(self.generate_view)
        self.stack.addWidget(self.drop_view)
        root.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.rail.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.generate_view.status.connect(self.statusBar().showMessage)
        self.drop_view.status.connect(self.statusBar().showMessage)
        # Disable the rail while an analysis is in flight (avoid mid-analysis switch).
        self.drop_view.busy.connect(lambda on: self.rail.setDisabled(on))
        self.drop_view.specBuilt.connect(self._on_spec_built)

        about = QAction("About Kickflip Shuffle", self)
        about.triggered.connect(self._about)
        self.menuBar().addMenu("Help").addAction(about)

        self.statusBar().showMessage("Pick a profile to start.")
        self.resize(980, 600)

    # Backwards-compatible alias (older tests / callers used `.view`).
    @property
    def view(self):
        return self.generate_view

    def _on_spec_built(self):
        self.generate_view.load_current_spec()
        self.rail.setCurrentRow(0)             # switch to Generate to correct/play

    def closeEvent(self, event):
        # Child closeEvent does NOT fire inside a QStackedWidget — tear down both
        # views' worker threads here.
        self.generate_view.shutdown()
        self.drop_view.shutdown()
        super().closeEvent(event)

    def _about(self):
        box = QMessageBox(self)
        box.setWindowTitle(f"About {APP_NAME}")
        box.setText(f"{APP_NAME}\nPop-punk drum MIDI generator.")
        pix = QPixmap(str(theme.asset_path("art", "keyart.png")))
        if not pix.isNull():
            box.setIconPixmap(pix.scaledToWidth(96))
        box.exec()
