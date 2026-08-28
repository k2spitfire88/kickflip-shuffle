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
MAX_LEAD_IN_BARS = 4           # plausible intro before bar 1 (detector has no phase)
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
    lead_in_s: float = 0.0       # seconds before the first downbeat; the
                                 # arrangement covers [lead_in_s, duration]


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
    """Bars per segment so the counts SUM to the track's total bar length.

    The total is taken over the boundaries' SPAN (`boundary_times[-1] -
    boundary_times[0]`), not the absolute end, so an arrangement re-based to the
    first downbeat covers only `[lead_in, duration]`. With `boundary_times[0] ==
    0.0` (no lead-in) this is identical to the previous absolute-end behaviour.

    The boundaries are scaled proportionally onto the total bar count
    (`round(span * tempo/60 / beats_per_bar)`) rather than each rounded
    against tempo independently — so the arrangement matches the source length
    regardless of how the boundaries were produced (MFCC novelty or beat-snapped),
    instead of overshooting. Each segment is still floored to >=1 bar; when there
    are more segments than whole bars (sub-bar segments), the total is raised to
    `n_segments` (the minimum that gives every segment a bar).

    `boundary_times` has len == n_segments + 1 (includes 0 and the track end).
    """
    n = len(boundary_times) - 1
    if n <= 0:
        return []
    span = boundary_times[-1] - boundary_times[0]
    total = max(n, round(span * tempo / 60.0 / beats_per_bar))
    widths = [boundary_times[i + 1] - boundary_times[i] for i in range(n)]
    if sum(widths) <= 0:                        # degenerate: equal split
        widths = [1.0] * n
    ideal = [w / sum(widths) * total for w in widths]
    bars = [max(1, int(f)) for f in ideal]      # floor, each >=1 bar
    # Largest-remainder: distribute the rounding residual so SUM(bars) == total
    # exactly (feasible since total >= n), instead of letting sub-bar segments
    # each force a full extra bar (which overshoots the track length).
    diff = total - sum(bars)
    if diff > 0:
        for i in sorted(range(n), key=lambda i: ideal[i] - int(ideal[i]),
                        reverse=True)[:diff]:
            bars[i] += 1
    elif diff < 0:
        order = sorted(range(n), key=lambda i: bars[i], reverse=True)
        k = 0
        while diff < 0:
            i = order[k % n]
            if bars[i] > 1:
                bars[i] -= 1
                diff += 1
            k += 1
    return bars


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
                  beats_per_bar=BEATS_PER_BAR_DEFAULT, cut_to_click=False):
    """Analyse an audio file into an editable `AnalysisResult`.

    `alignment`: "fixed_grid" (default) derives bars straight from tempo;
    "follow_beats" snaps segment boundaries to detected downbeats, and is
    silently downgraded to "fixed_grid" when no beats are found.
    `known_tempo`: override the estimated tempo VALUE (beats are still tracked
    so follow_beats can work).
    `cut_to_click`: the caller asserts the file starts exactly on beat 1, so the
    lead-in is forced to 0 and no re-basing happens (mirrors the drop view's
    "Cut to click" checkbox).
    """
    y, sr = librosa.load(path, mono=True)
    duration = float(librosa.get_duration(y=y, sr=sr))

    # --- tempo + beats (always tracked) -----------------------------------
    tempo_est, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    tempo_est = float(np.ravel(tempo_est)[0]) if np.size(tempo_est) else 0.0
    beat_frames = np.atleast_1d(beat_frames)
    beat_times = ([float(t) for t in librosa.frames_to_time(beat_frames, sr=sr)]
                  if beat_frames.size else [])

    if known_tempo is not None:
        if known_tempo <= 0:
            raise ValueError(f"known_tempo must be > 0, got {known_tempo}")
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

    # --- lead-in: re-base the arrangement onto the first downbeat ---------
    # The drums are played back shifted to `lead_in_s` (context mix), so bars
    # must be allocated over [lead_in_s, duration] — allocating from 0 would put
    # every section late by exactly the lead-in. Boundaries stay ABSOLUTE times.
    lead_in_s = 0.0
    if not cut_to_click and downbeat_times:
        cand = float(downbeat_times[0])
        # `downbeat_times` is `beat_times[::beats_per_bar]` with NO phase
        # estimation, so a mis-tracked first beat could land anywhere. Bound the
        # lead-in to something musically plausible (a few bars): without this, a
        # late candidate filters out every interior boundary and collapses a
        # multi-section arrangement to one section.
        if 0.0 < cand < min(duration - bar_secs, MAX_LEAD_IN_BARS * bar_secs):
            lead_in_s = cand
    if lead_in_s > 0.0:
        # Drop any boundary within a bar of the new start too — it would make a
        # sub-bar opening segment that _alloc_bars has to floor up to a full bar.
        boundary_times = ([lead_in_s]
                          + [t for t in boundary_times
                             if lead_in_s + bar_secs <= t < duration]
                          + [duration])

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
        confidence={"tempo": tempo_conf, "segmentation": seg_conf},
        lead_in_s=lead_in_s)


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
