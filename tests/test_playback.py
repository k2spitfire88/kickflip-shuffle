"""Phase 4 playback tests. The render/mix/load paths use real fluidsynth + the
soundfont and are skipped when the (gitignored) sf2 is absent. The Player test is
additionally gated behind a real audio output device."""
import numpy as np
import soundfile as sf
import pytest

import engine
from app import playback
from app.playback import (
    render_events, load_audio, mix, overlay, peak_normalize, click_track,
    has_output_device,
    Player, DEFAULT_SOUNDFONT,
)

# Render tests need the 142MB gitignored soundfont — skip cleanly without it.
needs_sf2 = pytest.mark.skipif(
    not DEFAULT_SOUNDFONT.exists(),
    reason="FluidR3_GM.sf2 not present (gitignored ~140MB)")

SR = 44100


def _two_events(ppq=480):
    # kick at tick 0, snare at tick ppq (one beat later), each 1/8 long.
    return [(0, 36, 120, ppq // 2), (ppq, 38, 110, ppq // 2)]


# ---------------------------------------------------------------------------
# render_events (real fluidsynth)
# ---------------------------------------------------------------------------
@needs_sf2
def test_render_shape_nonsilent_exact_length():
    tempo, ppq, tail = 120, 480, 1.0
    events = _two_events(ppq)
    buf = render_events(events, tempo=tempo, ppq=ppq, sample_rate=SR, tail=tail)
    assert buf.dtype == np.float32 and buf.ndim == 2 and buf.shape[1] == 2
    assert float(np.max(np.abs(buf))) > 0.0          # drum bank produced sound
    # Length is exact: last off index + tail (we control the sample count).
    sec_per_tick = 60.0 / (tempo * ppq)
    last_off = round((ppq + ppq // 2) * sec_per_tick * SR)
    assert buf.shape[0] == last_off + round(tail * SR)


@needs_sf2
def test_render_deterministic():
    e = _two_events()
    a = render_events(e, tempo=170, ppq=480, sample_rate=SR, tail=0.5)
    b = render_events(e, tempo=170, ppq=480, sample_rate=SR, tail=0.5)
    assert np.array_equal(a, b)


@needs_sf2
def test_single_kick_nonsilent():
    buf = render_events([(0, 36, 120, 240)], tempo=170, ppq=480,
                        sample_rate=SR, tail=0.5)
    assert float(np.max(np.abs(buf))) > 0.0


@needs_sf2
def test_render_real_song_via_engine():
    spec = engine.song_from_profile("pop_punk")
    events = engine.build_song(spec, seed=1, output_map=engine.GENERAL_MIDI)
    buf = render_events(events, tempo=spec["tempo"], ppq=spec["ppq"],
                        sample_rate=SR, tail=1.0)
    assert buf.shape[1] == 2 and float(np.max(np.abs(buf))) > 0.0


def test_missing_soundfont_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        render_events(_two_events(), tempo=120, ppq=480,
                      soundfont=tmp_path / "nope.sf2")


# ---------------------------------------------------------------------------
# mix + load_audio (no soundfont needed)
# ---------------------------------------------------------------------------
def test_mix_length_and_silent_bed():
    drums = np.ones((100, 2), dtype=np.float32) * 0.5
    bed = np.zeros((60, 2), dtype=np.float32)
    out = mix(drums, bed, drums_gain=1.0, bed_gain=0.8)
    assert out.shape == (100, 2) and out.dtype == np.float32
    assert np.array_equal(out[:100], drums)          # silent bed leaves drums as-is


def test_mix_normalises_on_clip():
    drums = np.ones((10, 2), dtype=np.float32)
    bed = np.ones((10, 2), dtype=np.float32)
    out = mix(drums, bed, drums_gain=1.0, bed_gain=1.0)  # would be 2.0 -> clip
    assert float(np.max(np.abs(out))) <= 1.0 + 1e-6


# --- Phase 9: alignment pads, overlay, gain monotonicity -------------------

def test_mix_default_pads_byte_identical():
    """Plan test 1 — the default (no-pad) path must not move a single sample."""
    rng = np.random.default_rng(7)
    drums = rng.standard_normal((200, 2)).astype(np.float32) * 0.3
    bed = rng.standard_normal((150, 2)).astype(np.float32) * 0.3
    assert np.array_equal(
        mix(drums, bed),
        mix(drums, bed, drums_pad_frames=0, bed_pad_frames=0))


def test_mix_drums_pad_frames():
    """Plan test 2 — positive offset front-pads the drums; length grows with it."""
    drums = np.ones((100, 2), dtype=np.float32) * 0.5
    bed = np.zeros((60, 2), dtype=np.float32)
    out = mix(drums, bed, drums_pad_frames=25)
    assert out.shape == (125, 2)                      # max(25+100, 60)
    assert not out[:25].any()                         # silence before the drums
    assert np.array_equal(out[25:125], drums)


def test_mix_bed_pad_frames_symmetric():
    """Plan test 3 — a negative offset pads the bed instead, symmetrically."""
    drums = np.zeros((60, 2), dtype=np.float32)
    bed = np.ones((100, 2), dtype=np.float32) * 0.5
    out = mix(drums, bed, bed_gain=1.0, bed_pad_frames=25)
    assert out.shape == (125, 2)
    assert not out[:25].any()
    assert np.array_equal(out[25:125], bed)


def test_mix_gain_ratio_is_monotonic():
    """Plan test 4 — raising drums_gain never lowers the drums:bed ratio, INCLUDING
    when peak-normalisation fires (it scales both sides equally).

    Drums and bed are disjoint in time inside ONE mix call, so both components are
    measurable in the single normalised output — mixing them separately would
    never clip and the test could not fail."""
    drums = np.ones((50, 2), dtype=np.float32)          # loud enough to clip
    bed = np.ones((50, 2), dtype=np.float32)
    ratios = []
    for g in (0.5, 1.0, 1.5):
        out = mix(drums, bed, drums_gain=g, bed_gain=0.8, bed_pad_frames=50)
        assert float(np.max(np.abs(out))) <= 1.0 + 1e-6     # normalisation fired
        drums_level = float(np.max(np.abs(out[:50])))
        bed_level = float(np.max(np.abs(out[50:])))
        ratios.append(drums_level / bed_level)
    assert ratios == sorted(ratios) and ratios[0] < ratios[-1]


def test_mix_normalize_false_defers_the_clip_check():
    drums = np.ones((10, 2), dtype=np.float32)
    bed = np.ones((10, 2), dtype=np.float32)
    raw = mix(drums, bed, drums_gain=1.0, bed_gain=1.0, normalize=False)
    assert float(np.max(np.abs(raw))) == pytest.approx(2.0)
    assert float(np.max(np.abs(peak_normalize(raw)))) == pytest.approx(1.0)
    assert np.array_equal(peak_normalize(raw), mix(drums, bed, bed_gain=1.0))


def test_overlay_clips_both_ends_and_tolerates_degenerate_src():
    """Plan test 5 — overlay never grows dest and clips src at both ends."""
    dest = np.zeros((10, 2), dtype=np.float32)
    src = np.ones((6, 2), dtype=np.float32)
    out = overlay(dest, src, 7)                       # runs off the end
    assert out.shape == (10, 2)
    assert not out[:7].any() and np.all(out[7:] == 1.0)
    out = overlay(dest, src, -4)                      # starts before the head
    assert np.all(out[:2] == 1.0) and not out[2:].any()
    out = overlay(dest, src, 100)                     # entirely past the end
    assert not out.any()
    # click_track's beats<=0 degenerate return is a 1-frame buffer.
    assert overlay(dest, click_track(0, 120), 3).shape == (10, 2)
    # dest is not mutated in place
    assert not dest.any()


def test_load_audio_resample_and_mono(tmp_path):
    # mono file at 22050 -> stereo float32 at 44100.
    src_sr = 22050
    y = (np.sin(2 * np.pi * 220 * np.arange(src_sr) / src_sr)).astype(np.float32)
    p = str(tmp_path / "mono.wav")
    sf.write(p, y, src_sr)
    out = load_audio(p, sample_rate=44100)
    assert out.dtype == np.float32 and out.shape[1] == 2
    assert abs(out.shape[0] - 44100) <= 2            # ~2x frames after resample


# ---------------------------------------------------------------------------
# Player (device-gated)
# ---------------------------------------------------------------------------
def test_seek_clamps_without_device():
    p = Player()
    p.load(np.zeros((SR, 2), dtype=np.float32), SR)
    p.seek(-5)
    assert p.position == 0.0
    p.seek(10_000)                                   # far past end -> clamped
    assert 0.0 <= p.position <= 1.0 + 1e-6


@pytest.mark.audio
@pytest.mark.skipif(not has_output_device(), reason="no audio output device")
def test_player_play_stop():
    p = Player()
    p.load(np.zeros((SR // 10, 2), dtype=np.float32), SR)
    p.play()
    p.stop()
    assert p.position == 0.0
    assert not p.is_playing
