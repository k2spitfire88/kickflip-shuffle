"""Generate view — profile -> generate -> play -> export, driving a Controller.

The view is the renderer; `Controller` (and the engine behind it) is the single
source of truth. Every spec mutation goes through the controller; programmatic
widget updates are wrapped in blockSignals so they don't re-enter handlers.
"""
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QSpinBox, QComboBox, QFileDialog,
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


class GenerateView(QWidget):
    status = Signal(str)

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._c = controller
        self._build_ui()
        self._populate_profiles()
        self._populate_output_maps()
        self._set_controls_enabled(False)   # empty state until a profile is picked

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = QHBoxLayout(self)

        self.profiles = QListWidget()
        self.profiles.setFixedWidth(248)
        self.profiles.currentItemChanged.connect(self._on_profile_selected)
        root.addWidget(self.profiles)

        right = QVBoxLayout()
        root.addLayout(right, 1)

        title = QLabel("Generate")
        title.setObjectName("title")
        title.setFont(theme.font_role("display", 20))
        right.addWidget(title)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("BPM"))
        self.bpm = QSpinBox()
        self.bpm.setRange(40, 300)          # before any setValue (Qt default max=99)
        self.bpm.valueChanged.connect(self._on_bpm_changed)
        controls.addWidget(self.bpm)

        self.seed_label = QLabel("seed —")
        self.seed_label.setObjectName("muted")
        controls.addWidget(self.seed_label)

        self.regen_btn = QPushButton("Regenerate")
        self.regen_btn.clicked.connect(self._on_regenerate)
        controls.addWidget(self.regen_btn)

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
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self._on_stop)
        self.export_btn = QPushButton("Export .mid")
        self.export_btn.clicked.connect(self._on_export)
        transport.addWidget(self.play_btn)
        transport.addWidget(self.stop_btn)
        transport.addStretch(1)
        transport.addWidget(self.export_btn)
        right.addLayout(transport)

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
            item.setSizeHint(QSize(0, 40))
            self.profiles.setItemWidget(item, self._profile_row(prof))

    def _profile_row(self, prof):
        row = QWidget()
        # Transparent so the QListWidget::item:selected highlight shows through
        # (an opaque QWidget would paint over it).
        row.setAttribute(Qt.WA_TranslucentBackground, True)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(6, 2, 6, 2)
        label = QLabel(f"{prof['name']}\n{prof['era']}")
        lay.addWidget(label, 1)
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

    def _on_bpm_changed(self, value):
        spec = self._c.spec
        if spec is None:
            return
        # Preserve sections/overrides — do NOT rebuild the arrangement.
        self._c.build_spec_from_ui_state(
            spec["profile"], axes=spec["overrides"], sections=spec["sections"],
            tempo=value, ppq=spec.get("ppq", 480))

    def _on_map_changed(self, _index):
        name = self.map_combo.currentData()
        if name:
            self._c.set_output_map(name)

    def _on_regenerate(self):
        if self._c.spec is None:
            return
        self._c.new_seed()
        self._c.generate()
        self._refresh_seed_label()
        self.status.emit("Regenerated.")

    def _on_play(self):
        try:
            self._c.render_preview()
            self._c.play()
            self.status.emit("Playing preview (General MIDI).")
        except Exception as exc:                       # noqa: BLE001 - surface to UI
            self.status.emit(f"Playback unavailable: {exc}")
        self._refresh_seed_label()

    def _on_stop(self):
        self._c.stop()
        self.status.emit("Stopped.")

    def _on_export(self):
        path, _filter = QFileDialog.getSaveFileName(
            self, "Export MIDI", "drums.mid", "MIDI (*.mid)")
        if not path:
            return
        try:
            out = self._c.export(path)
            self.status.emit(f"Exported {out}")
        except Exception as exc:                       # noqa: BLE001 - surface to UI
            self.status.emit(f"Export failed: {exc}")
        self._refresh_seed_label()

    # ------------------------------------------------------------- helpers
    def _refresh_from_spec(self):
        spec = self._c.spec
        self.bpm.blockSignals(True)
        self.bpm.setValue(int(round(spec["tempo"])))
        self.bpm.blockSignals(False)
        self._refresh_seed_label()
        self._set_controls_enabled(True)
        self.empty_hint.setVisible(False)

    def _refresh_seed_label(self):
        s = self._c.seed
        self.seed_label.setText(f"seed {s}" if s is not None else "seed —")

    def _set_controls_enabled(self, on):
        for w in (self.bpm, self.map_combo, self.regen_btn, self.play_btn,
                  self.stop_btn, self.export_btn):
            w.setEnabled(on)
