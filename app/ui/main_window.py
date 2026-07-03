"""Main window — shell hosting the Generate + Drop-audio + Browser views.

A left mode rail switches a QStackedWidget between modes (Generate / Drop audio /
Groove browser). All views share ONE Controller. The status bar surfaces messages
from every view so a missing soundfont / audio device / analysis error never
crashes the window.
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
from .browser_view import BrowserView

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
        self.rail.addItems(["Generate", "Drop audio", "Browser"])
        self.rail.setCurrentRow(0)
        root.addWidget(self.rail)

        self.stack = QStackedWidget()
        self.generate_view = GenerateView(self._c)
        self.drop_view = DropView(self._c)
        self.browser_view = BrowserView(self._c)
        self.stack.addWidget(self.generate_view)
        self.stack.addWidget(self.drop_view)
        self.stack.addWidget(self.browser_view)
        root.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.rail.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.rail.currentRowChanged.connect(self._on_mode_changed)
        self.generate_view.status.connect(self.statusBar().showMessage)
        self.drop_view.status.connect(self.statusBar().showMessage)
        self.browser_view.status.connect(self.statusBar().showMessage)
        # Disable the rail while an analysis is in flight (avoid mid-analysis switch).
        self.drop_view.busy.connect(lambda on: self.rail.setDisabled(on))
        self.drop_view.specBuilt.connect(self._on_spec_built)
        # Groove browser <-> arrangement editor wiring. Apply routes into the
        # Generate view's current section, then switches back to show the result;
        # the browser's apply buttons track whether a section is currently live.
        self.browser_view.useGroove.connect(self._on_use_groove)
        self.browser_view.addFill.connect(self._on_add_fill)
        self.generate_view.sectionSelectionChanged.connect(
            self.browser_view.set_apply_enabled)

        about = QAction("About Kickflip Shuffle", self)
        about.triggered.connect(self._about)
        self.menuBar().addMenu("Help").addAction(about)

        self.statusBar().showMessage("Pick a profile to start.")
        self.resize(980, 600)

    # Backwards-compatible alias (older tests / callers used `.view`).
    @property
    def view(self):
        return self.generate_view

    def _on_mode_changed(self, index):
        # Entering the Browser: sync apply-button state to whatever section is
        # currently live in the arrangement editor (sectionSelectionChanged only
        # fires on change, so a pre-existing selection wouldn't reach the browser).
        if self.stack.widget(index) is self.browser_view:
            self.browser_view.set_apply_enabled(
                self.generate_view.current_section_index())

    def _on_spec_built(self):
        self.generate_view.load_current_spec()
        self.rail.setCurrentRow(0)             # switch to Generate to correct/play

    def _on_use_groove(self, name):
        if self.generate_view.apply_groove_to_current_section(name):
            self.rail.setCurrentRow(0)         # show the change in the arrangement

    def _on_add_fill(self, name):
        if self.generate_view.apply_fill_to_current_section(name):
            self.rail.setCurrentRow(0)

    def closeEvent(self, event):
        # Child closeEvent does NOT fire inside a QStackedWidget — tear down every
        # view's worker threads here.
        self.generate_view.shutdown()
        self.drop_view.shutdown()
        self.browser_view.shutdown()
        super().closeEvent(event)

    def _about(self):
        box = QMessageBox(self)
        box.setWindowTitle(f"About {APP_NAME}")
        box.setText(f"{APP_NAME}\nPop-punk drum MIDI generator.")
        pix = QPixmap(str(theme.asset_path("art", "keyart.png")))
        if not pix.isNull():
            box.setIconPixmap(pix.scaledToWidth(96))
        box.exec()
