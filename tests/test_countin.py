"""Phase 8g count-in / click-track tests — preview-only click, offset bookkeeping,
and that export MIDI never carries the count-in (pytest-qt offscreen; render
monkeypatched to a known-size buffer)."""
import numpy as np
import mido

import engine
from app import playback
from app.controller import Controller


def test_click_track_shape_and_beats():
    buf = playback.click_track(4, 120, sample_rate=1000)   # 4 beats @ 120 = 2.0 s
    assert buf.shape == (2000, 2) and buf.dtype == np.float32
    assert np.any(buf[:60])                                 # a click at the head


def test_click_track_degenerate_inputs_no_crash():
    assert playback.click_track(0, 120, sample_rate=1000).shape == (1, 2)
    assert playback.click_track(4, 0, sample_rate=1000).shape == (1, 2)   # tempo 0


def _patch_render(monkeypatch, n=100):
    monkeypatch.setattr(playback, "render_events",
                        lambda events, **kw: np.zeros((n, 2), dtype=np.float32))


def test_render_preview_prepends_count_in(monkeypatch):
    _patch_render(monkeypatch, n=100)
    c = Controller(seed=1)
    c.song_from_profile("pop_punk")
    c.set_count_in(4)
    buf = c.render_preview(sample_rate=1000)
    tempo = c.spec["tempo"]
    click_len = int(round(4 * 60.0 / tempo * 1000))
    assert buf.shape[0] == click_len + 100                 # click prepended
    assert abs(c.preview_offset - 4 * 60.0 / tempo) < 1e-6


def test_no_count_in_offset_zero(monkeypatch):
    _patch_render(monkeypatch, n=100)
    c = Controller(seed=1)
    c.song_from_profile("pop_punk")
    buf = c.render_preview(sample_rate=1000)
    assert buf.shape[0] == 100 and c.preview_offset == 0.0


def test_export_has_no_count_in(tmp_path):
    # Count-in is preview-only; the exported .mid must be identical with/without it.
    c = Controller(seed=1)
    c.song_from_profile("pop_punk")
    a = c.export(tmp_path / "no.mid")
    c.set_count_in(4)
    b = c.export(tmp_path / "yes.mid")
    assert open(a, "rb").read() == open(b, "rb").read()     # export unaffected


def test_playhead_skips_count_in(qtbot, monkeypatch):
    from app.ui.generate_view import GenerateView
    _patch_render(monkeypatch, n=100)
    v = GenerateView(Controller(seed=1))
    qtbot.addWidget(v)
    v._c.song_from_profile("pop_punk")
    v.load_current_spec()
    v._c.set_count_in(4)
    v._c.render_preview(sample_rate=1000)
    off = v._c.preview_offset
    assert v._position_to_grid(off * 0.5) is v.LEAD_IN     # during count-in
    assert v._position_to_grid(off + 0.001) == (0, 0, 0)    # first musical step
