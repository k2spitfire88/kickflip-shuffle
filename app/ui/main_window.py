"""Main window — shell hosting the Generate + Drop-audio + Browser views.

A left mode rail switches a QStackedWidget between modes (Generate / Drop audio /
Groove browser). All views share ONE Controller. The status bar surfaces messages
from every view so a missing soundfont / audio device / analysis error never
crashes the window.
"""
from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QPixmap, QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow, QMessageBox, QWidget, QHBoxLayout, QListWidget, QStackedWidget,
    QFileDialog, QApplication,
)

from app.controller import Controller
from . import theme
from .generate_view import GenerateView
from .drop_view import DropView
from .browser_view import BrowserView
from .settings import Prefs

APP_NAME = "Kickflip Shuffle"
PROJECT_FILTER = "Kickflip project (*.ppd)"


class MainWindow(QMainWindow):
    def __init__(self, controller=None, parent=None, prefs=None):
        super().__init__(parent)
        self._c = controller or Controller()
        self._prefs = prefs or Prefs()
        self._project_path = None
        self.setWindowTitle(APP_NAME)

        icon_png = theme.asset_path("art", "keyart.png")  # .icns can render blank
        if icon_png.exists():
            self.setWindowIcon(QIcon(str(icon_png)))

        central = QWidget()
        root = QHBoxLayout(central)
        self.rail = QListWidget()
        self.rail.setFixedWidth(140)
        self.rail.setSpacing(2)
        self.rail.addItems(["Generate", "Drop audio", "Browser"])
        for i in range(self.rail.count()):
            self.rail.item(i).setSizeHint(QSize(0, 34))   # avoid clipped/overlapping rows
        self.rail.setCurrentRow(0)
        root.addWidget(self.rail)

        self.stack = QStackedWidget()
        self.generate_view = GenerateView(self._c, prefs=self._prefs)
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

        self._build_menus()

        self.statusBar().showMessage("Pick a profile to start.")
        self.resize(980, 600)
        self._update_title()

    # --------------------------------------------------------------- menus
    def _build_menus(self):
        file_menu = self.menuBar().addMenu("File")
        self._add_action(file_menu, "New", self._new, QKeySequence.New)
        self._add_action(file_menu, "Open…", self._open_dialog, QKeySequence.Open)
        self._recent_menu = file_menu.addMenu("Open Recent")
        self._rebuild_recent_menu()
        file_menu.addSeparator()
        self._add_action(file_menu, "Save", self._save, QKeySequence.Save)
        self._add_action(file_menu, "Save As…", self._save_as,
                         QKeySequence.SaveAs)

        edit_menu = self.menuBar().addMenu("Edit")
        self._undo_act = self._add_action(edit_menu, "Undo", self._undo,
                                          QKeySequence.Undo)
        self._redo_act = self._add_action(edit_menu, "Redo", self._redo,
                                          QKeySequence.Redo)
        edit_menu.aboutToShow.connect(self._refresh_undo_actions)
        self.generate_view.arrangementChanged.connect(self._refresh_undo_actions)
        self._refresh_undo_actions()

        view_menu = self.menuBar().addMenu("View")
        self._theme_group = QActionGroup(self)
        for mode in ("dark", "light"):
            act = QAction(mode.capitalize(), self, checkable=True)
            act.setChecked(self._prefs.theme() == mode)
            act.triggered.connect(lambda _c, m=mode: self._apply_theme(m))
            self._theme_group.addAction(act)
            view_menu.addAction(act)

        about = QAction("About Kickflip Shuffle", self)
        about.triggered.connect(self._about)
        self.menuBar().addMenu("Help").addAction(about)

    @staticmethod
    def _add_action(menu, text, slot, shortcut=None):
        act = QAction(text, menu)
        if shortcut is not None:
            act.setShortcut(shortcut)
        act.triggered.connect(slot)
        menu.addAction(act)
        return act

    def _rebuild_recent_menu(self):
        self._recent_menu.clear()
        recents = self._prefs.recent_files()
        self._recent_menu.setEnabled(bool(recents))
        for path in recents:
            act = QAction(Path(path).name, self._recent_menu)
            act.setToolTip(path)
            act.triggered.connect(lambda _c, p=path: self._open(p))
            self._recent_menu.addAction(act)

    # ------------------------------------------------------- undo / redo
    def _refresh_undo_actions(self):
        self._undo_act.setEnabled(self._c.can_undo())
        self._redo_act.setEnabled(self._c.can_redo())

    def _undo(self):
        if self._c.undo():
            self._resync_after_history()

    def _redo(self):
        if self._c.redo():
            self._resync_after_history()

    def _resync_after_history(self):
        self.generate_view.load_current_spec(
            self.generate_view.current_section_index() or 0)
        self._refresh_undo_actions()

    # ----------------------------------------------------- project actions
    def _new(self):
        self._c.clear_spec()                       # drop held arrangement
        self.generate_view.profiles.setCurrentRow(-1)
        self.generate_view.empty_hint.setVisible(True)
        self.generate_view.editor_panel.setVisible(False)
        self.generate_view._set_controls_enabled(False)
        self._set_project_path(None)
        self._refresh_undo_actions()
        self.statusBar().showMessage("New project — pick a profile to start.")

    def _open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open project", str(self._prefs.last_project_dir()),
            PROJECT_FILTER)
        if path:
            self._open(path)

    def _open(self, path):
        try:
            data = self._c.load_project(path)
        except Exception as exc:                   # noqa: BLE001 - surface to UI
            self.statusBar().showMessage(f"Open failed: {exc}")
            return
        theme_mode = data.get("theme")
        if theme_mode in ("dark", "light"):
            self._apply_theme(theme_mode)
        self.generate_view.load_current_spec(data.get("selected_section", 0) or 0)
        self.rail.setCurrentRow(0)
        self._prefs.add_recent(path)
        self._prefs.set_last_project_dir(Path(path).parent)
        self._rebuild_recent_menu()
        self._set_project_path(path)
        self._refresh_undo_actions()
        msg = f"Opened {Path(path).name}"
        for w in data.get("warnings", []):
            msg += f"  ·  {w}"
        self.statusBar().showMessage(msg)

    def _save(self):
        if self._project_path is None:
            self._save_as()
        else:
            self._write_project(self._project_path)

    def _save_as(self):
        start = str(self._prefs.last_project_dir() / "song.ppd")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save project", start, PROJECT_FILTER)
        if not path:
            return
        if not path.endswith(".ppd"):
            path += ".ppd"
        self._write_project(path)

    def _write_project(self, path):
        try:
            self._c.save_project(path, extra={
                "selected_section": self.generate_view.current_section_index() or 0,
                "theme": self._prefs.theme(),
            })
        except Exception as exc:                   # noqa: BLE001 - surface to UI
            self.statusBar().showMessage(f"Save failed: {exc}")
            return
        self._prefs.add_recent(path)
        self._prefs.set_last_project_dir(Path(path).parent)
        self._rebuild_recent_menu()
        self._set_project_path(path)
        self.statusBar().showMessage(f"Saved {Path(path).name}")

    def _set_project_path(self, path):
        self._project_path = path
        self._update_title()

    def _update_title(self):
        name = Path(self._project_path).stem if self._project_path else "Untitled"
        self.setWindowTitle(f"{APP_NAME} — {name}")

    def _apply_theme(self, mode):
        app = QApplication.instance()
        if app is not None:
            theme.apply(app, mode=mode)
        self._prefs.set_theme(mode)
        for act in self._theme_group.actions():
            act.setChecked(act.text().lower() == mode)

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
        self.generate_view.lock_tempo.setChecked(True)   # keep the dropped song's BPM
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
        from .drag import cleanup_temp_dir
        cleanup_temp_dir()                         # remove drag-out temp .mid files
        super().closeEvent(event)

    def _about(self):
        box = QMessageBox(self)
        box.setWindowTitle(f"About {APP_NAME}")
        box.setText(f"{APP_NAME}\nPop-punk drum MIDI generator.")
        pix = QPixmap(str(theme.asset_path("art", "keyart.png")))
        if not pix.isNull():
            box.setIconPixmap(pix.scaledToWidth(96))
        box.exec()
