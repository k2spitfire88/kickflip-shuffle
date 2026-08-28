"""Phase 9 UI tests — the transport-bar mix controls, worker plumbing (no
QWidget is ever read off the UI thread), the warning slot, and the drop view
attaching the analysed file as the context track.

Offscreen Qt; renders are monkeypatched, so no soundfont or audio device.
"""
import numpy as np
import pytest

from app import playback
from app.controller import Controller
from app.ui.generate_view import GenerateView, _RenderWorker


def _patch_render(monkeypatch, n=100):
    monkeypatch.setattr(playback, "render_events",
                        lambda events, **kw: np.full((n, 2), 0.5, dtype=np.float32))


def _view(qtbot, monkeypatch, *, with_track=False):
    _patch_render(monkeypatch)
    c = Controller(seed=1)
    v = GenerateView(c)
    qtbot.addWidget(v)
    c.song_from_profile("pop_punk")
    v.load_current_spec()
    if with_track:
        c.load_context_audio("fake.wav", sample_rate=44100,
                             buffer=np.full((44100, 2), 0.1, dtype=np.float32))
        v.context_audio_loaded()
    return v, c


# ---------------------------------------------------------------------------
# Enable-state (plan test 16)
# ---------------------------------------------------------------------------
def test_mix_controls_disabled_without_a_track(qtbot, monkeypatch):
    v, _ = _view(qtbot, monkeypatch)
    for w in (v.mix_chk, v.nudge, v.nudge_back, v.nudge_fwd,
              v.track_gain, v.drums_gain, v.align_export):
        assert not w.isEnabled()
    assert not v.mix_chk.isChecked()


def test_mix_controls_enabled_and_on_after_load(qtbot, monkeypatch):
    v, _ = _view(qtbot, monkeypatch, with_track=True)
    for w in (v.mix_chk, v.nudge, v.nudge_back, v.nudge_fwd,
              v.track_gain, v.drums_gain, v.align_export):
        assert w.isEnabled()
    assert v.mix_chk.isChecked()          # defaults ON with a track loaded
    assert v._mix_enabled()


def test_nudge_range_is_one_bar_at_the_current_tempo(qtbot, monkeypatch):
    v, c = _view(qtbot, monkeypatch, with_track=True)
    c._detected_tempo = 120.0             # one bar = 2000 ms
    v._sync_mix_controls()
    assert v.nudge.minimum() == -2000 and v.nudge.maximum() == 2000


# ---------------------------------------------------------------------------
# Controls are frozen during a render (plan test 17)
# ---------------------------------------------------------------------------
def test_new_widgets_are_disabled_during_a_render(qtbot, monkeypatch):
    v, _ = _view(qtbot, monkeypatch, with_track=True)
    v._set_controls_enabled(False)
    for w in (v.mix_chk, v.nudge, v.nudge_back, v.nudge_fwd, v.track_gain,
              v.drums_gain, v.align_export, v.count_in):
        assert not w.isEnabled(), w
    v._set_controls_enabled(True)
    assert v.mix_chk.isEnabled()


# ---------------------------------------------------------------------------
# Worker plumbing (plan test 18)
# ---------------------------------------------------------------------------
def test_start_render_passes_the_mix_flag_end_to_end(qtbot, monkeypatch):
    """Regression: `_mix_enabled()` reads the checkbox's ENABLED state, and
    `_start_render` disables the controls before building the worker — reading the
    flag after that made `with_context` permanently False, silently disabling the
    whole feature on the only path that reaches it."""
    v, c = _view(qtbot, monkeypatch, with_track=True)
    assert v._mix_enabled()

    built = {}
    import app.ui.generate_view as gv
    real = gv._RenderWorker

    def spy(controller, *, with_context=False):
        built["with_context"] = with_context
        return real(controller, with_context=with_context)

    monkeypatch.setattr(gv, "_RenderWorker", spy)
    v._start_render(target=None)
    qtbot.waitUntil(lambda: v._thread is None, timeout=3000)
    assert built["with_context"] is True


def test_start_render_is_refused_while_another_view_is_busy(qtbot, monkeypatch):
    v, c = _view(qtbot, monkeypatch, with_track=True)
    v.set_external_busy(True)
    v._start_render(target=None)
    assert v._thread is None                  # no render started


def test_external_busy_freezes_the_controls(qtbot, monkeypatch):
    """A drop-view analysis writes controller mix state from its own thread."""
    v, c = _view(qtbot, monkeypatch, with_track=True)
    v.set_external_busy(True)
    for w in (v.play_btn, v.mix_chk, v.nudge, v.regen_btn):
        assert not w.isEnabled(), w
    v.set_external_busy(False)
    assert v.play_btn.isEnabled() and v.mix_chk.isEnabled()


def test_render_worker_carries_the_mix_flag(monkeypatch):
    """The flag must reach render_preview through the worker's constructor —
    the worker must never read a widget."""
    seen = {}

    class _C:
        def render_preview(self, **kw):
            seen.update(kw)

    w = _RenderWorker(_C(), with_context=True)
    w.run()
    assert seen == {"with_context": True}


def test_variations_dialog_passes_the_flag(qtbot, monkeypatch):
    from app.ui.variations import VariationsDialog, _VariationsWorker
    v, c = _view(qtbot, monkeypatch, with_track=True)
    dlg = VariationsDialog(c, v, with_context=True)
    qtbot.addWidget(dlg)
    assert dlg._with_context is True

    seen = []

    class _C:
        def render_variation(self, seed, **kw):
            seen.append(kw)
            return np.zeros((4, 2), dtype=np.float32)

    snap = c.context_snapshot(sample_rate=44100)   # the rate the track loaded at
    worker = _VariationsWorker(_C(), [1, 2], sample_rate=44100, with_context=True,
                               context=snap)
    worker.run()
    assert all(kw["with_context"] is True for kw in seen)
    # The worker must hand over the SNAPSHOT, never let the controller read live
    # mix state from the worker thread.
    assert all(kw["context"] is snap for kw in seen)


# ---------------------------------------------------------------------------
# Warning slot (plan test 19)
# ---------------------------------------------------------------------------
def test_warning_label_hidden_when_clean(qtbot, monkeypatch):
    v, c = _view(qtbot, monkeypatch, with_track=True)
    c._detected_tempo = float(c.spec["tempo"])
    c._context_len_s = c._drums_length_s(c.spec)
    v._refresh_mix_warnings()
    assert not v.mix_warning.isVisible() and v.mix_warning.text() == ""


def test_warning_label_shows_drift(qtbot, monkeypatch):
    v, c = _view(qtbot, monkeypatch, with_track=True)
    c._detected_tempo = 170.0
    c.set_tempo(176.0)
    c._context_len_s = 240.0
    v._refresh_mix_warnings()
    assert v.mix_warning.text() != ""


def test_no_warnings_shown_when_mix_is_off(qtbot, monkeypatch):
    v, c = _view(qtbot, monkeypatch, with_track=True)
    c._detected_tempo = 170.0
    c.set_tempo(176.0)
    c._context_len_s = 240.0
    v.mix_chk.setChecked(False)
    v._refresh_mix_warnings()
    assert v.mix_warning.text() == ""


# ---------------------------------------------------------------------------
# Controls drive the controller
# ---------------------------------------------------------------------------
def test_nudge_spinbox_sets_the_controller(qtbot, monkeypatch):
    v, c = _view(qtbot, monkeypatch, with_track=True)
    v.nudge.setValue(-120)
    assert c.context_nudge_ms == -120
    assert c.context_offset_s == pytest.approx(-0.12)


def test_beat_buttons_step_one_beat(qtbot, monkeypatch):
    v, c = _view(qtbot, monkeypatch, with_track=True)
    c._detected_tempo = 120.0
    v._sync_mix_controls()
    v._on_nudge_beat(+1)
    assert c.context_nudge_ms == 500 and v.nudge.value() == 500


def test_gain_sliders_set_controller_and_prefs(qtbot, monkeypatch):
    v, c = _view(qtbot, monkeypatch, with_track=True)
    v.track_gain.setValue(50)
    v.drums_gain.setValue(120)
    assert c.mix_gains == {"drums": pytest.approx(1.2), "bed": pytest.approx(0.5)}
    assert v._prefs.mix_bed_gain() == pytest.approx(0.5)
    assert v._prefs.mix_drums_gain() == pytest.approx(1.2)


def test_prefs_gains_are_pushed_into_the_controller_at_startup(qtbot, monkeypatch):
    """Sliders and controller must not start out of sync."""
    _patch_render(monkeypatch)
    c = Controller(seed=1)
    v = GenerateView(c)
    qtbot.addWidget(v)
    v._prefs.set_mix_bed_gain(0.4)
    v._prefs.set_mix_drums_gain(1.1)
    v2 = GenerateView(Controller(seed=1), prefs=v._prefs)
    qtbot.addWidget(v2)
    assert v2._c.mix_gains == {"drums": pytest.approx(1.1), "bed": pytest.approx(0.4)}
    assert v2.track_gain.value() == 40 and v2.drums_gain.value() == 110


def test_align_export_checkbox_drives_the_controller(qtbot, monkeypatch):
    v, c = _view(qtbot, monkeypatch, with_track=True)
    assert c.align_export is True
    v.align_export.setChecked(False)
    assert c.align_export is False


# ---------------------------------------------------------------------------
# Drop view attaches the context track (plan test 20)
# ---------------------------------------------------------------------------
def test_analyze_worker_loads_context_on_the_worker_thread(monkeypatch):
    from app.ui.drop_view import _AnalyzeWorker
    calls = []

    class _C:
        def analyze_audio(self, path, **kw):
            calls.append(("analyze", path, kw.get("cut_to_click")))
            return "result"

        def load_context_audio(self, path):
            calls.append(("context", path))

    w = _AnalyzeWorker(_C(), "song.wav", "fixed_grid", None, cut_to_click=True)
    got = []
    w.done.connect(lambda r: got.append(r))
    w.run()
    assert calls == [("analyze", "song.wav", True), ("context", "song.wav")]
    assert got == ["result"]


def test_context_decode_failure_does_not_break_the_build(monkeypatch):
    from app.ui.drop_view import _AnalyzeWorker

    class _C:
        def analyze_audio(self, path, **kw):
            return "result"

        def load_context_audio(self, path):
            raise RuntimeError("no soundfile")

    w = _AnalyzeWorker(_C(), "song.wav", "fixed_grid", None)
    done, failed_ctx = [], []
    w.done.connect(lambda r: done.append(r))
    w.context_failed.connect(lambda m: failed_ctx.append(m))
    w.run()
    assert done == ["result"]                 # analysis still succeeds
    assert failed_ctx and "no soundfile" in failed_ctx[0]
