"""Section preview — play_section slices the exact section out of the full render
so auditioning a section matches what plays in context (pytest-qt offscreen)."""
import numpy as np

import engine
from engine.generate import STEPS
from app.controller import Controller


class _FakePlayer:
    def __init__(self):
        self.loaded = None
        self.calls = []

    def load(self, buf, sr):
        self.loaded = (np.asarray(buf), sr)
        self.calls.append("load")

    def play(self):
        self.calls.append("play")

    def stop(self):
        self.calls.append("stop")


def _patch(monkeypatch, n_per_sample=None):
    from app import playback

    # A render whose samples encode their own index, so a slice is verifiable.
    def fake_render(events, *, tempo, ppq, sample_rate=44100, **kw):
        # length = last event tick -> seconds -> samples + small tail
        last = max((t + d for t, _n, _v, d in events), default=0)
        secs = last * 60.0 / (tempo * ppq)
        n = int(round(secs * sample_rate)) + 10
        idx = np.arange(n, dtype=np.float32)
        return np.stack([idx, idx], axis=1)

    monkeypatch.setattr(playback, "render_events", fake_render)
    fp = _FakePlayer()
    monkeypatch.setattr(playback, "Player", lambda: fp)
    return fp


def test_play_section_slices_matching_range(qtbot, monkeypatch):
    fp = _patch(monkeypatch)
    c = Controller(seed=1)
    c.build_spec_from_ui_state(
        "pop_punk", sections=[{"groove": "verse_basic", "bars": 2},
                              {"groove": "skank", "bars": 2},
                              {"groove": "halftime", "bars": 2}])
    sr = 22050
    c.render_preview(sample_rate=sr)
    # Expected section-1 sample range from the markers.
    markers = engine.compute_section_markers(c.spec)
    tempo, ppq = c.spec["tempo"], c.spec["ppq"]
    spt = 60.0 / (tempo * ppq)
    start = int(round(markers[1][0] * spt * sr))
    end = int(round(markers[2][0] * spt * sr))

    c.play_section(1)
    buf, got_sr = fp.loaded
    assert got_sr == sr
    # The fake render encodes sample index as value -> slice must start at `start`.
    assert abs(float(buf[0, 0]) - start) < 2
    assert abs(buf.shape[0] - (end - start)) < 2
    assert abs(c.play_base - markers[1][0] * spt) < 1e-6


def test_play_section_requires_preview(monkeypatch):
    _patch(monkeypatch)
    c = Controller(seed=1)
    c.song_from_profile("pop_punk")
    import pytest
    with pytest.raises(ValueError):
        c.play_section(0)                    # nothing rendered yet


def test_last_section_runs_to_end_with_tail(qtbot, monkeypatch):
    fp = _patch(monkeypatch)
    c = Controller(seed=1)
    c.build_spec_from_ui_state(
        "pop_punk", sections=[{"groove": "verse_basic", "bars": 2},
                              {"groove": "skank", "bars": 2}])
    c.render_preview(sample_rate=22050)
    total = c._preview_buf.shape[0]
    c.play_section(1)                        # last section
    buf, _sr = fp.loaded
    assert abs((float(buf[0, 0]) + buf.shape[0]) - total) < 2   # runs to buffer end


def test_full_play_resets_base(qtbot, monkeypatch):
    _patch(monkeypatch)
    c = Controller(seed=1)
    c.build_spec_from_ui_state(
        "pop_punk", sections=[{"groove": "verse_basic", "bars": 2},
                              {"groove": "skank", "bars": 2}])
    c.render_preview(sample_rate=22050)
    c.play_section(1)
    assert c.play_base > 0
    c.play()
    assert c.play_base == 0.0                # full song rebased to 0


def test_generate_view_play_section_wires(qtbot, monkeypatch):
    from app.ui.generate_view import GenerateView
    _patch(monkeypatch)
    v = GenerateView(Controller(seed=1))
    qtbot.addWidget(v)
    v._c.song_from_profile("pop_punk")
    v.load_current_spec()
    v.timeline.list.setCurrentRow(2)
    v.play_btn.click()                       # Play now previews the selected section
    qtbot.waitUntil(lambda: v._thread is None and v._c._preview_buf is not None,
                    timeout=3000)            # render fully finished
    assert v._play_target == 2               # targeted the selected section
    v.play_all_btn.click()                   # Play Song = whole arrangement
    qtbot.waitUntil(lambda: v._thread is None, timeout=3000)
    assert v._play_target is None
