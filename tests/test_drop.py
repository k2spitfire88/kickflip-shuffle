"""Phase 5b Drop-audio tests — pytest-qt offscreen. controller.analyze_audio is
monkeypatched to a fast fake (real librosa is covered by test_analyze.py); the
fake has 2 sections (!= the 7-section profile default) so assertions can't pass
vacuously."""
from PySide6.QtCore import QUrl

from app.controller import Controller
from app import analyze
from app.ui.drop_view import DropView, _is_audio_url
from app.ui.main_window import MainWindow


def _fake_result():
    return analyze.AnalysisResult(
        tempo=150.0, sr=22050, duration=6.0, alignment="fixed_grid",
        beat_times=[], downbeat_times=[],
        segments=[(0.0, 3.0), (3.0, 6.0)], segment_energy=[0.2, 0.8],
        sections=[{"role": "verse", "bars": 4, "fill_at_end": True},
                  {"role": "chorus", "bars": 4, "crash_in": True}],
        confidence={"tempo": 0.5, "segmentation": "structural"})


def _drop(qtbot, controller=None):
    d = DropView(controller or Controller())
    qtbot.addWidget(d)
    return d


def test_is_audio_url():
    assert _is_audio_url(QUrl.fromLocalFile("/a/song.wav"))
    assert _is_audio_url(QUrl.fromLocalFile("/a/song.MP3"))
    assert not _is_audio_url(QUrl.fromLocalFile("/a/notes.txt"))


def test_analyze_populates_readout(qtbot, monkeypatch):
    d = _drop(qtbot)
    monkeypatch.setattr(d._c, "analyze_audio", lambda path, **kw: _fake_result())
    d.load_file("song.wav")
    assert d.analyze_btn.isEnabled()
    d._start_analyze()
    qtbot.waitUntil(lambda: d._result is not None, timeout=3000)
    assert d.sections.count() == 2
    assert d.build_btn.isEnabled()
    assert "150" in d.detected.text()


def test_build_with_era_flavors_and_keeps_tempo(qtbot, monkeypatch):
    d = _drop(qtbot)
    monkeypatch.setattr(d._c, "analyze_audio", lambda path, **kw: _fake_result())
    d.load_file("song.wav")
    d._start_analyze()
    qtbot.waitUntil(lambda: d._result is not None, timeout=3000)
    # Pick an era-capable drummer, then an era.
    d.profile.setCurrentIndex(d.profile.findData("relient_k"))
    assert not d.era.isHidden()                              # era combo shown
    d.era.setCurrentIndex(d.era.findData("Mmhmm–Five Score (04–07) — Douglas"))
    d._build()
    spec = d._c.spec
    assert spec["era"] == "Mmhmm–Five Score (04–07) — Douglas"
    assert spec["tempo"] == 150.0                            # analysed BPM kept
    assert "tempo_range" not in spec                         # pinned


def test_era_hidden_for_flat_drop_profile(qtbot):
    d = _drop(qtbot)
    d.profile.setCurrentIndex(d.profile.findData("pop_punk"))
    assert d.era.isHidden()


def test_inputs_passed_through(qtbot, monkeypatch):
    calls = {}

    def spy(path, **kw):
        calls.update(kw)
        calls["path"] = path
        return _fake_result()

    d = _drop(qtbot)
    monkeypatch.setattr(d._c, "analyze_audio", spy)
    d.load_file("song.wav")
    d.known_check.setChecked(True)
    d.known_spin.setValue(140)
    d.align.setCurrentText("follow_beats")
    d._start_analyze()
    qtbot.waitUntil(lambda: d._result is not None, timeout=3000)
    assert calls["known_tempo"] == 140
    assert calls["alignment"] == "follow_beats"


def test_cut_to_click_gating(qtbot):
    d = _drop(qtbot)
    d.cut_click.setChecked(True)
    assert d.known_check.isChecked() and not d.known_check.isEnabled()
    assert d.align.currentText() == "fixed_grid" and not d.align.isEnabled()


def test_build_uses_captured_result(qtbot, monkeypatch):
    d = _drop(qtbot)
    # Fake analyze does NOT set controller._analysis -> Build must use the captured
    # result, not the held field.
    monkeypatch.setattr(d._c, "analyze_audio", lambda path, **kw: _fake_result())
    built = []
    d.specBuilt.connect(lambda: built.append(True))
    d.load_file("song.wav")
    d._start_analyze()
    qtbot.waitUntil(lambda: d._result is not None, timeout=3000)
    d.profile.setCurrentIndex(0)
    d._build()
    assert built and len(d._c.spec["sections"]) == 2
    assert d._c.analysis is None                    # held field never set by fake


def test_analyze_error_surfaced(qtbot, monkeypatch):
    def boom(path, **kw):
        raise RuntimeError("bad audio")

    d = _drop(qtbot)
    monkeypatch.setattr(d._c, "analyze_audio", boom)
    msgs = []
    d.status.connect(msgs.append)
    d.load_file("song.wav")
    d._start_analyze()
    qtbot.waitUntil(lambda: any("failed" in m for m in msgs), timeout=3000)
    assert d.analyze_btn.isEnabled()                # inputs re-enabled after failure


def test_mainwindow_drop_build_switches_to_generate(qtbot, monkeypatch):
    w = MainWindow(Controller())
    qtbot.addWidget(w)
    monkeypatch.setattr(w._c, "analyze_audio", lambda path, **kw: _fake_result())
    w.rail.setCurrentRow(1)                          # Drop mode
    assert w.stack.currentWidget() is w.drop_view
    w.drop_view.load_file("song.wav")
    w.drop_view._start_analyze()
    qtbot.waitUntil(lambda: w.drop_view._result is not None, timeout=3000)
    w.drop_view._build()
    assert w.rail.currentRow() == 0                  # switched back to Generate
    assert len(w._c.spec["sections"]) == 2           # analysed arrangement kept
    assert not w.generate_view.editor_panel.isHidden()


def test_load_current_spec_keeps_sections(qtbot):
    w = MainWindow(Controller())
    qtbot.addWidget(w)
    w._c.build_spec_from_ui_state(
        "pop_punk", sections=[{"role": "verse", "bars": 2},
                              {"role": "chorus", "bars": 2, "crash_in": True}])
    w.generate_view.load_current_spec()
    assert w.generate_view.timeline.list.count() == 2   # not the 7-section default
    assert not w.generate_view.editor_panel.isHidden()
    assert w._c.spec["profile"] == "pop_punk"


def test_mainwindow_close_is_safe(qtbot):
    w = MainWindow(Controller())
    qtbot.addWidget(w)
    w.close()                                        # no running threads -> no crash
