"""Generate view — profile -> generate -> play -> export, driving a Controller.

The view is the renderer; `Controller` (and the engine behind it) is the single
source of truth. Every spec mutation goes through the controller; programmatic
widget updates are wrapped in blockSignals so they don't re-enter handlers.
"""
from PySide6.QtCore import Qt, Signal, QSize, QThread, QObject, QTimer
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QSpinBox, QComboBox, QFileDialog, QCheckBox,
)

from engine.generate import _AXIS_KEYS as AXIS_KEYS  # single source of axis order

from . import theme


class AxisFingerprint(QWidget):
    """A compact read-only bar-viz of a profile's 7 axis values (0..1)."""

    def __init__(self, axes, parent=None):
        super().__init__(parent)
        self._vals = [float(axes.get(k, 0.0)) for k in AXIS_KEYS]
        self.setMinimumSize(84, 18)

    def sizeHint(self):
        return QSize(84, 18)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setPen(Qt.NoPen)
        n = len(self._vals)
        w = self.width() / n
        h = self.height()
        for i, v in enumerate(self._vals):
            bar_h = max(1, int(max(0.0, min(1.0, v)) * h))
            p.setBrush(QColor(theme.DARK["accent"]))
            p.drawRect(int(i * w) + 1, h - bar_h, max(1, int(w) - 2), bar_h)
        p.end()


class _RenderWorker(QObject):
    """Runs the (potentially slow) fluidsynth render off the UI thread."""
    done = Signal()
    failed = Signal(str)

    def __init__(self, controller):
        super().__init__()
        self._c = controller

    def run(self):
        try:
            self._c.render_preview()
            self.done.emit()
        except Exception as exc:                 # noqa: BLE001 - surfaced to UI
            self.failed.emit(str(exc))


class GenerateView(QWidget):
    status = Signal(str)
    # Emits the arrangement-editor's selected section index, or None when no spec
    # / no selection. The groove browser uses it to enable/disable apply buttons.
    sectionSelectionChanged = Signal(object)
    # Any arrangement edit (section/timeline/grid/bpm) — MainWindow refreshes the
    # Undo/Redo enable-state on this.
    arrangementChanged = Signal()

    def __init__(self, controller, parent=None, prefs=None):
        super().__init__(parent)
        self._c = controller
        from .settings import Prefs
        self._prefs = prefs or Prefs()
        self._last_export = None            # last written .mid path (for Reveal)
        self._thread = None
        self._worker = None
        self._taps = []                     # tap-tempo click timestamps
        self._play_target = None            # None = whole song, int = section index
        self._play_timer = QTimer(self)     # playhead poll while previewing
        self._play_timer.setInterval(33)    # ~30 Hz
        self._play_timer.timeout.connect(self._tick_playhead)
        self._build_ui()
        self._populate_profiles()
        self._populate_output_maps()
        self._set_controls_enabled(False)   # empty state until a profile is picked

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self.setObjectName("generateRoot")      # grit background target (theme QSS)
        root = QHBoxLayout(self)

        self.profiles = QListWidget()
        self.profiles.setFixedWidth(248)
        self.profiles.currentItemChanged.connect(self._on_profile_selected)
        root.addWidget(self.profiles)

        right = QVBoxLayout()
        root.addLayout(right, 1)

        title = QLabel()
        wordmark = QPixmap(str(theme.asset_path("wordmark.png")))
        if not wordmark.isNull():
            title.setPixmap(wordmark.scaledToHeight(44, Qt.SmoothTransformation))
        else:
            title.setText("Generate")
            title.setObjectName("title")
            title.setFont(theme.font_role("display", 20))
        right.addWidget(title)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("BPM"))
        self.bpm = QSpinBox()
        self.bpm.setRange(40, 300)          # before any setValue (Qt default max=99)
        self.bpm.valueChanged.connect(self._on_bpm_changed)
        controls.addWidget(self.bpm)
        self.tap_btn = QPushButton("Tap")
        self.tap_btn.setToolTip("Tap repeatedly to set the tempo.")
        self.tap_btn.clicked.connect(self._on_tap)
        controls.addWidget(self.tap_btn)

        self.seed_label = QLabel("seed —")
        self.seed_label.setObjectName("muted")
        controls.addWidget(self.seed_label)

        self.regen_btn = QPushButton("Regenerate")
        self.regen_btn.clicked.connect(self._on_regenerate)
        controls.addWidget(self.regen_btn)
        self.variations_btn = QPushButton("Variations…")
        self.variations_btn.clicked.connect(self._on_variations)
        controls.addWidget(self.variations_btn)

        controls.addWidget(QLabel("Output"))
        self.map_combo = QComboBox()
        self.map_combo.currentIndexChanged.connect(self._on_map_changed)
        controls.addWidget(self.map_combo)
        controls.addStretch(1)
        right.addLayout(controls)

        transport = QHBoxLayout()
        self.play_btn = QPushButton("Play")
        self.play_btn.setObjectName("primary")
        self.play_btn.clicked.connect(self._on_play)
        self.play_btn.setToolTip("Preview the selected section.")
        self.play_all_btn = QPushButton("Play Song")
        self.play_all_btn.setToolTip("Preview the whole arrangement.")
        self.play_all_btn.clicked.connect(self._on_play_all)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self._on_stop)
        self.count_in = QCheckBox("Count-in")
        self.count_in.setToolTip("Prepend a 4-beat click before preview playback.")
        self.count_in.toggled.connect(
            lambda on: self._c.set_count_in(4 if on else 0))
        self.export_btn = QPushButton("Export .mid")
        self.export_btn.clicked.connect(self._on_export)
        self.export_as_btn = QPushButton("Export As…")
        self.export_as_btn.clicked.connect(self._on_export_as)
        self.reveal_btn = QPushButton("Reveal")
        self.reveal_btn.clicked.connect(self._on_reveal)
        from .drag import MidiDragButton
        self.drag_btn = MidiDragButton(
            "Drag to DAW ⇱",
            export_fn=lambda path: self._c.export(path),
            enabled_fn=lambda: self._c.spec is not None,
            on_status=self.status.emit)
        self.drag_btn.setToolTip("Drag this onto a DAW/EZ Drummer track to drop the "
                                 ".mid directly.")
        transport.addWidget(self.play_btn)
        transport.addWidget(self.play_all_btn)
        transport.addWidget(self.stop_btn)
        transport.addWidget(self.count_in)
        transport.addStretch(1)
        transport.addWidget(self.drag_btn)
        transport.addWidget(self.export_btn)
        transport.addWidget(self.export_as_btn)
        transport.addWidget(self.reveal_btn)
        right.addLayout(transport)

        # Arrangement editor (timeline + per-section editor + step grid), shown
        # once a profile is selected.
        from .editor_widgets import SectionTimeline, SectionEditor, StepGrid
        self.editor_panel = QWidget()
        ep = QVBoxLayout(self.editor_panel)
        ep.setContentsMargins(0, 0, 0, 0)
        self.timeline = SectionTimeline(self._c)
        self.section_editor = SectionEditor(self._c)
        self.grid = StepGrid(self._c)
        ep.addWidget(self.timeline)
        edit_row = QHBoxLayout()
        edit_row.addWidget(self.section_editor, 1)
        edit_row.addWidget(self.grid, 2)
        ep.addLayout(edit_row)
        self.timeline.sectionSelected.connect(self._select_section)
        self.timeline.sectionsChanged.connect(self._on_sections_changed)
        self.section_editor.changed.connect(self._on_section_edited)
        self.grid.edited.connect(self._on_grid_edited)
        right.addWidget(self.editor_panel, 1)
        self.editor_panel.setVisible(False)

        # Empty-state hint (key art + prompt) shown until a profile is chosen.
        self.empty_hint = QLabel()
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.setObjectName("muted")
        pix = QPixmap(str(theme.asset_path("art", "keyart.png")))
        if not pix.isNull():
            self.empty_hint.setPixmap(
                pix.scaledToWidth(360, Qt.SmoothTransformation))
        else:
            self.empty_hint.setText("Pick a profile to start.")
        right.addWidget(self.empty_hint, 1, Qt.AlignCenter)

    # ----------------------------------------------------------- populate
    def _populate_profiles(self):
        for prof in self._c.list_profiles():
            item = QListWidgetItem(self.profiles)   # parent arg already inserts it
            item.setData(Qt.UserRole, prof["name"])
            item.setSizeHint(QSize(0, 52))          # room for name + era (2 lines)
            self.profiles.setItemWidget(item, self._profile_row(prof))

    def _profile_row(self, prof):
        row = QWidget()
        # Transparent so the QListWidget::item:selected highlight shows through
        # (an opaque QWidget would paint over it).
        row.setAttribute(Qt.WA_TranslucentBackground, True)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(8, 4, 6, 4)
        text = QVBoxLayout()
        text.setSpacing(0)
        name = QLabel(prof["name"])
        era = QLabel(prof["era"])
        era.setObjectName("muted")                  # smaller, dimmed subtitle
        era.setFont(theme.font_role("mono", 10))
        text.addWidget(name)
        text.addWidget(era)
        lay.addLayout(text, 1)
        lay.addWidget(AxisFingerprint(prof["axes"]))
        return row

    def _populate_output_maps(self):
        self.map_combo.blockSignals(True)
        for name, _n_roles, verified in self._c.list_output_maps():
            label = name if verified else f"{name} (unverified)"
            self.map_combo.addItem(label, userData=name)
        self.map_combo.blockSignals(False)

    # ------------------------------------------------------------ handlers
    def _on_profile_selected(self, current, _previous):
        if current is None:
            return
        name = current.data(Qt.UserRole)
        self._c.song_from_profile(name)
        self._refresh_from_spec()

    def _on_variations(self):
        if self._c.spec is None:
            return
        from .variations import VariationsDialog
        dlg = VariationsDialog(self._c, self)
        dlg.keepSeed.connect(self._on_keep_variation)
        dlg.exec()

    def _on_keep_variation(self, seed):
        self._c.set_seed(int(seed))
        self._c.generate()
        self._refresh_seed_label()
        idx = self.current_section_index()
        if idx is not None:
            self.grid.load(idx)
        self.status.emit(f"Kept variation (seed {seed}).")

    def _on_tap(self):
        """Tap-tempo: average recent inter-tap intervals -> BPM -> set via the BPM
        spinbox (so it routes through set_tempo, tracked/undoable). Resets after a
        >2 s gap."""
        import time
        if self._c.spec is None:
            return
        now = time.monotonic()
        if self._taps and now - self._taps[-1] > 2.0:
            self._taps = []
        self._taps.append(now)
        self._taps = self._taps[-8:]                   # average the last few taps
        if len(self._taps) >= 2:
            intervals = [b - a for a, b in zip(self._taps, self._taps[1:])]
            avg = sum(intervals) / len(intervals)
            if avg <= 0:                               # identical timestamps -> skip
                return
            bpm = max(40, min(300, int(round(60.0 / avg))))
            self.bpm.setValue(bpm)                     # fires _on_bpm_changed
            self.status.emit(f"Tap tempo: {bpm} BPM")

    def _on_bpm_changed(self, value):
        if self._c.spec is None:
            return
        # Tracked in-place tempo edit (undoable); no full-spec rebuild, so it does
        # not reset undo history.
        self._c.set_tempo(value)
        self.arrangementChanged.emit()

    def _on_map_changed(self, _index):
        name = self.map_combo.currentData()
        if name:
            self._c.set_output_map(name)

    def _on_regenerate(self):
        if self._c.spec is None:
            return
        self._c.regenerate()                       # locked sections keep their part
        self._refresh_seed_label()
        idx = self.current_section_index()
        if idx is not None:
            self.grid.load(idx)                    # re-rolled patterns changed
        self.status.emit("Regenerated (locked sections kept).")

    def _on_play(self):
        # Intuitive default: Play previews the SELECTED section (whole song if no
        # section is selected). "Play Song" plays the full arrangement.
        self._start_render(target=self.current_section_index())

    def _on_play_all(self):
        self._start_render(target=None)                # whole arrangement

    def _start_render(self, *, target):
        if self._thread is not None:                   # a render is already running
            return                                     # ignore the click; keep its target
        # Assign AFTER the guard on purpose: a click during an in-flight render is
        # ignored entirely (controls are also disabled below), so it must not
        # overwrite the running render's target.
        self._play_target = target
        # Disable ALL mutating controls for the render duration: the worker thread
        # reads/writes controller spec/seed/buffer, so a concurrent Regenerate/BPM/
        # Export would race it (render against a half-swapped spec / clobbered buffer).
        self._set_controls_enabled(False)
        self.status.emit("Rendering preview…")
        self._thread = QThread(self)
        self._worker = _RenderWorker(self._c)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_render_done)
        self._worker.failed.connect(self._on_render_failed)
        self._thread.start()

    def _finish_thread(self):
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._worker.deleteLater()
            self._thread.deleteLater()
            self._thread = None
            self._worker = None
        self._set_controls_enabled(True)
        self._refresh_seed_label()

    def shutdown(self):
        """Quit/wait any running render thread. Called by MainWindow.closeEvent
        (a child widget's closeEvent does NOT fire inside a QStackedWidget)."""
        self._play_timer.stop()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    def _on_render_done(self):
        self._finish_thread()
        try:
            if self._play_target is not None:
                self._c.play_section(self._play_target)
                self.status.emit(f"Playing section {self._play_target + 1} "
                                 "(General MIDI).")
            else:
                self._c.play()                         # transport is non-blocking
                self.status.emit("Playing preview (General MIDI).")
            self._play_timer.start()                   # drive the playhead
        except Exception as exc:                       # noqa: BLE001 - surface to UI
            self.status.emit(f"Playback unavailable: {exc}")

    def _on_render_failed(self, message):
        self._finish_thread()
        self._play_timer.stop()
        self.grid.clear_playhead()
        self.status.emit(f"Playback unavailable: {message}")

    def _on_stop(self):
        self._c.stop()
        self._play_timer.stop()
        self.grid.clear_playhead()
        self.status.emit("Stopped.")

    # ------------------------------------------------------------ playhead
    def _tick_playhead(self):
        pos = self._position_to_grid(self._c.playback_position)
        if pos is None:                                # ended (or no spec) -> clear
            self._play_timer.stop()
            self.grid.clear_playhead()
            return
        self.grid.set_playhead(*pos)

    _FEEL = {"normal": (1, 1), "half": (2, 1), "double": (1, 2)}

    def _position_to_grid(self, seconds):
        """Map a playback position (seconds) to (section_index, bar_in_section,
        step 0..15), or None if there is no spec or the position is past the
        arrangement end. 4/4, 16 steps per bar; per-section `feel` scales bar
        width (mirrors the engine's _iter_bars)."""
        spec = self._c.spec
        if spec is None or seconds <= 0:
            return None                            # not playing yet
        # Map transport position to musical time: drop the count-in head, add the
        # base (0 for the full song; the section start when auditioning a section).
        seconds = seconds - self._c.preview_offset + self._c.play_base
        if seconds < 0:
            return None                            # still counting in -> no playhead
        tempo = spec.get("tempo") or 120
        ppq = spec.get("ppq", 480)
        step_ticks = ppq // 4
        bar_ticks = 16 * step_ticks
        tick = seconds * tempo * ppq / 60.0
        acc = 0
        for si, sec in enumerate(spec.get("sections", [])):
            num, den = self._FEEL.get(sec.get("feel", "normal"), (1, 1))
            sbar = bar_ticks * num // den
            sstep = max(1, step_ticks * num // den)
            sec_ticks = int(sec.get("bars", 4)) * sbar
            if tick < acc + sec_ticks:
                into = tick - acc
                bar_in = int(into // sbar)
                step = max(0, min(15, int((into % sbar) // sstep)))
                return si, bar_in, step
            acc += sec_ticks
        return None                                    # past the end (into tail)

    def _on_export(self):
        """Export straight to the default folder with a de-duped filename."""
        target = self._dedup_path(self._prefs.export_dir() / "drums.mid")
        self._do_export(str(target))

    def _on_export_as(self):
        start = str(self._prefs.export_dir() / "drums.mid")
        path, _filter = QFileDialog.getSaveFileName(
            self, "Export MIDI", start, "MIDI (*.mid)")
        if path:
            self._do_export(path)

    def _do_export(self, path):
        try:
            out = self._c.export(path)
            self._last_export = str(out)
            self.status.emit(f"Exported {out}")
        except Exception as exc:                       # noqa: BLE001 - surface to UI
            self.status.emit(f"Export failed: {exc}")
        self._refresh_seed_label()

    def _on_reveal(self):
        # Reveal stays enabled without a spec on purpose — opening the output
        # folder is useful any time, unlike the spec-dependent transport buttons.
        import sys
        import subprocess
        from pathlib import Path
        if self._last_export:
            target, folder = self._last_export, str(Path(self._last_export).parent)
        else:
            target = folder = str(self._prefs.export_dir())
        if sys.platform != "darwin":
            self.status.emit(f"Output folder: {folder}")
            return
        cmd = ["open", "-R", target] if self._last_export else ["open", target]
        subprocess.Popen(cmd)
        self.status.emit(f"Revealed {target}")

    @staticmethod
    def _dedup_path(path):
        """Return `path`, or `<stem>-N<suffix>` at the first free N (no clobber)."""
        from pathlib import Path
        path = Path(path)
        if not path.exists():
            return path
        n = 2
        while True:
            cand = path.with_name(f"{path.stem}-{n}{path.suffix}")
            if not cand.exists():
                return cand
            n += 1

    # ------------------------------------------------------------- helpers
    def _refresh_from_spec(self, selected_section=0):
        spec = self._c.spec
        self.bpm.blockSignals(True)
        self.bpm.setValue(int(round(spec["tempo"])))
        self.bpm.blockSignals(False)
        self._refresh_seed_label()
        self._set_controls_enabled(True)
        self.empty_hint.setVisible(False)
        self.editor_panel.setVisible(True)
        self.timeline.refresh()
        n = len(spec.get("sections", []))
        if n:
            row = max(0, min(int(selected_section or 0), n - 1))   # clamp saved index
            self.timeline.list.setCurrentRow(row)
            self._select_section(row)
        else:
            self.sectionSelectionChanged.emit(None)

    def load_current_spec(self, selected_section=0):
        """Load an externally-set current spec (e.g. built from Drop analysis or a
        loaded .ppd), restoring `selected_section` (clamped to the live range).

        Selects the matching profile row WITHOUT firing _on_profile_selected
        (which would call song_from_profile and discard the loaded sections), then
        refreshes the editor from controller.spec.
        """
        spec = self._c.spec
        if spec is None:
            return
        self.profiles.blockSignals(True)
        for i in range(self.profiles.count()):
            if self.profiles.item(i).data(Qt.UserRole) == spec.get("profile"):
                self.profiles.setCurrentRow(i)
                break
        self.profiles.blockSignals(False)
        self._refresh_from_spec(selected_section)

    def _select_section(self, index):
        self.section_editor.load(index)
        self.grid.load(index)
        self.sectionSelectionChanged.emit(self.current_section_index())

    # --------------------------------------------------- groove-browser API
    def current_section_index(self):
        """Arrangement-editor selected section index, or None if no spec / no
        selection / stale row. Bounds-checked against the live section count."""
        spec = self._c.spec
        if spec is None:
            return None
        row = self.timeline.list.currentRow()
        if row < 0 or row >= len(spec.get("sections", [])):
            return None
        return row

    def apply_groove_to_current_section(self, name):
        """Set the current section's groove (browser 'Use in current section').
        Passes role=None explicitly so a role-based section drops its role key
        rather than carrying both. No-op (returns False) if no section is live."""
        idx = self.current_section_index()
        if idx is None:
            return False
        self._c.update_section(idx, groove=name, role=None)
        self.timeline.refresh()
        self._select_section(idx)
        self.arrangementChanged.emit()          # undoable edit -> refresh undo state
        self.status.emit(f"Section {idx + 1} groove -> {name}.")
        return True

    def apply_fill_to_current_section(self, name):
        """Set the current section's fill (browser 'Add as fill'). No-op if no
        section is live."""
        idx = self.current_section_index()
        if idx is None:
            return False
        self._c.update_section(idx, fill=name)
        self.timeline.refresh()
        self._select_section(idx)
        self.arrangementChanged.emit()          # undoable edit -> refresh undo state
        self.status.emit(f"Section {idx + 1} fill -> {name}.")
        return True

    def _on_sections_changed(self):
        self._refresh_seed_label()           # spec mutated; seed/preview unaffected here
        self.arrangementChanged.emit()

    def _on_section_edited(self):
        # role/bars label + groove/bars may change the resolved grid -> refresh both.
        self.timeline.refresh()
        if self.section_editor._i is not None:
            self.grid.load(self.section_editor._i)
        self.arrangementChanged.emit()

    def _on_grid_edited(self):
        self.arrangementChanged.emit()

    def _refresh_seed_label(self):
        s = self._c.seed
        self.seed_label.setText(f"seed {s}" if s is not None else "seed —")

    def _set_controls_enabled(self, on):
        for w in (self.bpm, self.map_combo, self.regen_btn, self.play_btn,
                  self.play_all_btn, self.stop_btn, self.export_btn,
                  self.export_as_btn, self.drag_btn, self.tap_btn,
                  self.variations_btn):
            w.setEnabled(on)
