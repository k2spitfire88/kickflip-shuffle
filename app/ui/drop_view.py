"""Drop-audio view (F2 UI): drag in an audio file, analyse it on a worker thread
(Controller.analyze_audio), review the detected tempo/roles, pick a profile, and
'Build drums to fit' -> a spec loaded into the Generate view for correction.

Minimal by design: per-segment correction happens in the arrangement editor after
Build. The analysed result is captured from the worker and passed explicitly to
spec_from_analysis (never relying on the controller's held _analysis field)."""
import os

from PySide6.QtCore import Qt, Signal, QThread, QObject
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton, QComboBox,
    QCheckBox, QSpinBox, QListWidget, QFileDialog,
)

AUDIO_EXTS = {".wav", ".flac", ".ogg", ".aif", ".aiff", ".mp3", ".m4a"}


def _is_audio_url(url):
    """True if a QUrl points at a local audio file we can analyse."""
    if not url.isLocalFile():
        return False
    return os.path.splitext(url.toLocalFile())[1].lower() in AUDIO_EXTS


class _AnalyzeWorker(QObject):
    done = Signal(object)          # AnalysisResult
    failed = Signal(str)

    def __init__(self, controller, path, alignment, known_tempo):
        super().__init__()
        self._c = controller
        self._path = path
        self._alignment = alignment
        self._known_tempo = known_tempo

    def run(self):
        try:
            result = self._c.analyze_audio(
                self._path, alignment=self._alignment,
                known_tempo=self._known_tempo)
            self.done.emit(result)
        except Exception as exc:               # noqa: BLE001 - surfaced to UI
            self.failed.emit(str(exc))


class DropView(QWidget):
    status = Signal(str)
    specBuilt = Signal()
    busy = Signal(bool)                        # analysis in flight (rail disable)

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._c = controller
        self._path = None
        self._result = None
        self._thread = None
        self._worker = None
        self.setAcceptDrops(True)
        self._build_ui()
        self._update_enabled()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        lay = QVBoxLayout(self)

        self.drop_zone = QFrame()
        self.drop_zone.setObjectName("panel")
        self.drop_zone.setMinimumHeight(120)
        dz = QVBoxLayout(self.drop_zone)
        self.drop_label = QLabel("Drag an audio file here")
        self.drop_label.setAlignment(Qt.AlignCenter)
        self.drop_label.setObjectName("muted")
        dz.addWidget(self.drop_label)
        choose = QPushButton("Choose file…")
        choose.clicked.connect(self._choose)
        dz.addWidget(choose, 0, Qt.AlignCenter)
        lay.addWidget(self.drop_zone)

        inputs = QHBoxLayout()
        self.known_check = QCheckBox("Known tempo")
        self.known_spin = QSpinBox()
        self.known_spin.setRange(40, 300)
        self.known_spin.setValue(120)
        self.known_check.toggled.connect(self._update_enabled)
        inputs.addWidget(self.known_check)
        inputs.addWidget(self.known_spin)
        inputs.addWidget(QLabel("Align"))
        self.align = QComboBox()
        self.align.addItems(["fixed_grid", "follow_beats"])
        inputs.addWidget(self.align)
        self.cut_click = QCheckBox("Cut to click (starts on beat 1)")
        self.cut_click.toggled.connect(self._on_cut_click)
        inputs.addWidget(self.cut_click)
        inputs.addStretch(1)
        lay.addLayout(inputs)

        row = QHBoxLayout()
        self.analyze_btn = QPushButton("Analyse")
        self.analyze_btn.clicked.connect(self._start_analyze)
        row.addWidget(self.analyze_btn)
        row.addWidget(QLabel("Profile"))
        self.profile = QComboBox()
        for p in self._c.list_profiles():
            self.profile.addItem(p["name"], p["name"])
        self.profile.currentIndexChanged.connect(self._populate_eras)
        row.addWidget(self.profile)
        self.era_label = QLabel("Era")
        self.era = QComboBox()
        self.era.setToolTip("Optional: build your song in a specific era's style.")
        row.addWidget(self.era_label)
        row.addWidget(self.era)
        self.build_btn = QPushButton("Build drums to fit")
        self.build_btn.setObjectName("primary")
        self.build_btn.clicked.connect(self._build)
        row.addWidget(self.build_btn)
        row.addStretch(1)
        lay.addLayout(row)

        self._populate_eras()

        self.detected = QLabel("No audio analysed yet.")
        self.detected.setObjectName("muted")
        lay.addWidget(self.detected)
        self.sections = QListWidget()
        lay.addWidget(self.sections, 1)

    # ------------------------------------------------------------ file in
    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if urls and _is_audio_url(urls[0]):
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls and _is_audio_url(urls[0]):
            self.load_file(urls[0].toLocalFile())

    def _choose(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose audio", "",
            "Audio (*.wav *.flac *.ogg *.aif *.aiff *.mp3 *.m4a)")
        if path:
            self.load_file(path)

    def load_file(self, path):
        self._path = path
        self.drop_label.setText(os.path.basename(path))
        self._update_enabled()

    # ------------------------------------------------------------- inputs
    def _on_cut_click(self, on):
        # Cut-to-click trusts the grid from t=0: force fixed_grid + known tempo.
        if on:
            self.known_check.setChecked(True)
            self.align.setCurrentText("fixed_grid")
        self.known_check.setEnabled(not on)
        self.align.setEnabled(not on)
        self._update_enabled()

    def _populate_eras(self, *_):
        """Fill the Era combo for the selected profile (hidden for flat profiles)."""
        eras = self._c.list_profile_eras(self.profile.currentData())
        self.era.blockSignals(True)
        self.era.clear()
        self.era.addItem("— default —", None)
        for label in eras:
            self.era.addItem(label, label)
        self.era.setCurrentIndex(0)
        self.era.blockSignals(False)
        self.era.setVisible(bool(eras))
        self.era_label.setVisible(bool(eras))

    def _known_tempo(self):
        return self.known_spin.value() if self.known_check.isChecked() else None

    def _update_enabled(self):
        analysing = self._thread is not None
        self.analyze_btn.setEnabled(self._path is not None and not analysing)
        self.build_btn.setEnabled(self._result is not None and not analysing)
        self.known_spin.setEnabled(self.known_check.isChecked())

    # ----------------------------------------------------------- analysis
    def _start_analyze(self):
        if self._path is None or self._thread is not None:
            return
        self.busy.emit(True)
        self.status.emit("Analysing…")
        self._thread = QThread(self)
        self._worker = _AnalyzeWorker(self._c, self._path,
                                      self.align.currentText(), self._known_tempo())
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._update_enabled()
        self._thread.start()

    def _finish_thread(self):
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._worker.deleteLater()
            self._thread.deleteLater()
            self._thread = None
            self._worker = None
        self.busy.emit(False)
        self._update_enabled()

    def _on_done(self, result):
        self._result = result
        self._finish_thread()
        self._show_result(result)
        self.status.emit("Analysis complete.")

    def _on_failed(self, message):
        self._finish_thread()
        self.status.emit(f"Analysis failed: {message}")

    def _show_result(self, r):
        self.detected.setText(
            f"tempo {r.tempo:.0f}  ·  {r.duration:.1f}s  ·  align {r.alignment}"
            f"  ·  tempo-confidence {r.confidence.get('tempo', 0):.2f}")
        self.sections.clear()
        for sec, energy in zip(r.sections, r.segment_energy):
            flags = []
            if sec.get("crash_in"):
                flags.append("crash")
            if sec.get("fill_at_end"):
                flags.append("fill")
            tag = (" [" + ",".join(flags) + "]") if flags else ""
            self.sections.addItem(
                f"{sec['role']} · {sec['bars']} bars · energy {energy:.2f}{tag}")

    # -------------------------------------------------------------- build
    def _build(self):
        if self._result is None:
            return
        self._c.spec_from_analysis(self.profile.currentData(), result=self._result)
        era = self.era.currentData()
        if era:
            self._c.apply_era(era, keep_tempo=True)   # flavor + keep the analysed BPM
        self.specBuilt.emit()
        which = f" ({era})" if era else ""
        self.status.emit(f"Built drums to fit{which} — edit in Generate.")

    def shutdown(self):
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
