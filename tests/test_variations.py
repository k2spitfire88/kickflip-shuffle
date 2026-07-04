"""Phase 8h tests — batch variations + A/B: non-mutating variation renders, the
VariationsDialog worker, and the Keep -> adopt-seed flow (pytest-qt offscreen;
playback monkeypatched)."""
import numpy as np

import engine
from app.controller import Controller
from app.ui.variations import VariationsDialog
from app.ui.generate_view import GenerateView


def _patch_playback(monkeypatch):
    from app import playback
    monkeypatch.setattr(playback, "render_events",
                        lambda events, **kw: np.ones((50, 2), dtype=np.float32))

    class _P:
        def __init__(self):
            self.calls = []

        def load(self, *a):
            self.calls.append("load")

        def play(self):
            self.calls.append("play")

        def stop(self):
            self.calls.append("stop")

    p = _P()
    monkeypatch.setattr(playback, "Player", lambda: p)
    return p


# ------------------------------------------------------------- controller
def test_render_variation_does_not_mutate_held_state(monkeypatch):
    _patch_playback(monkeypatch)
    c = Controller(seed=7)
    c.song_from_profile("pop_punk")
    held_spec, held_seed = c.spec, c.seed
    buf = c.render_variation(123)
    assert buf.shape[1] == 2
    assert c.spec is held_spec and c.seed == held_seed        # untouched
    assert c._preview_buf is None                             # no held buffer set


def test_render_variation_seed_determines_output():
    c = Controller()
    c.build_spec_from_ui_state(
        "pop_punk", sections=[{"role": "verse", "bars": 2},
                              {"role": "chorus", "bars": 2}])
    # Different seeds -> (very likely) different events; same seed -> identical.
    a1 = engine.build_song(c.spec, seed=1)
    a1b = engine.build_song(c.spec, seed=1)
    a2 = engine.build_song(c.spec, seed=2)
    assert a1 == a1b and a1 != a2


# ------------------------------------------------------------------- dialog
def test_dialog_generates_and_keeps(qtbot, monkeypatch):
    _patch_playback(monkeypatch)
    c = Controller(seed=1)
    c.song_from_profile("pop_punk")
    dlg = VariationsDialog(c)
    qtbot.addWidget(dlg)
    dlg.count.setValue(3)
    dlg._generate()
    qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=3000)
    assert dlg.list.count() == 3
    assert dlg.keep_btn.isEnabled()

    kept = {}
    dlg.keepSeed.connect(lambda s: kept.setdefault("seed", s))
    dlg.list.setCurrentRow(1)
    expected = dlg._results[1][0]
    dlg._keep()
    assert kept["seed"] == expected


def test_dialog_play_uses_buffer(qtbot, monkeypatch):
    p = _patch_playback(monkeypatch)
    c = Controller(seed=1)
    c.song_from_profile("pop_punk")
    dlg = VariationsDialog(c)
    qtbot.addWidget(dlg)
    dlg._generate()
    qtbot.waitUntil(lambda: bool(dlg._results), timeout=3000)
    dlg.list.setCurrentRow(0)
    dlg._play()
    assert "play" in p.calls


def test_keep_variation_adopts_seed(qtbot, monkeypatch):
    _patch_playback(monkeypatch)
    v = GenerateView(Controller(seed=1))
    qtbot.addWidget(v)
    v._c.song_from_profile("pop_punk")
    v.load_current_spec()
    v._on_keep_variation(4242)
    assert v._c.seed == 4242


def test_dialog_close_is_safe(qtbot, monkeypatch):
    _patch_playback(monkeypatch)
    c = Controller(seed=1)
    c.song_from_profile("pop_punk")
    dlg = VariationsDialog(c)
    qtbot.addWidget(dlg)
    dlg.close()                                    # no active thread -> no crash
