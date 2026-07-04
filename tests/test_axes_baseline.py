"""Section-editor axis sliders show the inherited profile baseline (barker high
ghost, mxpx low) and only write a per-section override when moved off it."""
import engine
from app.controller import Controller
from app.ui.editor_widgets import SectionEditor


def test_global_axes_reflect_profile():
    c = Controller()
    c.song_from_profile("barker")
    assert c.global_axes()["ghost"] == 1.0            # barker maxes ghost
    c.song_from_profile("mxpx")
    assert c.global_axes()["ghost"] == 0.2


def test_sliders_start_at_profile_baseline(qtbot):
    c = Controller()
    c.song_from_profile("barker")
    ed = SectionEditor(c)
    qtbot.addWidget(ed)
    ed.load(0)
    assert ed.sliders["ghost"].value() == 100         # inherited from profile
    assert ed.sliders["ornament"].value() == 100

    c2 = Controller()
    c2.song_from_profile("mxpx")
    ed2 = SectionEditor(c2)
    qtbot.addWidget(ed2)
    ed2.load(0)
    assert ed2.sliders["ghost"].value() == 20


def test_unchanged_axes_stay_inherited(qtbot):
    c = Controller()
    c.song_from_profile("barker")
    ed = SectionEditor(c)
    qtbot.addWidget(ed)
    ed.load(0)
    ed._commit()                                      # touch nothing
    assert c.spec["sections"][0].get("axes") is None  # not bloated, still inherits


def test_moved_axis_writes_only_that_override(qtbot):
    c = Controller()
    c.song_from_profile("barker")
    ed = SectionEditor(c)
    qtbot.addWidget(ed)
    ed.load(0)
    ed.sliders["ghost"].setValue(30)                  # move ghost off baseline
    axes = c.spec["sections"][0]["axes"]
    assert axes == {"ghost": 0.3}                     # only the changed axis


def test_override_persists_on_reload(qtbot):
    c = Controller()
    c.song_from_profile("barker")
    ed = SectionEditor(c)
    qtbot.addWidget(ed)
    ed.load(0)
    ed.sliders["double_bass"].setValue(50)
    ed.load(0)                                        # reload same section
    assert ed.sliders["double_bass"].value() == 50    # override shown back
    assert ed.sliders["ghost"].value() == 100         # others still inherited
