"""Phase 2 headless smoke test: the controller generates + exports a .mid with
no UI, the seed/determinism contract holds, and the output-map layer remaps
note numbers without disturbing rhythm/velocity/duration."""
import mido
import pytest

import engine
from app import Controller

# Seed verified to emit `tom_hi` (GM note 50) in the pop_punk default
# arrangement, so the GM->EZD3 remap test actually exercises the diff
# (GM and EZD3 currently differ only at tom_hi).
TOM_SEED = 42


def read_events(path):
    """Re-read a .mid into (tick, note, vel, dur) tuples, plus channels/tempo.

    write_midi emits split note_on/note_off with delta times (off sorted before
    on at the same tick); reconstruct durations by FIFO-pairing per pitch.
    """
    mid = mido.MidiFile(path)
    abs_t = 0
    opens = {}
    events, channels, tempo = [], set(), None
    for msg in mid.tracks[0]:
        abs_t += msg.time
        if msg.type == "set_tempo":
            tempo = msg.tempo
        elif msg.type == "note_on" and msg.velocity > 0:
            opens.setdefault(msg.note, []).append((abs_t, msg.velocity))
            channels.add(msg.channel)
        elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
            start, vel = opens[msg.note].pop(0)
            events.append((start, msg.note, vel, abs_t - start))
            channels.add(msg.channel)
    events.sort()
    return events, channels, tempo


# ---------------------------------------------------------------------------
# 1. generate
# ---------------------------------------------------------------------------
def test_generate_shape():
    c = Controller()
    c.song_from_profile("pop_punk")
    events = c.generate(seed=1)
    assert events, "no events generated"
    assert events == sorted(events, key=lambda e: e[0]), "events not tick-sorted"
    for e in events:
        assert len(e) == 4  # (tick, note, vel, dur)


def test_generate_requires_spec():
    with pytest.raises(ValueError):
        Controller().generate()


# ---------------------------------------------------------------------------
# 2. determinism — both the explicit and the seedless path
# ---------------------------------------------------------------------------
def test_determinism_explicit(tmp_path):
    c = Controller()
    c.song_from_profile("pop_punk")
    gen = c.generate(seed=7)
    out = c.export(str(tmp_path / "x.mid"), seed=7)
    exported, _, _ = read_events(out)
    # Compare as multisets: events sharing a tick have no defined intra-tick order.
    assert sorted(exported) == sorted(gen)


def test_determinism_seedless(tmp_path):
    """The path that actually breaks if the controller forwards None: generate
    with no seed, export with no seed -> the .mid must match the preview."""
    c = Controller()
    c.song_from_profile("pop_punk")
    gen = c.generate()                       # materialises + holds a concrete seed
    out = c.export(str(tmp_path / "y.mid"))   # reuses the held seed
    exported, _, _ = read_events(out)
    assert sorted(exported) == sorted(gen)


def test_export_does_not_overwrite_held_seed(tmp_path):
    c = Controller()
    c.song_from_profile("pop_punk")
    c.generate(seed=11)
    c.export(str(tmp_path / "z.mid"), seed=999)  # transient seed
    assert c.seed == 11


# ---------------------------------------------------------------------------
# 3. GM export is a valid, readable GM file at the right tempo on channel 9
# ---------------------------------------------------------------------------
def test_export_gm_valid(tmp_path):
    c = Controller()
    spec = c.song_from_profile("pop_punk")
    out = c.export(str(tmp_path / "gm.mid"), seed=TOM_SEED)
    events, channels, tempo = read_events(out)
    assert events
    assert channels == {9}, "drums must be on MIDI channel 9"
    assert set(n for _, n, _, _ in events) <= set(engine.GENERAL_MIDI.values())
    assert round(mido.tempo2bpm(tempo)) == spec["tempo"]


# ---------------------------------------------------------------------------
# 4. EZD3 export == GM export under the GM->EZD3 note remap (rhythm intact)
# ---------------------------------------------------------------------------
def test_export_ezd3_is_remap_of_gm(tmp_path):
    c = Controller()
    c.song_from_profile("pop_punk")
    gm = read_events(c.export(str(tmp_path / "gm.mid"),
                              output_map="GENERAL_MIDI", seed=TOM_SEED))[0]
    ez = read_events(c.export(str(tmp_path / "ez.mid"),
                              output_map="EZ_DRUMMER_3", seed=TOM_SEED))[0]

    # GM is injective, so GM-note -> EZD3-note is a well-defined remap. Remap
    # the GM export and compare as multisets — remapping a note changes its
    # intra-tick sort position, so a positional zip could misalign.
    remap = {engine.GENERAL_MIDI[r]: engine.EZ_DRUMMER_3[r] for r in engine.ROLES}
    assert len(gm) == len(ez)
    gm_remapped = sorted((t, remap[n], v, d) for (t, n, v, d) in gm)
    assert gm_remapped == sorted(ez)

    # Guard against a vacuous pass: the diff must actually be exercised.
    diff_notes = {r for r in engine.ROLES
                  if engine.GENERAL_MIDI[r] != engine.EZ_DRUMMER_3[r]}
    gm_notes = {n for _, n, _, _ in gm}
    assert any(engine.GENERAL_MIDI[r] in gm_notes for r in diff_notes), \
        "seed did not emit any role where GM and EZD3 differ — test is vacuous"


def test_export_uses_held_output_map(tmp_path):
    """A kwarg-less export resolves the note map via the held selection."""
    c = Controller()
    c.song_from_profile("pop_punk")
    c.set_output_map("EZ_DRUMMER_3")
    held = read_events(c.export(str(tmp_path / "held.mid"), seed=TOM_SEED))[0]
    explicit = read_events(c.export(str(tmp_path / "exp.mid"),
                                    output_map="EZ_DRUMMER_3", seed=TOM_SEED))[0]
    assert sorted(held) == sorted(explicit)


def test_generate_always_previews_general_midi(tmp_path):
    """generate ignores the selected output map — preview is the GM stand-in."""
    c = Controller()
    c.song_from_profile("pop_punk")
    c.set_output_map("EZ_DRUMMER_3")
    notes = {n for _, n, _, _ in c.generate(seed=TOM_SEED)}
    assert notes <= set(engine.GENERAL_MIDI.values())
    assert 50 in notes  # GM tom_hi (EZD3 would emit 48); seed emits tom_hi


def test_write_note_ladder_uses_held_map(tmp_path):
    c = Controller()
    c.set_output_map("EZ_DRUMMER_3")
    out = c.write_note_ladder(str(tmp_path / "ladder.mid"))
    notes = [n for _, n, _, _ in read_events(out)[0]]
    assert notes == [engine.EZ_DRUMMER_3[r] for r in engine.ROLES]


# ---------------------------------------------------------------------------
# 5. build_spec_from_ui_state -> engine-valid spec; per-section axes honoured
# ---------------------------------------------------------------------------
def test_build_spec_from_ui_state_valid():
    c = Controller()
    spec = c.build_spec_from_ui_state(
        "pop_punk", axes={"ghost": 0.5}, tempo=180,
        sections=[{"groove": "verse_basic", "bars": 2},
                  {"groove": "verse_basic", "bars": 2}])
    assert spec["tempo"] == 180
    assert spec["overrides"] == {"ghost": 0.5}
    assert engine.build_song(spec, seed=1)  # engine accepts it
    assert c.spec is spec


def test_build_spec_unknown_profile():
    with pytest.raises(ValueError):
        Controller().build_spec_from_ui_state("not_a_profile")


def test_per_section_axes_change_rows():
    """A per-section axis override must change that section's resolved rows."""
    c = Controller()
    base_sec = {"groove": "verse_basic", "bars": 1}
    plain = c.build_spec_from_ui_state("pop_punk", sections=[dict(base_sec)])
    rows_plain = c.resolved_bar(0, 0, spec=plain, seed=3)
    loud = c.build_spec_from_ui_state(
        "pop_punk",
        sections=[{**base_sec, "axes": {"double_bass": 1.0}}])
    rows_loud = c.resolved_bar(0, 0, spec=loud, seed=3)
    assert rows_plain != rows_loud, "per-section axes had no effect on rows"


# ---------------------------------------------------------------------------
# 6. future-phase stubs
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("call", [
    lambda c: c.render_preview(),
    lambda c: c.analyze_audio("x.wav"),
    lambda c: c.play(),
    lambda c: c.stop(),
])
def test_future_stubs_raise(call):
    with pytest.raises(NotImplementedError):
        call(Controller())


# ---------------------------------------------------------------------------
# 7. seed accessors + spec property
# ---------------------------------------------------------------------------
def test_seed_accessors():
    c = Controller()
    assert c.seed is None
    assert c.set_seed(5) == 5 and c.seed == 5
    n = c.new_seed()
    assert isinstance(n, int) and c.seed == n
    c.song_from_profile("pop_punk")
    c.set_seed(8)
    assert c.generate() == c.generate()  # held seed -> reproducible


def test_spec_property_tracks_current():
    c = Controller()
    assert c.spec is None
    s = c.song_from_profile("ramones")
    assert c.spec is s
