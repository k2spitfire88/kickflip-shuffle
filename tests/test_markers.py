"""Phase 8d section-marker tests — compute_section_markers ticks/labels, marker
metas written on export, and the default (no-marker) write_midi path byte-identical."""
import mido

import engine
from app.controller import Controller
from engine.generate import STEPS


def _bar_ticks(ppq=480):
    return STEPS * (ppq // (STEPS // 4))


def test_markers_at_section_boundaries():
    spec = {
        "ppq": 480, "profile": "pop_punk", "tempo": 170, "overrides": {},
        "sections": [
            {"role": "intro", "bars": 2},
            {"groove": "skank", "bars": 4},
            {"role": "chorus", "bars": 2, "label": "BIG CHORUS"},
        ],
    }
    m = engine.compute_section_markers(spec)
    bt = _bar_ticks()
    assert [t for t, _ in m] == [0, 2 * bt, 6 * bt]
    assert [lbl for _, lbl in m] == ["intro", "skank", "BIG CHORUS"]   # label > role


def test_export_writes_marker_metas(tmp_path):
    c = Controller(seed=1)
    c.song_from_profile("pop_punk")
    out = c.export(tmp_path / "song.mid")
    mid = mido.MidiFile(out)
    markers = [msg.text for tr in mid.tracks for msg in tr
               if msg.type == "marker"]
    assert markers                                   # at least one section marker
    assert len(markers) == len(c.spec["sections"])


def test_write_midi_no_markers_byte_identical(tmp_path):
    spec = engine.song_from_profile("pop_punk")
    events = engine.build_song(spec, seed=42)
    a = engine.write_midi(events, str(tmp_path / "a.mid"), tempo=170)
    b = engine.write_midi(events, str(tmp_path / "b.mid"), tempo=170, markers=None)
    assert open(a, "rb").read() == open(b, "rb").read()   # default path unchanged
