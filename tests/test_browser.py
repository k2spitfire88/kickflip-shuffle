"""Phase 5c groove-browser tests — engine usage map, controller preview/audition
(no held-state mutation), and the BrowserView UI (pytest-qt offscreen, playback
monkeypatched so no audio device/soundfont is touched)."""
import numpy as np

import engine
from app.controller import Controller
from app.ui.browser_view import BrowserView
from app.ui.main_window import MainWindow


# --------------------------------------------------------------- engine
def test_groove_usage_covers_all_and_no_orphans():
    u = engine.groove_usage()
    names = {g["name"] for g in engine.list_grooves()} | \
            {f["name"] for f in engine.list_fills()}
    assert set(u) == names
    orphans = [n for n, v in u.items() if not v["profiles"]]
    assert orphans == [], f"unexpected orphans: {orphans}"


def test_orphans_wired_to_barker_tre_cool_only():
    u = engine.groove_usage()
    assert set(u["half_time_shuffle"]["profiles"]) == {"barker", "tre_cool"}
    assert set(u["halfbar_toms"]["profiles"]) == {"barker", "tre_cool"}
    # Golden profiles must remain untouched by the orphan wiring.
    assert "half_time_shuffle" not in engine.PROFILES["pop_punk"]["bridge"]
    assert "halfbar_toms" not in engine.PROFILES["ramones"]["fills"]


def test_fills_carry_fill_role():
    u = engine.groove_usage()
    assert u["tom_descend"]["roles"] == ["fill"]


# ----------------------------------------------------------- controller
def test_preview_groove_no_spec_falls_back_without_mutation():
    c = Controller(seed=1)
    spec = c.preview_groove("half_time_shuffle")
    assert c.spec is None                       # not mutated
    assert spec["profile"] == "pop_punk"
    assert spec["sections"] == [{"groove": "half_time_shuffle", "bars": 2}]
    assert engine.build_song(spec, seed=1)      # renders


def test_preview_groove_flavored_by_current_profile():
    c = Controller(seed=1)
    c.song_from_profile("barker")
    spec = c.preview_groove("skank")
    assert spec["profile"] == "barker"
    assert spec["tempo"] == float(engine.PROFILES["barker"]["tempo"])


def test_preview_fill_builds_fill_section():
    c = Controller(seed=1)
    spec = c.preview_groove("halfbar_toms", kind="fill")
    sec = spec["sections"][0]
    assert sec["fill"] == "halfbar_toms" and sec["fill_at_end"] is True
    assert engine.build_song(spec, seed=1)


def test_audition_does_not_touch_held_spec_or_seed(monkeypatch):
    from app import playback
    monkeypatch.setattr(playback, "render_events",
                        lambda events, **kw: np.ones((10, 2), dtype=np.float32))
    c = Controller(seed=7)
    c.song_from_profile("pop_punk")
    held = c.spec
    c.audition(c.preview_groove("skank"))
    assert c.spec is held                        # same object, untouched
    assert c.seed == 7


# ------------------------------------------------------------------- UI
class _FakePlayer:
    def __init__(self):
        self.calls = []

    def load(self, buf, sr):
        self.calls.append("load")

    def play(self):
        self.calls.append("play")

    def stop(self):
        self.calls.append("stop")


def _patch_playback(monkeypatch):
    from app import playback
    monkeypatch.setattr(playback, "render_events",
                        lambda events, **kw: np.ones((100, 2), dtype=np.float32))
    fp = _FakePlayer()
    monkeypatch.setattr(playback, "Player", lambda: fp)
    return fp


def _browser(qtbot, controller=None):
    b = BrowserView(controller or Controller())
    qtbot.addWidget(b)
    return b


def _first_child(tree, kind):
    for i in range(tree.topLevelItemCount()):
        head = tree.topLevelItem(i)
        for j in range(head.childCount()):
            item = head.child(j)
            data = item.data(0, 0x0100)          # Qt.UserRole
            if data and data[1] == kind:
                return item
    return None


def test_browser_populates_all_rows(qtbot):
    b = _browser(qtbot)
    total = sum(b.tree.topLevelItem(i).childCount()
                for i in range(b.tree.topLevelItemCount()))
    assert total == len(b._c.list_grooves()) + len(b._c.list_fills())


def test_apply_buttons_disabled_without_section(qtbot):
    b = _browser(qtbot)
    b.tree.setCurrentItem(_first_child(b.tree, "groove"))
    assert not b.use_btn.isEnabled()             # no section live
    assert not b.fill_btn.isEnabled()


def test_apply_button_enable_matches_kind(qtbot):
    b = _browser(qtbot)
    b.set_apply_enabled(0)                        # a section is live
    b.tree.setCurrentItem(_first_child(b.tree, "groove"))
    assert b.use_btn.isEnabled() and not b.fill_btn.isEnabled()
    b.tree.setCurrentItem(_first_child(b.tree, "fill"))
    assert b.fill_btn.isEnabled() and not b.use_btn.isEnabled()


def test_use_groove_emits(qtbot):
    b = _browser(qtbot)
    b.set_apply_enabled(0)
    b.tree.setCurrentItem(_first_child(b.tree, "groove"))
    with qtbot.waitSignal(b.useGroove, timeout=1000) as sig:
        b.use_btn.click()
    assert sig.args[0] == b._current_name


def test_preview_play_renders_off_thread(qtbot, monkeypatch):
    fp = _patch_playback(monkeypatch)
    b = _browser(qtbot)
    b.tree.setCurrentItem(_first_child(b.tree, "groove"))
    b.play_btn.click()
    qtbot.waitUntil(lambda: "play" in fp.calls, timeout=3000)
    assert "load" in fp.calls


def test_browser_close_is_safe(qtbot):
    b = _browser(qtbot)
    b.close()                                    # no active thread -> no crash


# --------------------------------------------------- MainWindow wiring
def test_mainwindow_apply_routes_into_section(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.generate_view._c.song_from_profile("pop_punk")
    w.generate_view.load_current_spec()          # selects section 0
    # Route a groove through the browser signal -> generate current section.
    w.browser_view.useGroove.emit("half_time_shuffle")
    assert w._c.spec["sections"][0].get("groove") == "half_time_shuffle"
    assert "role" not in w._c.spec["sections"][0]   # role cleared
    assert w.rail.currentRow() == 0                 # switched back to Generate


def test_mode_switch_syncs_apply_state(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.generate_view._c.song_from_profile("pop_punk")
    w.generate_view.load_current_spec()
    w.rail.setCurrentRow(2)                          # Browser
    b = w.browser_view
    b.tree.setCurrentItem(_first_child(b.tree, "groove"))
    assert b.use_btn.isEnabled()                     # section synced on entry
