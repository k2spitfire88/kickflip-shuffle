"""Audio analysis (F2) — librosa audio file -> an editable AnalysisResult ->
engine song spec.

The analysis is deliberately *approximate and correctable*: `analyze_audio`
returns a rich `AnalysisResult` (detected tempo, beats, segments, energy,
suggested sections, confidence) that the UI surfaces for editing; a separate
`spec_from_analysis` turns a (possibly corrected) result + a chosen profile into
an engine spec. Profile choice is the user's — analysis is band-style agnostic.

Determinism: every librosa call here (`load`, `beat_track`, `feature.mfcc/rms`,
`segment.agglomerative`) is deterministic; no rng is introduced. The only crash
surface is empty/flat inputs, handled explicitly below.

Verified librosa 0.11 behaviours relied on here:
  * `beat.beat_track` returns `(tempo, beat_frames)`; tempo may be a 1-element
    ndarray and can be 0.0 with an EMPTY beats array on weak material.
  * `feature.rms(y=)` -> shape `(1, n_frames)`; use row 0.
  * `segment.agglomerative(feature, k)` -> boundary FRAME indices including 0 but
    NOT the final frame; deterministic (no random init).
"""
from dataclasses import dataclass

import numpy as np
import librosa

import engine

DEFAULT_TEMPO = 120.0          # used only when no tempo can be estimated/given
MIN_SECTION_BARS = 2           # fixed-fallback chunk size, in bars
BEATS_PER_BAR_DEFAULT = 4      # 4/4 assumption
BARS_PER_SEGMENT_TARGET = 8    # ~1 structural segment per this many bars
_K_MIN, _K_MAX = 2, 8


@dataclass
class AnalysisResult:
    tempo: float
    sr: int
    duration: float
    alignment: str               # EFFECTIVE alignment (may be downgraded)
    beat_times: list             # seconds
    downbeat_times: list         # seconds (every beats_per_bar-th beat; naive)
    segments: list               # list of (start, end) seconds; last end==duration
    segment_energy: list         # normalised mean RMS per segment, 0..1
    sections: list               # [{role, bars, fill_at_end?, crash_in?}]
    confidence: dict             # {tempo: float 0..1, segmentation: str}


# ---------------------------------------------------------------------------
# Pure mapping helpers (no librosa — unit-tested directly)
# ---------------------------------------------------------------------------
def _normalize(energies):
    """Min-max to 0..1. Flat or single-element input -> all 0.5 (no div-by-0)."""
    if not energies:
        return []
    lo, hi = min(energies), max(energies)
    if hi == lo:
        return [0.5] * len(energies)
    return [(e - lo) / (hi - lo) for e in energies]


def _label_roles(norm):
    """First segment -> intro; otherwise two-band: >0.5 chorus, else verse.

    No auto-bridge/outro this phase (any numeric criterion would be arbitrary;
    bridge stays a UI choice). Flat input normalises to 0.5 -> intro then all
    verse (a flat track has no louder 'chorus' to distinguish).
    """
    roles = []
    for i, v in enumerate(norm):
        if i == 0:
            roles.append("intro")
        elif v > 0.5:
            roles.append("chorus")
        else:
            roles.append("verse")
    return roles


def _alloc_bars(boundary_times, tempo, beats_per_bar):
    """Bars per segment by CUMULATIVE rounding of boundary positions so the bar
    counts track total length (no independent-per-segment rounding drift). Each
    segment is floored to >=1 bar.

    `boundary_times` has len == n_segments + 1 (includes 0 and the track end).
    """
    bar_pos = [round(t * tempo / 60.0 / beats_per_bar) for t in boundary_times]
    return [max(1, bar_pos[i + 1] - bar_pos[i]) for i in range(len(bar_pos) - 1)]


def _sections_from(roles, bars, norm):
    """Assemble section dicts. crash_in on chorus; fill_at_end only when the
    NEXT section is louder (a build-up transition); last section never fills."""
    n = len(roles)
    sections = []
    for i in range(n):
        sec = {"role": roles[i], "bars": bars[i]}
        if roles[i] == "chorus":
            sec["crash_in"] = True
        if i < n - 1 and norm[i + 1] > norm[i]:
            sec["fill_at_end"] = True
        sections.append(sec)
    return sections


def _nearest(t, candidates):
    return min(candidates, key=lambda c: abs(c - t))


# ---------------------------------------------------------------------------
# Audio analysis
# ---------------------------------------------------------------------------
def analyze_audio(path, *, alignment="fixed_grid", known_tempo=None,
                  beats_per_bar=BEATS_PER_BAR_DEFAULT):
    """Analyse an audio file into an editable `AnalysisResult`.

    `alignment`: "fixed_grid" (default) derives bars straight from tempo;
    "follow_beats" snaps segment boundaries to detected downbeats, and is
    silently downgraded to "fixed_grid" when no beats are found.
    `known_tempo`: override the estimated tempo VALUE (beats are still tracked
    so follow_beats can work).
    """
    y, sr = librosa.load(path, mono=True)
    duration = float(librosa.get_duration(y=y, sr=sr))

    # --- tempo + beats (always tracked) -----------------------------------
    tempo_est, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    tempo_est = float(np.ravel(tempo_est)[0]) if np.size(tempo_est) else 0.0
    beat_frames = np.atleast_1d(beat_frames)
    beat_times = ([float(t) for t in librosa.frames_to_time(beat_frames, sr=sr)]
                  if beat_frames.size else [])

    if known_tempo:
        tempo = float(known_tempo)
    elif tempo_est > 0:
        tempo = tempo_est
    else:
        tempo = DEFAULT_TEMPO

    if len(beat_times) >= 2:
        intervals = np.diff(beat_times)
        mean_iv = float(np.mean(intervals))
        cv = float(np.std(intervals)) / mean_iv if mean_iv > 0 else 1.0
        tempo_conf = 1.0 / (1.0 + cv)
    else:
        tempo_conf = 0.0

    downbeat_times = beat_times[::beats_per_bar]
    bar_secs = beats_per_bar * 60.0 / tempo

    # --- segmentation (structural feature, or computable fixed fallback) ---
    feat = librosa.feature.mfcc(y=y, sr=sr)
    n_frames = feat.shape[1]
    rms = librosa.feature.rms(y=y)[0]
    n_rms = len(rms)

    k_req = int(np.clip(round(duration / (BARS_PER_SEGMENT_TARGET * bar_secs)),
                        _K_MIN, _K_MAX))
    use_structural = n_frames >= 2 and n_frames >= 2 * k_req \
        and duration >= MIN_SECTION_BARS * bar_secs

    if use_structural:
        bounds = librosa.segment.agglomerative(feat, min(k_req, n_frames))
        btimes = [float(t) for t in librosa.frames_to_time(np.asarray(bounds), sr=sr)]
        boundary_times = sorted(set([0.0] + [t for t in btimes if 0.0 < t < duration]))
        boundary_times.append(duration)
        seg_conf = "structural"
    else:
        chunk = MIN_SECTION_BARS * bar_secs
        boundary_times, t = [0.0], chunk
        while t < duration - 1e-6:
            boundary_times.append(t)
            t += chunk
        boundary_times.append(duration)
        seg_conf = "fixed_fallback"

    # --- effective alignment ----------------------------------------------
    eff_alignment = alignment
    if alignment == "follow_beats":
        if downbeat_times:
            snapped = sorted(set(
                [0.0] + [_nearest(t, downbeat_times)
                         for t in boundary_times[1:-1]] + [duration]))
            boundary_times = snapped
        else:
            eff_alignment = "fixed_grid"

    segments = [(boundary_times[i], boundary_times[i + 1])
                for i in range(len(boundary_times) - 1)]

    # --- per-segment energy -> roles/bars/sections ------------------------
    energies = []
    for s, e in segments:
        fs = max(0, int(librosa.time_to_frames(s, sr=sr)))
        fe = min(n_rms, int(librosa.time_to_frames(e, sr=sr)))
        if fe <= fs:
            fe = min(n_rms, fs + 1)
        energies.append(float(np.mean(rms[fs:fe])) if fe > fs else 0.0)

    norm = _normalize(energies)
    roles = _label_roles(norm)
    bars = _alloc_bars(boundary_times, tempo, beats_per_bar)
    sections = _sections_from(roles, bars, norm)

    return AnalysisResult(
        tempo=float(tempo), sr=int(sr), duration=duration,
        alignment=eff_alignment, beat_times=beat_times,
        downbeat_times=list(downbeat_times), segments=segments,
        segment_energy=norm, sections=sections,
        confidence={"tempo": tempo_conf, "segmentation": seg_conf})


def spec_from_analysis(result, profile, *, overrides=None, ppq=480):
    """Build an engine spec from a (possibly user-corrected) AnalysisResult and a
    chosen profile. Pure assembly — no music logic (mirrors
    Controller.build_spec_from_ui_state).
    """
    if profile not in engine.PROFILES:
        raise ValueError(f"Unknown profile '{profile}'. "
                         f"Options: {sorted(engine.PROFILES)}")
    return {
        "ppq": ppq,
        "profile": profile,
        "tempo": float(result.tempo),
        "overrides": dict(overrides or {}),
        "sections": [dict(s) for s in result.sections],
    }
