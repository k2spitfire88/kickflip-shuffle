"""Phase 3 audio-analysis tests. Pure mapping helpers are unit-tested without
librosa; the fallback/empty-beats branches are forced deterministically; one
smoke test runs the real librosa pipeline on a generated click track."""
import numpy as np
import soundfile as sf
import pytest

import engine
from app import analyze
from app.analyze import (
    _normalize, _label_roles, _alloc_bars, _sections_from,
    AnalysisResult, analyze_audio, spec_from_analysis,
)


# ---------------------------------------------------------------------------
# Pure helpers (no librosa)
# ---------------------------------------------------------------------------
def test_normalize_spread():
    assert _normalize([1.0, 3.0, 5.0]) == [0.0, 0.5, 1.0]


def test_normalize_flat_and_single_no_nan():
    assert _normalize([0.7, 0.7, 0.7]) == [0.5, 0.5, 0.5]  # max==min, no div/0
    assert _normalize([0.4]) == [0.5]
    assert _normalize([]) == []


def test_label_roles_bands():
    roles = _label_roles([0.0, 0.9, 0.1, 0.8])
    assert roles == ["intro", "chorus", "verse", "chorus"]


def test_label_roles_flat_is_intro_then_verse():
    assert _label_roles([0.5, 0.5, 0.5]) == ["intro", "verse", "verse"]
    assert "bridge" not in _label_roles([0.5] * 5)  # never auto-bridge


def test_alloc_bars_cumulative_no_drift():
    # 120 BPM, 4/4 -> 2.0 s/bar. Boundaries at 0,4,8,12 s -> 2,2,2 bars; sums to 6.
    bars = _alloc_bars([0.0, 4.0, 8.0, 12.0], tempo=120, beats_per_bar=4)
    assert bars == [2, 2, 2]
    total_bars = round(12.0 * 120 / 60 / 4)
    assert sum(bars) == total_bars


def test_alloc_bars_subbar_floored_to_one():
    # 0..1 s at 120 BPM is half a bar -> rounds to 0 -> floored to 1.
    assert _alloc_bars([0.0, 1.0], tempo=120, beats_per_bar=4) == [1]


def test_sections_from_crash_fill_last():
    roles = ["verse", "chorus", "verse"]
    bars = [4, 4, 4]
    norm = [0.2, 0.9, 0.3]   # v->c rises (fill), c->v falls (no fill)
    secs = _sections_from(roles, bars, norm)
    assert secs[0] == {"role": "verse", "bars": 4, "fill_at_end": True}
    assert secs[1] == {"role": "chorus", "bars": 4, "crash_in": True}
    assert secs[2] == {"role": "verse", "bars": 4}  # last: no fill


# ---------------------------------------------------------------------------
# spec_from_analysis
# ---------------------------------------------------------------------------
def _fake_result(**kw):
    base = dict(
        tempo=174.0, sr=22050, duration=8.0, alignment="fixed_grid",
        beat_times=[], downbeat_times=[],
        segments=[(0.0, 4.0), (4.0, 8.0)], segment_energy=[0.2, 0.9],
        sections=[{"role": "verse", "bars": 4, "fill_at_end": True},
                  {"role": "chorus", "bars": 4, "crash_in": True}],
        confidence={"tempo": 0.0, "segmentation": "fixed_fallback"})
    base.update(kw)
    return AnalysisResult(**base)


def test_spec_from_analysis_builds_valid_spec():
    spec = spec_from_analysis(_fake_result(), "pop_punk")
    assert spec["profile"] == "pop_punk" and spec["tempo"] == 174.0
    assert spec["sections"] == _fake_result().sections
    assert engine.build_song(spec, seed=1)  # engine accepts + renders


def test_spec_from_analysis_unknown_profile():
    with pytest.raises(ValueError):
        spec_from_analysis(_fake_result(), "not_a_profile")


# ---------------------------------------------------------------------------
# librosa-backed branches (real signals, forced deterministically)
# ---------------------------------------------------------------------------
def _write_clicks(path, *, bpm=120, dur=8.0, sr=22050):
    spacing = 60.0 / bpm
    y = librosa_clicks(spacing, dur, sr)
    sf.write(path, y, sr)


def librosa_clicks(spacing, dur, sr):
    import librosa
    times = np.arange(0.0, dur, spacing)
    return librosa.clicks(times=times, sr=sr, length=int(dur * sr))


def test_fixed_fallback_on_short_audio(tmp_path):
    # 1 s at 120 BPM is < MIN_SECTION_BARS(2)*2 s/bar = 4 s -> fixed fallback.
    p = str(tmp_path / "short.wav")
    _write_clicks(p, dur=1.0)
    r = analyze_audio(p, known_tempo=120)
    assert r.confidence["segmentation"] == "fixed_fallback"
    assert r.sections and all(s["bars"] >= 1 for s in r.sections)


def test_follow_beats_downgrades_when_no_beats(tmp_path, monkeypatch):
    import librosa
    # Force empty beats -> downbeats empty -> follow_beats must downgrade.
    monkeypatch.setattr(librosa.beat, "beat_track",
                        lambda **kw: (0.0, np.array([], dtype=int)))
    p = str(tmp_path / "c.wav")
    _write_clicks(p, dur=6.0)
    r = analyze_audio(p, alignment="follow_beats")
    assert r.alignment == "fixed_grid"          # downgraded, no crash
    assert r.downbeat_times == []
    assert r.confidence["tempo"] == 0.0


@pytest.mark.slow
def test_real_pipeline_smoke(tmp_path):
    p = str(tmp_path / "click120.wav")
    _write_clicks(p, bpm=120, dur=8.0)
    r = analyze_audio(p, known_tempo=120)
    assert np.isfinite(r.tempo) and r.tempo == 120.0   # plumbed, not estimated
    assert len(r.sections) >= 1
    assert 0.0 < r.duration <= 9.0
    spec = spec_from_analysis(r, "pop_punk")
    assert engine.build_song(spec, seed=1)             # end-to-end works
