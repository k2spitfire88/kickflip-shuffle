"""Batch variations + A/B compare (Phase 8h).

Generate N random-seed renders of the CURRENT arrangement, audition each, and
"Keep" one (adopts its seed). Renders run SERIALLY on one worker thread — the
controller is not thread-safe, so parallel renders would race its held state;
each variation is produced by `controller.render_variation` (non-mutating) into a
standalone buffer, then played on the UI thread via `controller.play_buffer`.
"""
import random

from PySide6.QtCore import Qt, Signal, QObject, QThread
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QListWidget, QListWidgetItem,
)


class _VariationsWorker(QObject):
    done = Signal(list)          # [(seed, buffer)]
    failed = Signal(str)

    def __init__(self, controller, seeds, sample_rate=44100):
        super().__init__()
        self._c = controller
        self._seeds = seeds
        self._sr = sample_rate

    def run(self):
        try:
            out = [(s, self._c.render_variation(s, sample_rate=self._sr))
                   for s in self._seeds]                # serial -> no state race
            self.done.emit(out)
        except Exception as exc:                        # noqa: BLE001 - to UI
            self.failed.emit(str(exc))


class VariationsDialog(QDialog):
    keepSeed = Signal(object)    # user adopted a variation's seed (64-bit -> object)

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._c = controller
        self._results = []       # [(seed, buffer)]
        self._thread = None
        self._worker = None
        self.setWindowTitle("Variations")
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("How many"))
        self.count = QSpinBox()
        self.count.setRange(2, 8)
        self.count.setValue(4)
        top.addWidget(self.count)
        self.gen_btn = QPushButton("Generate")
        self.gen_btn.clicked.connect(self._generate)
        top.addWidget(self.gen_btn)
        top.addStretch(1)
        lay.addLayout(top)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda *_: self._play())
        lay.addWidget(self.list)

        row = QHBoxLayout()
        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(self._play)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(lambda *_: self._c.stop())
        self.keep_btn = QPushButton("Keep")
        self.keep_btn.clicked.connect(self._keep)
        for b in (self.play_btn, self.stop_btn, self.keep_btn):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        lay.addWidget(self.status)
        self._set_result_actions(False)

    # ------------------------------------------------------------ generate
    def _generate(self):
        if self._thread is not None:
            return
        n = self.count.value()
        seeds = [random.randrange(2 ** 63) for _ in range(n)]
        self.gen_btn.setEnabled(False)
        self.status.setText(f"Rendering {n} variations…")
        self._thread = QThread(self)
        self._worker = _VariationsWorker(self._c, seeds)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._thread.start()

    def _on_done(self, results):
        self._finish_thread()
        self._results = results
        self.list.clear()
        for i, (seed, _buf) in enumerate(results):
            item = QListWidgetItem(f"Variation {i + 1} — seed {seed}")
            item.setData(Qt.UserRole, i)
            self.list.addItem(item)
        if results:
            self.list.setCurrentRow(0)
        self._set_result_actions(bool(results))
        self.status.setText(f"{len(results)} variations. Play / Keep one.")

    def _on_failed(self, message):
        self._finish_thread()
        self.status.setText(f"Render failed: {message}")

    # -------------------------------------------------------------- actions
    def _current(self):
        row = self.list.currentRow()
        if 0 <= row < len(self._results):
            return self._results[row]
        return None

    def _play(self):
        cur = self._current()
        if cur is None:
            return
        seed, buf = cur
        self._c.play_buffer(buf)
        self.status.setText(f"Playing seed {seed}.")

    def _keep(self):
        cur = self._current()
        if cur is None:
            return
        self._c.stop()
        self.keepSeed.emit(int(cur[0]))
        self.accept()

    def _set_result_actions(self, on):
        for b in (self.play_btn, self.stop_btn, self.keep_btn):
            b.setEnabled(on)

    # ------------------------------------------------------------- teardown
    def _finish_thread(self):
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._worker.deleteLater()
            self._thread.deleteLater()
            self._thread = None
            self._worker = None
        self.gen_btn.setEnabled(True)

    def closeEvent(self, event):
        self._c.stop()
        self._finish_thread()                       # quit/wait + deleteLater + None
        super().closeEvent(event)
