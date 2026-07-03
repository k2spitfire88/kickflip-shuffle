"""Groove browser (Phase 5c) — audition the 26 grooves + 13 fills and push one
into the current arrangement section.

Grooves are grouped by their primary ROLE (verse/chorus/bridge/intro) and fills
under "Fills"; each row carries a "Used by" badge of the profiles that reference
it (data from `controller.list_groove_usage`). Preview is flavored by the Generate
view's current profile (`controller.preview_groove` -> `controller.audition`) and
rendered off the UI thread. Apply buttons are disabled until a section is live in
the arrangement editor; "Use in current section" targets a groove, "Add as fill"
targets a fill.
"""
from PySide6.QtCore import Qt, Signal, QObject, QThread
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem,
)

from . import theme

# Groove role groups (priority order picks a groove's single primary role) plus
# the fills bucket. Fills carry the synthetic role "fill" from groove_usage().
_GROOVE_PRIORITY = ("chorus", "bridge", "verse", "intro")
_GROUP_ORDER = ("verse", "chorus", "bridge", "intro", "other", "fill")
_GROUP_LABELS = {
    "verse": "Verse grooves", "chorus": "Chorus grooves",
    "bridge": "Bridge grooves", "intro": "Intro grooves",
    "other": "Other grooves", "fill": "Fills",
}


class _PreviewWorker(QObject):
    """Builds + renders a throwaway audition spec off the UI thread."""
    done = Signal()
    failed = Signal(str)

    def __init__(self, controller, name, kind):
        super().__init__()
        self._c = controller
        self._name = name
        self._kind = kind

    def run(self):
        try:
            spec = self._c.preview_groove(self._name, kind=self._kind)
            self._c.audition(spec)
            self.done.emit()
        except Exception as exc:                     # noqa: BLE001 - surfaced to UI
            self.failed.emit(str(exc))


class BrowserView(QWidget):
    status = Signal(str)
    useGroove = Signal(str)      # -> MainWindow -> generate.apply_groove_to_current_section
    addFill = Signal(str)        # -> MainWindow -> generate.apply_fill_to_current_section

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._c = controller
        self._thread = None
        self._worker = None
        self._section_available = False       # set by set_apply_enabled
        self._current_name = None
        self._current_kind = None
        self._build_ui()
        self._populate()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self.setObjectName("browserRoot")
        root = QHBoxLayout(self)

        self.tree = QTreeWidget()
        self.tree.setFixedWidth(320)
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(self._on_selected)
        root.addWidget(self.tree)

        right = QVBoxLayout()
        root.addLayout(right, 1)

        self.name_label = QLabel("Select a groove")
        self.name_label.setObjectName("title")
        self.name_label.setFont(theme.font_role("display", 20))
        right.addWidget(self.name_label)

        self.desc_label = QLabel("")
        self.desc_label.setWordWrap(True)
        right.addWidget(self.desc_label)

        self.usedby_label = QLabel("")
        self.usedby_label.setObjectName("muted")
        self.usedby_label.setWordWrap(True)
        right.addWidget(self.usedby_label)

        transport = QHBoxLayout()
        self.play_btn = QPushButton("Play")
        self.play_btn.setObjectName("primary")
        self.play_btn.clicked.connect(self._on_play)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self._on_stop)
        transport.addWidget(self.play_btn)
        transport.addWidget(self.stop_btn)
        transport.addStretch(1)
        right.addLayout(transport)

        apply_row = QHBoxLayout()
        self.use_btn = QPushButton("Use in current section")
        self.use_btn.clicked.connect(self._on_use)
        self.fill_btn = QPushButton("Add as fill")
        self.fill_btn.clicked.connect(self._on_add_fill)
        apply_row.addWidget(self.use_btn)
        apply_row.addWidget(self.fill_btn)
        apply_row.addStretch(1)
        right.addLayout(apply_row)
        right.addStretch(1)

        self._set_detail_enabled(False)
        self._update_apply_buttons()

    def _populate(self):
        usage = self._c.list_groove_usage()
        groups = {g: [] for g in _GROUP_ORDER}
        for g in self._c.list_grooves():
            name = g["name"]
            roles = usage.get(name, {}).get("roles", [])
            role = next((r for r in _GROOVE_PRIORITY if r in roles), "other")
            groups[role].append((name, "groove", g.get("description"),
                                 usage.get(name, {}).get("profiles", [])))
        for f in self._c.list_fills():
            name = f["name"]
            groups["fill"].append((name, "fill", f.get("description"),
                                   usage.get(name, {}).get("profiles", [])))

        self.tree.blockSignals(True)
        for key in _GROUP_ORDER:
            rows = groups[key]
            if not rows:
                continue
            head = QTreeWidgetItem(self.tree, [f"{_GROUP_LABELS[key]} ({len(rows)})"])
            head.setFlags(Qt.ItemIsEnabled)          # header not selectable
            for name, kind, desc, profiles in rows:
                item = QTreeWidgetItem(head, [name])
                item.setData(0, Qt.UserRole, (name, kind, desc, profiles))
                if desc:
                    item.setToolTip(0, desc)
            head.setExpanded(True)
        self.tree.blockSignals(False)

    # ------------------------------------------------------------ handlers
    def _on_selected(self, current, _previous):
        data = current.data(0, Qt.UserRole) if current is not None else None
        if data is None:                             # header row or cleared
            self._current_name = self._current_kind = None
            self.name_label.setText("Select a groove")
            self.desc_label.setText("")
            self.usedby_label.setText("")
            self._set_detail_enabled(False)
            self._update_apply_buttons()
            return
        name, kind, desc, profiles = data
        self._current_name, self._current_kind = name, kind
        self.name_label.setText(name)
        self.desc_label.setText(desc or "(no description)")
        self.usedby_label.setText(
            "Used by: " + (", ".join(profiles) if profiles else "— (unused)"))
        self._set_detail_enabled(True)
        self._update_apply_buttons()

    def _on_play(self):
        if self._thread is not None or self._current_name is None:
            return
        self.play_btn.setEnabled(False)
        self.status.emit(f"Rendering {self._current_name}…")
        self._thread = QThread(self)
        self._worker = _PreviewWorker(self._c, self._current_name, self._current_kind)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_render_done)
        self._worker.failed.connect(self._on_render_failed)
        self._thread.start()

    def _on_render_done(self):
        self._finish_thread()
        try:
            self._c.play()
            self.status.emit(f"Playing {self._current_name} (General MIDI).")
        except Exception as exc:                     # noqa: BLE001 - surface to UI
            self.status.emit(f"Playback unavailable: {exc}")

    def _on_render_failed(self, message):
        self._finish_thread()
        self.status.emit(f"Preview unavailable: {message}")

    def _on_stop(self):
        self._c.stop()
        self.status.emit("Stopped.")

    def _on_use(self):
        if self._current_kind == "groove" and self._current_name:
            self.useGroove.emit(self._current_name)

    def _on_add_fill(self):
        if self._current_kind == "fill" and self._current_name:
            self.addFill.emit(self._current_name)

    # -------------------------------------------------------- external API
    def set_apply_enabled(self, section_index):
        """Called by MainWindow relaying generate.sectionSelectionChanged. A live
        (non-None) section index enables the apply button matching the current
        selection's kind."""
        self._section_available = section_index is not None
        self._update_apply_buttons()

    # ------------------------------------------------------------- helpers
    def _update_apply_buttons(self):
        avail = self._section_available
        self.use_btn.setEnabled(avail and self._current_kind == "groove")
        self.fill_btn.setEnabled(avail and self._current_kind == "fill")

    def _set_detail_enabled(self, on):
        self.play_btn.setEnabled(on)
        self.stop_btn.setEnabled(on)

    def _finish_thread(self):
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._worker.deleteLater()
            self._thread.deleteLater()
            self._thread = None
            self._worker = None
        self.play_btn.setEnabled(self._current_name is not None)

    def shutdown(self):
        """Quit/wait any running preview thread and finalize it. Called by
        MainWindow.closeEvent (a child widget's closeEvent does NOT fire inside a
        QStackedWidget). Disconnect the worker first so a done/failed signal that
        fires during quit() can't re-enter a slot after teardown."""
        if self._thread is None:
            return
        try:
            self._worker.done.disconnect(self._on_render_done)
            self._worker.failed.disconnect(self._on_render_failed)
        except (RuntimeError, TypeError):        # already disconnected
            pass
        self._thread.quit()
        self._thread.wait()
        self._worker.deleteLater()
        self._thread.deleteLater()
        self._thread = None
        self._worker = None

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
