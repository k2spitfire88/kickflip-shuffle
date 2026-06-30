"""Main window — shell hosting the Generate view (Phase 5a-i).

A left mode rail (Generate / Drop audio / Groove browser) is stubbed for Phases
5b/c; only Generate is wired now. The status bar surfaces Play/Export messages
(incl. errors) from the Generate view so a missing soundfont or audio device
never crashes the window.
"""
from PySide6.QtGui import QIcon, QPixmap, QAction
from PySide6.QtWidgets import QMainWindow, QMessageBox

from app.controller import Controller
from . import theme
from .generate_view import GenerateView

APP_NAME = "Kickflip Shuffle"


class MainWindow(QMainWindow):
    def __init__(self, controller=None, parent=None):
        super().__init__(parent)
        self._c = controller or Controller()
        self.setWindowTitle(APP_NAME)

        icon_png = theme.asset_path("art", "keyart.png")  # .icns can render blank
        if icon_png.exists():
            self.setWindowIcon(QIcon(str(icon_png)))

        self.view = GenerateView(self._c)
        self.view.status.connect(self.statusBar().showMessage)
        self.setCentralWidget(self.view)

        about = QAction("About Kickflip Shuffle", self)
        about.triggered.connect(self._about)
        self.menuBar().addMenu("Help").addAction(about)

        self.statusBar().showMessage("Pick a profile to start.")
        self.resize(900, 560)

    def _about(self):
        box = QMessageBox(self)
        box.setWindowTitle(f"About {APP_NAME}")
        box.setText(f"{APP_NAME}\nPop-punk drum MIDI generator.")
        pix = QPixmap(str(theme.asset_path("art", "keyart.png")))
        if not pix.isNull():
            box.setIconPixmap(pix.scaledToWidth(96))
        box.exec()
