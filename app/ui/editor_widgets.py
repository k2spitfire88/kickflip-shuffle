"""Arrangement editor widgets (Phase 5a-ii): SectionTimeline, SectionEditor,
StepGrid. All are thin and controller-driven — every edit goes through the
Controller, which is the single source of truth. Programmatic refreshes block
signals so they don't re-enter handlers."""
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QListWidget,
    QPushButton, QComboBox, QCheckBox, QSpinBox, QSlider,
)

import engine
from engine.generate import _AXIS_KEYS as AXIS_KEYS

SECTION_ROLES = ("intro", "verse", "chorus", "bridge")
ROLES = engine.ROLES                       # 17 canonical grid rows


class SectionTimeline(QWidget):
    sectionSelected = Signal(int)
    sectionsChanged = Signal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._c = controller
        lay = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.setFlow(QListWidget.LeftToRight)
        self.list.setFixedHeight(48)
        self.list.currentRowChanged.connect(self._on_row)
        lay.addWidget(self.list)
        btns = QHBoxLayout()
        for label, slot in (("+ Add", self._add), ("Remove", self._remove),
                            ("◀", self._left), ("▶", self._right),
                            ("🔒 Lock", self._toggle_lock)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            btns.addWidget(b)
        btns.addStretch(1)
        lay.addLayout(btns)

    def refresh(self):
        self.list.blockSignals(True)
        self.list.clear()
        for s in self._c.spec["sections"]:
            role = s.get("role") or s.get("groove", "?")
            lock = "🔒" if s.get("locked") else ""
            self.list.addItem(f"{lock}{role}·{s.get('bars', 4)}")
        self.list.blockSignals(False)

    def _sel(self):
        return self.list.currentRow()

    def _on_row(self, row):
        if row >= 0:
            self.sectionSelected.emit(row)

    def _set_sections(self, secs, select):
        self._c.set_sections(secs)
        self.refresh()
        self.list.setCurrentRow(max(0, min(select, len(secs) - 1)))
        self.sectionsChanged.emit()

    def _add(self):
        secs = list(self._c.spec["sections"])
        secs.append({"role": "verse", "bars": 4})
        self._set_sections(secs, len(secs) - 1)

    def _remove(self):
        i, secs = self._sel(), list(self._c.spec["sections"])
        if 0 <= i < len(secs) and len(secs) > 1:
            del secs[i]
            self._set_sections(secs, i)

    def _move(self, delta):
        i, secs = self._sel(), list(self._c.spec["sections"])
        j = i + delta
        if 0 <= i < len(secs) and 0 <= j < len(secs):
            secs[i], secs[j] = secs[j], secs[i]
            self._set_sections(secs, j)

    def _left(self):
        self._move(-1)

    def _right(self):
        self._move(1)

    def _toggle_lock(self):
        i = self._sel()
        if i < 0:
            return
        sec = self._c.spec["sections"][i]
        self._c.set_section_locked(i, not sec.get("locked"))
        self.refresh()
        self.list.setCurrentRow(i)
        self.sectionsChanged.emit()


class SectionEditor(QWidget):
    changed = Signal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._c = controller
        self._i = None
        form = QFormLayout(self)

        self.role = QComboBox()
        self.role.addItems(SECTION_ROLES)
        self.groove = QComboBox()
        self.groove.addItem("(from role)", None)
        for g in self._c.list_grooves():
            self.groove.addItem(g["name"], g["name"])
        self.fill = QComboBox()
        self.fill.addItem("none", None)
        for f in self._c.list_fills():
            self.fill.addItem(f["name"], f["name"])
        self.bars = QSpinBox()
        self.bars.setRange(1, 32)
        self.crash = QCheckBox("crash in")
        self.feel = QComboBox()
        for label, data in (("normal", None), ("half-time", "half"),
                            ("double-time", "double")):
            self.feel.addItem(label, data)

        form.addRow("Role", self.role)
        form.addRow("Groove", self.groove)
        form.addRow("Fill", self.fill)
        form.addRow("Bars", self.bars)
        form.addRow("Feel", self.feel)
        form.addRow("", self.crash)

        self.sliders = {}
        for k in AXIS_KEYS:
            s = QSlider(Qt.Horizontal)
            s.setRange(0, 100)
            s.valueChanged.connect(self._commit)
            self.sliders[k] = s
            form.addRow(k, s)

        for w in (self.role, self.groove, self.fill, self.feel):
            w.currentIndexChanged.connect(self._commit)
        self.bars.valueChanged.connect(self._commit)
        self.crash.toggled.connect(self._commit)

    def load(self, index):
        self._i = None                     # suppress _commit during population
        s = self._c.spec["sections"][index]
        widgets = [self.role, self.groove, self.fill, self.bars, self.crash,
                   self.feel, *self.sliders.values()]
        for w in widgets:
            w.blockSignals(True)
        role = s.get("role", "verse")
        if self.role.findText(role) < 0:     # preserve a role outside the 4 presets
            self.role.addItem(role)           # (e.g. from an imported/analysed spec)
        self.role.setCurrentText(role)
        self.groove.setCurrentIndex(max(0, self.groove.findData(s.get("groove"))))
        self.fill.setCurrentIndex(max(0, self.fill.findData(
            s.get("fill") if isinstance(s.get("fill"), str) else None)))
        self.bars.setValue(s.get("bars", 4))
        self.crash.setChecked(bool(s.get("crash_in", False)))
        self.feel.setCurrentIndex(max(0, self.feel.findData(s.get("feel"))))
        axes = s.get("axes", {})
        for k, sl in self.sliders.items():
            sl.setValue(int(round(axes.get(k, 0.0) * 100)))
        for w in widgets:
            w.blockSignals(False)
        # A locked section is frozen (role -> explicit groove); editing it would
        # write a stray `role` key and corrupt the lock bookkeeping. Make the
        # editor read-only until the user unlocks (via the timeline 🔒 button).
        self.setEnabled(not s.get("locked"))
        self._i = index

    def _commit(self, *_):
        if self._i is None:
            return
        axes = {k: sl.value() / 100.0 for k, sl in self.sliders.items()
                if sl.value() > 0}
        self._c.update_section(
            self._i, role=self.role.currentText(), bars=self.bars.value(),
            crash_in=self.crash.isChecked(), groove=self.groove.currentData(),
            fill=self.fill.currentData(), axes=(axes or None),
            feel=self.feel.currentData())
        self.changed.emit()


class _GridCanvas(QWidget):
    LABEL_W, ROW_H, CELL = 78, 17, 22

    def __init__(self, grid):
        super().__init__()
        self._grid = grid
        self.setMinimumSize(self.sizeHint())

    def sizeHint(self):
        return QSize(self.LABEL_W + 16 * self.CELL, len(ROLES) * self.ROW_H)

    def mousePressEvent(self, event):
        col = (event.position().x() - self.LABEL_W) // self.CELL
        row = event.position().y() // self.ROW_H
        if 0 <= row < len(ROLES) and 0 <= col < 16:
            self._grid.toggle(int(row), int(col))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#16130d"))
        for r, role in enumerate(ROLES):
            y = r * self.ROW_H
            p.setPen(QColor("#928e86"))
            p.drawText(2, y + self.ROW_H - 4, role)
            row = self._grid.matrix.get(role, [0] * 16)
            for c in range(16):
                x = self.LABEL_W + c * self.CELL
                on = row[c] > 0
                beat = (c // 4) % 2 == 0
                p.fillRect(x + 1, y + 1, self.CELL - 2, self.ROW_H - 2,
                           QColor("#e2b84a") if on
                           else QColor("#211c14" if beat else "#1a160f"))
        ph = self._grid._playhead
        if ph is not None and 0 <= ph < 16:
            x = self.LABEL_W + ph * self.CELL
            p.fillRect(x, 0, self.CELL, len(ROLES) * self.ROW_H,
                       QColor(226, 184, 74, 70))          # translucent amber column
        p.end()


class StepGrid(QWidget):
    edited = Signal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._c = controller
        self._i = 0
        self._playhead = None                        # current step column, or None
        self.matrix = {r: [0] * 16 for r in ROLES}
        lay = QVBoxLayout(self)
        ctl = QHBoxLayout()
        ctl.addWidget(QLabel("Bar"))
        self.bar = QSpinBox()
        self.bar.setRange(0, 0)
        self.bar.valueChanged.connect(lambda *_: self._reseed())
        ctl.addWidget(self.bar)
        reset = QPushButton("Reset bar")
        reset.clicked.connect(self._reset)
        ctl.addWidget(reset)
        ctl.addStretch(1)
        lay.addLayout(ctl)
        self.canvas = _GridCanvas(self)
        lay.addWidget(self.canvas)

    def load(self, index):
        self._i = index
        self.clear_playhead()                        # drop stale playhead on switch
        bars = self._c.spec["sections"][index].get("bars", 4)
        self.bar.blockSignals(True)
        self.bar.setRange(0, max(0, bars - 1))
        if self.bar.value() > bars - 1:
            self.bar.setValue(bars - 1)
        self.bar.blockSignals(False)
        self._reseed()

    def _reseed(self):
        rows = self._c.resolved_bar(self._i, self.bar.value())
        self.matrix = {r: list(rows.get(r, [0] * 16)) for r in ROLES}
        self.canvas.update()

    def toggle(self, row, col):
        role = ROLES[row]
        self.matrix[role][col] = 0 if self.matrix[role][col] else 100
        override = {r: row_ for r, row_ in self.matrix.items() if any(row_)}
        self._c.set_bar_pattern(self._i, self.bar.value(), override)
        self.canvas.update()
        self.edited.emit()

    def _reset(self):
        self._c.clear_bar_pattern(self._i, self.bar.value())
        self._reseed()
        self.edited.emit()

    def set_playhead(self, section_index, bar_index, step):
        """Show the playhead at `step` only when this grid is displaying the
        (section, bar) currently playing; otherwise hide it."""
        showing = (section_index == self._i and bar_index == self.bar.value())
        new = step if showing else None
        if new != self._playhead:
            self._playhead = new
            self.canvas.update()

    def clear_playhead(self):
        if self._playhead is not None:
            self._playhead = None
            self.canvas.update()
