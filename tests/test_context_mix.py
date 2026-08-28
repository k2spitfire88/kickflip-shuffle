"""Phase 9 context-mix tests — alignment offset bookkeeping, the count-in
overlay, section slicing over a mixed buffer, sample-rate guarding, aligned
export, warnings, and .ppd persistence.

`render_events` is monkeypatched to a known-size buffer throughout (the 142MB
sf2 is gitignored), so these run without audio hardware or the soundfont.
"""
import json

import numpy as np
import mido
import pytest

import engine
from app import playback
from app.controller import Controller


def _patch_render(monkeypatch, n=100, level=0.5):
    """Drums = a constant non-zero buffer, so padding is visible as silence."""
    monkeypatch.setattr(
        playback, "render_events",
        lambda events, **kw: np.full((n, 2), level, dtype=np.float32))


def _bed(n=1000, level=0.1):
    return np.full((n, 2), level, dtype=np.float32)


def _ctl(monkeypatch, *, n=100, bed_n=1000, sr=1000, offset=0.0, profile="pop_punk"):
    _patch_render(monkeypatch, n=n)
    c = Controller(seed=1)
    c.song_from_profile(profile)
    c.load_context_audio("fake.wav", sample_rate=sr, buffer=_bed(bed_n))
    c._auto_offset_s = offset
    return c


# ---------------------------------------------------------------------------
# Offset bookkeeping (plan test 8) — preview_offset is NEVER negative
# ---------------------------------------------------------------------------
def test_preview_offset_positive_offset(monkeypatch):
    c = _ctl(monkeypatch, offset=0.25, sr=1000)
    buf = c.render_preview(sample_rate=1000, with_context=True)
    assert c.preview_offset == pytest.approx(0.25)
    assert not buf[:250].any() or np.all(np.abs(buf[:250]) <= 0.1 + 1e-6)
    # drums (0.5) only start after the 250-frame pad
    assert float(np.max(np.abs(buf[:250]))) < 0.5
    assert float(np.max(np.abs(buf[250:350]))) > 0.1


def test_preview_offset_never_negative(monkeypatch):
    """A negative nudge pads the BED, not the drums — the offset stays >= 0.
    A negative preview_offset would make play_section slice buf[-N:end]."""
    c = _ctl(monkeypatch, offset=0.0, sr=1000)
    c.set_context_nudge(-100)                       # drums 0.1s EARLIER than the bed
    buf = c.render_preview(sample_rate=1000, with_context=True)
    assert c.context_offset_s == pytest.approx(-0.1)
    assert c.preview_offset == 0.0                  # never negative
    assert float(np.max(np.abs(buf[:100]))) == pytest.approx(0.5)   # drums at frame 0
    assert len(buf) == 1100                         # bed pushed back by 100 frames


def test_preview_offset_zero_offset(monkeypatch):
    c = _ctl(monkeypatch, offset=0.0, sr=1000)
    c.render_preview(sample_rate=1000, with_context=True)
    assert c.preview_offset == 0.0


# ---------------------------------------------------------------------------
# Count-in overlay (plan test 9)
# ---------------------------------------------------------------------------
def test_count_in_overlays_lead_in_without_shifting(monkeypatch):
    """With enough lead-in the click lays OVER the track — nothing shifts."""
    c = _ctl(monkeypatch, offset=4.0, sr=1000, bed_n=8000)
    c._detected_tempo = 120.0                       # 4 beats = 2.0 s <= 4.0 s lead-in
    c.set_count_in(4)
    # A recognisable stand-in click: the real one's 1 kHz tone aliases to DC at
    # this test's 1 kHz sample rate (a test-rate artifact, not a render bug).
    monkeypatch.setattr(playback, "click_track",
                        lambda beats, tempo, **kw: np.full((2000, 2), 0.3,
                                                           dtype=np.float32))
    buf = c.render_preview(sample_rate=1000, with_context=True)
    assert c.preview_offset == pytest.approx(4.0)   # NOT 4.0 + click length
    assert len(buf) == 8000                         # buffer length unchanged
    # click sits in the 2 s before the downbeat, summed on top of the bed
    assert float(np.max(np.abs(buf[2000:4000]))) == pytest.approx(0.3 + 0.08)
    assert float(np.max(np.abs(buf[:2000]))) == pytest.approx(0.08)   # bed only


def test_count_in_short_lead_in_front_pads(monkeypatch):
    """Lead-in shorter than the count-in: front-pad by the deficit so the click
    stays complete, and preview_offset absorbs it."""
    c = _ctl(monkeypatch, offset=0.5, sr=1000, bed_n=8000)
    c._detected_tempo = 120.0                       # need 2.0 s, have 0.5 s
    c.set_count_in(4)
    c.render_preview(sample_rate=1000, with_context=True)
    assert c.preview_offset == pytest.approx(0.5 + 1.5)   # offset + deficit


def test_count_in_dry_path_unchanged(monkeypatch):
    """No context track -> the original prepend path, byte-identical."""
    _patch_render(monkeypatch, n=100)
    c = Controller(seed=1)
    c.song_from_profile("pop_punk")
    c.set_count_in(4)
    dry = c.render_preview(sample_rate=1000)
    tempo = c.spec["tempo"]
    assert dry.shape[0] == int(round(4 * 60.0 / tempo * 1000)) + 100
    assert c.preview_offset == pytest.approx(4 * 60.0 / tempo)


# ---------------------------------------------------------------------------
# play_section over a mixed buffer (plan test 10)
# ---------------------------------------------------------------------------
def test_play_section_last_stops_at_drums_not_track(monkeypatch):
    """The last section must not audition the rest of the backing track."""
    c = _ctl(monkeypatch, n=100, bed_n=100_000, sr=1000, offset=0.0)
    played = {}
    monkeypatch.setattr(playback, "Player",
                        lambda *a, **k: _FakePlayer(played))
    c.render_preview(sample_rate=1000, with_context=True)
    assert len(c._preview_buf) == 100_000            # the whole track is in there
    last = len(c.spec["sections"]) - 1
    c.play_section(last)
    spec = c.spec
    sec_per_tick = 60.0 / (spec["tempo"] * spec.get("ppq", 480))
    drums_end = engine.song_ticks(spec) * sec_per_tick + playback.RENDER_TAIL_S
    assert len(played["buf"]) <= int(round(drums_end * 1000)) + 1
    assert len(played["buf"]) < 100_000              # not the whole track


def test_play_section_twice_slices_the_same(monkeypatch):
    """play_section must not mutate the held buffer's offset — a second call on
    the same buffer has to slice identically."""
    c = _ctl(monkeypatch, n=100, bed_n=5000, sr=1000, offset=1.0)
    played = {}
    monkeypatch.setattr(playback, "Player", lambda *a, **k: _FakePlayer(played))
    c.render_preview(sample_rate=1000, with_context=True)
    c.play_section(0)
    first = np.array(played["buf"], copy=True)
    c.play_section(0)
    assert np.array_equal(first, played["buf"])
    assert c.preview_offset == pytest.approx(1.0)    # still describes the buffer
    assert c.playhead_offset == 0.0                  # the slice itself has no head


class _FakePlayer:
    def __init__(self, sink):
        self._sink = sink

    def load(self, buf, sr):
        self._sink["buf"] = buf
        self._sink["sr"] = sr

    def play(self):
        self._sink["played"] = True

    def stop(self):
        pass


# ---------------------------------------------------------------------------
# Sample-rate guard (plan test 11)
# ---------------------------------------------------------------------------
def test_sample_rate_mismatch_reloads_context(monkeypatch):
    c = _ctl(monkeypatch, n=100, bed_n=1000, sr=44100, offset=0.0)
    calls = []

    def fake_load(path, *, sample_rate=44100):
        calls.append(sample_rate)
        return _bed(2000)

    monkeypatch.setattr(playback, "load_audio", fake_load)
    c.render_preview(sample_rate=1000, with_context=True)
    assert calls == [1000]                           # re-decoded at the render rate
    assert c._context_sr == 1000


def test_sample_rate_mismatch_without_path_raises(monkeypatch):
    c = _ctl(monkeypatch, n=100, bed_n=1000, sr=44100, offset=0.0)
    c._context_path = None
    with pytest.raises(ValueError, match="sample rate|Hz"):
        c.render_preview(sample_rate=1000, with_context=True)


# ---------------------------------------------------------------------------
# Aligned export (plan test 12)
# ---------------------------------------------------------------------------
def _first_note_tick(path):
    mid = mido.MidiFile(path)
    for track in mid.tracks:
        t = 0
        for msg in track:
            t += msg.time
            if msg.type == "note_on":
                return t
    return None


def test_aligned_export_shifts_every_event(tmp_path, monkeypatch):
    c = _ctl(monkeypatch, offset=1.0, sr=1000)
    spec = c.spec
    ppq, tempo = spec.get("ppq", 480), float(spec["tempo"])
    plain = c.export(tmp_path / "plain.mid", align=False)
    aligned = c.export(tmp_path / "aligned.mid", align=True)
    shift = int(round(1.0 * ppq * tempo / 60.0))
    assert _first_note_tick(aligned) - _first_note_tick(plain) == shift


def test_unaligned_export_byte_identical(tmp_path, monkeypatch):
    """With alignment off — or no context track — export must not change."""
    c = Controller(seed=1)
    c.song_from_profile("pop_punk")
    a = c.export(tmp_path / "a.mid")                 # no context loaded at all
    c.load_context_audio("fake.wav", sample_rate=1000, buffer=_bed(1000))
    c._auto_offset_s = 1.0
    b = c.export(tmp_path / "b.mid", align=False)
    assert open(a, "rb").read() == open(b, "rb").read()


def test_export_alignment_defaults_to_held_flag(tmp_path, monkeypatch):
    c = _ctl(monkeypatch, offset=1.0, sr=1000)
    assert c.align_export is True                    # default ON with a track
    on = c.export(tmp_path / "on.mid")
    c.set_align_export(False)
    off = c.export(tmp_path / "off.mid")
    assert _first_note_tick(on) > _first_note_tick(off)


def test_negative_alignment_does_not_shift_export(tmp_path, monkeypatch):
    """Drums starting before the file cannot be expressed as padding."""
    c = _ctl(monkeypatch, offset=0.0, sr=1000)
    c.set_context_nudge(-200)
    plain = c.export(tmp_path / "p.mid", align=False)
    aligned = c.export(tmp_path / "a.mid", align=True)
    assert open(plain, "rb").read() == open(aligned, "rb").read()


# ---------------------------------------------------------------------------
# Warnings (plan test 13)
# ---------------------------------------------------------------------------
def test_no_warnings_right_after_build(monkeypatch):
    c = _ctl(monkeypatch, offset=0.0, sr=1000, bed_n=1000)
    c._detected_tempo = c.spec["tempo"]
    # Drums length ~= track length -> no length warning either.
    c._context_len_s = c._drums_length_s(c.spec)
    assert c.mix_warnings == []


def test_tempo_drift_warning(monkeypatch):
    c = _ctl(monkeypatch, offset=0.0, sr=1000)
    c._detected_tempo = 170.0
    c._context_len_s = 240.0                         # 4 minutes
    c.set_tempo(172.0)                               # ~2.8 s drift over the track
    c._context_len_s = 240.0
    assert any("drift" in w.lower() for w in c.mix_warnings)


def test_no_tempo_drift_warning_over_a_short_track(monkeypatch):
    c = _ctl(monkeypatch, offset=0.0, sr=1000)
    c._detected_tempo = float(c.spec["tempo"])
    c.set_tempo(c._detected_tempo + 0.2)             # tiny error, short track
    c._context_len_s = c._drums_length_s(c.spec)
    assert not any("drift" in w.lower() for w in c.mix_warnings)


def test_length_mismatch_warning(monkeypatch):
    c = _ctl(monkeypatch, offset=0.0, sr=1000)
    c._detected_tempo = float(c.spec["tempo"])
    c._context_len_s = c._drums_length_s(c.spec) + 60.0    # a minute longer
    assert any("length" in w.lower() for w in c.mix_warnings)


def test_no_warnings_without_context(monkeypatch):
    _patch_render(monkeypatch)
    c = Controller(seed=1)
    c.song_from_profile("pop_punk")
    assert c.mix_warnings == []


# ---------------------------------------------------------------------------
# Persistence (plan test 14)
# ---------------------------------------------------------------------------
def test_ppd_round_trips_context_block(tmp_path, monkeypatch):
    c = _ctl(monkeypatch, offset=1.25, sr=1000)
    c.set_context_nudge(-40)
    c._detected_tempo = 168.0
    p = c.save_project(tmp_path / "proj.ppd")

    monkeypatch.setattr(playback, "load_audio",
                        lambda path, *, sample_rate=44100: _bed(1000))
    c2 = Controller()
    out = c2.load_project(p)
    assert out["warnings"] == []
    assert c2.has_context_audio
    assert c2._auto_offset_s == pytest.approx(1.25)   # NOT just the nudge
    assert c2.context_nudge_ms == -40
    assert c2.context_offset_s == pytest.approx(1.21)
    assert c2._detected_tempo == 168.0


def test_ppd_missing_audio_warns_not_raises(tmp_path, monkeypatch):
    c = _ctl(monkeypatch, offset=1.0, sr=1000)
    p = c.save_project(tmp_path / "proj.ppd")

    def boom(path, *, sample_rate=44100):
        raise FileNotFoundError(path)

    monkeypatch.setattr(playback, "load_audio", boom)
    c2 = Controller()
    out = c2.load_project(p)                          # must NOT raise
    assert any("context audio" in w for w in out["warnings"])
    assert not c2.has_context_audio
    assert c2.spec is not None                        # the project still loaded


def test_old_ppd_without_block_still_loads(tmp_path, monkeypatch):
    _patch_render(monkeypatch)
    c = Controller(seed=1)
    c.song_from_profile("pop_punk")
    p = c.save_project(tmp_path / "old.ppd")
    data = json.load(open(p))
    assert "context_audio" not in data                # nothing added without a track
    c2 = Controller()
    out = c2.load_project(p)
    assert out["warnings"] == [] and not c2.has_context_audio


def test_loading_a_project_clears_a_previous_context(tmp_path, monkeypatch):
    _patch_render(monkeypatch)
    plain = Controller(seed=1)
    plain.song_from_profile("pop_punk")
    p = plain.save_project(tmp_path / "plain.ppd")

    c = _ctl(monkeypatch, offset=2.0, sr=1000)
    c.set_context_nudge(80)
    c.load_project(p)
    assert not c.has_context_audio
    assert c.context_offset_s == 0.0                  # stale alignment is gone


# ---------------------------------------------------------------------------
# Variations (plan test 15)
# ---------------------------------------------------------------------------
def test_render_variation_with_context_mutates_nothing(monkeypatch):
    c = _ctl(monkeypatch, n=100, bed_n=5000, sr=1000, offset=0.5)
    c.render_preview(sample_rate=1000, with_context=True)
    before = {
        "spec": json.dumps(c.spec, sort_keys=True),
        "seed": c.seed,
        "preview": np.array(c._preview_buf, copy=True),
        "offset": c.preview_offset,
        "nudge": c.context_nudge_ms,
        "auto": c._auto_offset_s,
    }
    buf = c.render_variation(12345, sample_rate=1000, with_context=True)
    assert json.dumps(c.spec, sort_keys=True) == before["spec"]
    assert c.seed == before["seed"]
    assert np.array_equal(c._preview_buf, before["preview"])
    assert c.preview_offset == before["offset"]
    assert c.context_nudge_ms == before["nudge"]
    assert c._auto_offset_s == before["auto"]
    assert len(buf) == 100                            # bed sliced to the drums' span


def test_variation_bed_slice_is_not_the_whole_track(monkeypatch):
    """A full-length bed per variation is the memory blow-up this guards — but the
    bed must still actually be IN the mix."""
    c = _ctl(monkeypatch, n=100, bed_n=200_000, sr=1000, offset=0.0)
    buf = c.render_variation(1, sample_rate=1000, with_context=True)
    assert len(buf) == 100                            # not 200_000
    # drums 0.5*1.0 + bed 0.1*0.8 — a dropped bed would read 0.5
    assert float(np.max(np.abs(buf))) == pytest.approx(0.58)


def test_variation_uses_the_snapshot_not_live_state(monkeypatch):
    """The worker gets an immutable snapshot: mutating the controller afterwards
    must not change what the in-flight batch renders."""
    c = _ctl(monkeypatch, n=100, bed_n=5000, sr=1000, offset=0.0)
    snap = c.context_snapshot(sample_rate=1000)
    c.set_mix_gains(drums=0.0, bed=0.0)               # would silence a live read
    buf = c.render_variation(1, sample_rate=1000, with_context=True, context=snap)
    assert float(np.max(np.abs(buf))) == pytest.approx(0.58)


def test_context_snapshot_is_none_without_a_track(monkeypatch):
    _patch_render(monkeypatch)
    c = Controller(seed=1)
    c.song_from_profile("pop_punk")
    assert c.context_snapshot() is None


def test_variation_without_context_is_dry(monkeypatch):
    c = _ctl(monkeypatch, n=100, bed_n=5000, sr=1000, offset=0.0)
    dry = c.render_variation(1, sample_rate=1000, with_context=False)
    assert float(np.max(np.abs(dry))) == pytest.approx(0.5)   # no bed summed in


# ---------------------------------------------------------------------------
# Nudge controls
# ---------------------------------------------------------------------------
def test_nudge_beat_steps_one_beat_at_detected_tempo(monkeypatch):
    c = _ctl(monkeypatch, offset=0.0, sr=1000)
    c._detected_tempo = 120.0                         # one beat = 500 ms
    c.nudge_beat(+1)
    assert c.context_nudge_ms == 500
    c.nudge_beat(-1)
    assert c.context_nudge_ms == 0


def test_setters_invalidate_the_preview(monkeypatch):
    c = _ctl(monkeypatch, offset=0.0, sr=1000)
    for call in (lambda: c.set_context_nudge(10),
                 lambda: c.nudge_beat(1),
                 lambda: c.set_mix_gains(drums=1.2),
                 lambda: c.set_mix_gains(bed=0.5),
                 lambda: c.unload_context_audio()):
        c.render_preview(sample_rate=1000, with_context=False)
        assert c._preview_buf is not None
        call()
        assert c._preview_buf is None


def test_analyze_sets_offset_and_detected_tempo(monkeypatch):
    """Plan test 4/8 — the analysis lead-in becomes the alignment offset."""
    from app import analyze as analyze_mod

    class _R:
        tempo, sr, duration = 168.0, 22050, 200.0
        lead_in_s = 3.5
        sections = [{"role": "verse", "bars": 4}]

    monkeypatch.setattr(analyze_mod, "analyze_audio", lambda *a, **k: _R())
    c = Controller(seed=1)
    c.analyze_audio("x.wav")
    assert c._auto_offset_s == 3.5
    assert c._detected_tempo == 168.0
    assert c.context_nudge_ms == 0                    # a new analysis resets it


# ---------------------------------------------------------------------------
# Diff-gate regressions
# ---------------------------------------------------------------------------
def test_dry_last_section_keeps_its_render_tail(monkeypatch):
    """The 2 s decay tail belongs to EVERY render, mixed or dry — clamping the
    last section to the musical end alone cuts the cymbals off."""
    spec_sr = 1000
    _patch_render(monkeypatch, n=100)
    c = Controller(seed=1)
    c.song_from_profile("pop_punk")
    played = {}
    monkeypatch.setattr(playback, "Player", lambda *a, **k: _FakePlayer(played))
    # A dry render long enough to contain the whole arrangement plus a tail.
    spec = c.spec
    sec_per_tick = 60.0 / (spec["tempo"] * spec.get("ppq", 480))
    musical_s = engine.song_ticks(spec) * sec_per_tick
    total = int(round((musical_s + playback.RENDER_TAIL_S) * spec_sr))
    monkeypatch.setattr(playback, "render_events",
                        lambda events, **kw: np.full((total, 2), 0.5,
                                                     dtype=np.float32))
    c.render_preview(sample_rate=spec_sr)
    c.play_section(len(spec["sections"]) - 1)
    # The slice must reach the END of the buffer (musical end + tail), not stop
    # at the musical end.
    assert len(played["buf"]) > int(round(playback.RENDER_TAIL_S * spec_sr * 0.9))


def test_count_in_over_a_mix_does_not_clip(monkeypatch):
    """The click is summed in AFTER mix(), so it must be inside the peak check."""
    c = _ctl(monkeypatch, n=100, bed_n=8000, sr=1000, offset=4.0)
    c._detected_tempo = 120.0
    c.set_count_in(4)
    monkeypatch.setattr(playback, "click_track",
                        lambda beats, tempo, **kw: np.full((2000, 2), 0.9,
                                                           dtype=np.float32))
    c.set_mix_gains(drums=1.0, bed=1.0)
    buf = c.render_preview(sample_rate=1000, with_context=True)
    assert float(np.max(np.abs(buf))) <= 1.0 + 1e-6


def test_failed_context_restore_is_reported_by_mix_warnings(tmp_path, monkeypatch):
    """A moved audio file must keep warning after load — an export would
    otherwise silently lose the alignment the project was saved with."""
    c = _ctl(monkeypatch, offset=1.0, sr=1000)
    p = c.save_project(tmp_path / "proj.ppd")

    def boom(path, *, sample_rate=44100):
        raise FileNotFoundError(path)

    monkeypatch.setattr(playback, "load_audio", boom)
    c2 = Controller()
    c2.load_project(p)
    assert any("context audio" in w for w in c2.mix_warnings)


def test_align_export_persists_without_a_context_track(tmp_path, monkeypatch):
    _patch_render(monkeypatch)
    c = Controller(seed=1)
    c.song_from_profile("pop_punk")
    c.set_align_export(False)
    p = c.save_project(tmp_path / "a.ppd")
    c2 = Controller()
    c2.set_align_export(True)              # a previous project's setting
    c2.load_project(p)
    assert c2.align_export is False        # not left over from the old project
