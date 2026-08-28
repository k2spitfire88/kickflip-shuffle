# Phase 9 — Context mix: hear the drums over the dropped track

**STATUS: SHIPPED 2026-08-28** — all five build steps done, 289 tests passing.
Deviations from this plan are listed under "As built" at the foot of the document.

**Rev 2** (post plan-gate, 2026-08-28). Rev 1's four blockers are resolved below;
where a Rev-1 owner decision was made without knowing a consequence, the supersession
is called out explicitly.

Goal: audition the generated drums **against the audio file the user dropped in**,
time-aligned to the track, before exporting the `.mid` — and export a `.mid` that
lands in the DAW where it was auditioned.

## Current state (verified against the working tree)

Shipped and tested, but **no UI caller anywhere in `app/ui/`**:
- `playback.load_audio(path, *, sample_rate)` (`app/playback.py:119`)
- `playback.mix(drums, bed, *, drums_gain=1.0, bed_gain=0.8)` (`app/playback.py:135`)
  — pad-to-longer sum, peak-normalise on clip. **Sums from frame 0; no offset.**
- `Controller.load_context_audio(path)` (`app/controller.py:626`)
- `Controller.render_preview(..., with_context=False)` (`app/controller.py:633`),
  mixing at `:655`.

Gaps: `grep -rn "with_context\|load_context" app/ui` → **0 hits**; the dropped path
dies in `DropView._path` (`app/ui/drop_view.py:146`); no alignment; no gain UI.

## Owner decisions (LOCKED 2026-08-28)

1. **Alignment: auto downbeat offset + manual nudge.**
2. **BPM drift: warn only.** No time-stretch, no BPM lock.
3. **Path plumbing: auto-load on drop, persist in `.ppd`,** missing file degrades
   with a warning.
4. **Scope: Play Song + Play Section + Variations + track/drums gain sliders.**
5. **Count-in: click overlays the track's lead-in** — built at the **detected** tempo
   and phase-locked to `beat_times`, so it counts you into the *track* (rev 2).
6. ~~Shift drums, pad the end, arrangement stays sized from t=0.~~ **SUPERSEDED by
   decision 11** — that combination lands every detected section late by the offset.
7. **Length mismatch: inline warning** past one bar.
8. **Short lead-in: front-pad the whole mix** so the click stays complete;
   `_preview_offset` absorbs the deficit.
9. **`.ppd`: no `PROJECT_VERSION` bump.** Additive optional block.
10. **Mix checkbox defaults ON** when a context track is loaded; gains in **percent**
    (0–150 %, track 80 % / drums 100 %).
11. **Re-base bar allocation to the first downbeat** (`analyze.py` only) so sections
    line up with the track. Supersedes 6.
12. **Padded export**, default **ON** when a context track is loaded: prepend
    `round(offset_s * ppq * tempo / 60)` ticks at write time so the exported `.mid`
    lands where it was auditioned. Drag-to-DAW uses the same setting.
13. **Nudge range = ±1 bar at the current tempo**, plus ◀/▶ buttons that jump exactly
    one beat (the detector has no phase estimation — see Risk 🔴 A).

## Design

### A. The offset, defined once

Everything hangs off one quantity and one invariant.

```
o          = context_offset_s = auto_offset_s + nudge_ms/1000
deficit_s  = max(0, count_in_beats * 60/detected_tempo - max(0, o))   # 0 when not mixing
drums_pad  = max(0,  o) + deficit_s          # seconds of silence before the drums
bed_pad    = max(0, -o) + deficit_s          # seconds of silence before the track
_preview_offset = drums_pad                  # ALWAYS >= 0
```

`_preview_offset` keeps its existing meaning — *seconds of buffer before musical tick
0* — which is why `generate_view._position_to_grid` (`:448`) and the head math in
`play_section` (`:743`) keep working. **It must never go negative**: Rev 1 set it to a
raw signed offset, which made `play_section` slice `buf[-N:end]` (a tail-relative
slice → silence, no exception) and ran the playhead ahead. [plan-gate BLOCKER 1]

### B. `app/playback.py`

- **`mix(drums, bed, *, drums_gain=1.0, bed_gain=0.8, drums_pad_frames=0,
  bed_pad_frames=0)`** — pads in **frames, not seconds**, so the caller owns all
  sample-rate math and there is no second rate default to disagree with the render
  rate. [BLOCKER 1, HIGH 8] Defaults keep the existing call site byte-identical.
- **Normalise before applying user gains** (or apply fixed headroom), so raising
  `drums_gain` can never attenuate the drums-to-bed ratio. Today's unconditional
  post-gain peak-normalise (`:142`) is non-monotonic once the gains are user-facing.
  [MED 14]
- **`overlay(dest, src, at_frames)`** — new helper; sums `src` into `dest` at a frame
  offset, clipping `src` at both ends. Tolerates `click_track`'s 1-frame degenerate
  return (`:31`). Rev 1 said "the mixed path overlays" without naming a function that
  could. [HIGH 6]
- **`click_track`** — unchanged signature; callers pass the detected tempo.

### C. `app/analyze.py`

- `analyze_audio` gains `lead_in` handling: `boundary_times` are re-based to the first
  downbeat and `_alloc_bars` allocates over `duration - offset`, so section boundaries
  match the track. `AnalysisResult` grows `lead_in_s`. [BLOCKER 3]
- **Cut-to-click** (`drop_view.py:92`) asserts the track starts on beat 1 → force
  `lead_in_s = 0.0` and skip re-basing. [HIGH 5]
- Existing `tests/test_analyze.py` bar-count expectations change with this — that is
  intended, not a regression. **No engine touch → golden byte-identity untouched.**

### D. `app/controller.py`

New state: `_context_path`, `_context_len_s`, `_auto_offset_s`, `_context_nudge_ms`,
`_drums_gain`, `_bed_gain`, `_detected_tempo`, `_align_export`.

- `load_context_audio(path, *, sample_rate)` — also store the path and length.
- `has_context_audio` / `unload_context_audio()` — both referenced by the UI, neither
  existed. [LOW 17]
- `context_offset_s` property (`_auto_offset_s + _context_nudge_ms/1000`);
  `set_context_nudge(ms)`, `nudge_beat(±1)`, `set_mix_gains(drums=, bed=)`,
  `set_align_export(bool)` — all `_invalidate_preview()`.
- `analyze_audio` — set `_auto_offset_s = result.lead_in_s` and
  `_detected_tempo = result.tempo`.
- `render_preview(..., with_context=False)`:
  - The mixed path runs **only** under `with_context and self._context_audio is not
    None`; otherwise the existing prepend path (`:659-665`) runs **unchanged** —
    `tests/test_countin.py` is the byte-identity guard. [HIGH 7]
  - **Sample-rate guard**: if `_context_sr != sample_rate`, re-load/resample the
    context before mixing. `_context_sr` is stored today and read by nothing. [HIGH 8]
  - Build the click at `_detected_tempo`, phase-locked to `beat_times`, and `overlay`
    it onto the bed ending at the first downbeat. [HIGH 6]
  - `mix(...)` with the frame pads from §A; set `_preview_offset = drums_pad`.
- `play_section` — **needs changes; Rev 1's "no change needed" was false.**
  - Clamp the last section: `end_s = min(len(buf), head + round((total_ticks *
    sec_per_tick + tail) * sr))`. Unclamped, a mixed last-section audition plays the
    entire remaining track. [BLOCKER 2]
  - Stop mutating `_preview_offset` to 0 (`:751`); use a separate `_play_head_s` so a
    second `play_section` on the same held buffer still slices correctly. [MED 16]
- `render_variation(seed, *, with_context=False, bed_slice=None)` — mix against
  **only the drums' span of the bed**, not the whole track: 8 full-length mixed
  variations is ~670 MB for a 4-minute track. [HIGH 11] Snapshot `(bed, offset,
  gains)` as arguments at call time on the UI thread so the documented purity /
  thread-safety contract in `variations.py:1-8` stays true. [MED 12]
- `export(..., align=None)` — when aligning, prepend `round(offset_s * ppq * tempo /
  60)` ticks to every event at write time. Default follows `_align_export`.
  Unaligned path stays byte-identical. [BLOCKER 4]
- `mix_warnings` property: tempo drift expressed as **accumulated drift over the track**
  (`abs(Δtempo)/tempo * duration > half a beat`), not a raw 0.5 BPM threshold; length
  mismatch > 1 bar; missing/failed context file. [LOW 17]
- `to_project` — additive `"context_audio": {"path", "nudge_ms", "auto_offset_s",
  "detected_tempo", "align_export"}`. Persisting the nudge alone would silently lose
  the alignment on reload, since `load_project` never re-runs analysis. [MED 13]
- `load_project` — restore the block **after** the "all validated — now mutate" line
  (`:580`), catching broad `Exception` (the lazy `from . import playback` pulls in
  fluidsynth/sounddevice/soundfile and can fail for reasons other than a missing
  file). Append to `warnings`; never raise. [MED 13]

### E. `app/ui/`

- `drop_view.py` — load the context audio **inside `_AnalyzeWorker.run`** (it already
  holds the path) and emit the buffer with the result. Doing it in `_on_done`
  (`:210`) would decode + resample a full song on the UI thread, a second time.
  [MED 15]
- `generate_view.py` transport row, before the stretch at `:184`:
  `mix_chk` (default ON when a track is loaded, disabled otherwise), `◀ beat` /
  `nudge` spinbox (±1 bar at current tempo, ms) / `beat ▶`, `track` + `drums` gain
  sliders (percent), `align_export` checkbox, and a warning `QLabel` fed from
  `mix_warnings`.
  - **All new widgets go into `_set_controls_enabled` (`:642`)** — otherwise the UI
    thread can invalidate the preview mid-render and the worker then writes a stale
    buffer over the invalidation. [HIGH 9]
  - `with_context` and the gains/offset are captured into **`_RenderWorker.__init__`**
    on the UI thread (`:381`). Rev 1 wired them to `_start_render`/`_on_render_done`,
    but `_on_render_done` does no rendering — the only render call is
    `_RenderWorker.run` (`:54`). [HIGH 10]
  - `GenerateView.__init__` pushes the restored `Prefs` gains into the controller, so
    the sliders and `_drums_gain`/`_bed_gain` cannot start out of sync. [LOW 17]
  - Playhead: `_position_to_grid` returns `None` before tick 0 (`:452,458`), so the
    grid is dead through the whole lead-in — show an explicit "counting in / lead-in"
    state instead of a frozen grid. [LOW 17]
- `variations.py` — `with_context` and the bed slice go through
  `_VariationsWorker.__init__`; a worker must not read `parent().mix_chk` across
  threads. [HIGH 10]
- `settings.py` — `mix_drums_gain`, `mix_bed_gain` keys, matching the `export_dir`
  getter/setter pattern.

## Risks

- 🔴 **A. The detector has no phase estimation.** `downbeat_times =
  beat_times[::beats_per_bar]` (`analyze.py:181`, its own comment says "naive") — the
  "first downbeat" is one of four beats at random. Decision 13 (±1 bar + beat jumps)
  is the mitigation; the auto offset is a starting point, not an answer. [HIGH 5]
- 🔴 **B. `_preview_offset` sign.** §A's invariant is the fix; test both signs of
  nudge explicitly, including `play_section`.
- 🟡 **C. `mix()` signature + normalisation change** — 1 call site, plus
  `tests/test_playback.py`. Defaults must be byte-identical.
- 🟡 **D. Count-in has two code paths now.** Mixed (overlay, detected tempo) vs
  unmixed (prepend, spec tempo). `tests/test_countin.py` guards the second.
- 🟡 **E. `analyze` re-basing changes generated specs** — `tests/test_analyze.py`
  expectations move. Intended.
- 🟡 **F. Export gains an alignment mode** — the unaligned path must stay
  byte-identical; `tests/test_golden.py` + `tests/test_persistence.py` guards.
- 🔵 **No engine touch anywhere.** Golden byte-identity is safe by construction.

## Test plan

**Regression guards that must keep passing unchanged:**
`tests/test_countin.py::test_render_preview_prepends_count_in`,
`::test_no_count_in_offset_zero`, `::test_playhead_skips_count_in`;
`tests/test_play_section.py::test_last_section_runs_to_end_with_tail` (update for the
mixed case — it asserts today's unclamped behaviour and would pass while blocker 2 is
live); the engine golden test.

`tests/test_playback.py`
1. `mix()` with default pads is `array_equal` to today's output.
2. `drums_pad_frames=N` → first N frames silent; length `== max(len(bed), N+len(drums))`.
3. `bed_pad_frames=N` is symmetric.
4. Raising `drums_gain` never lowers the drums-to-bed ratio (normalisation monotonicity).
5. `overlay` clips at both ends and tolerates a 1-frame src.

`tests/test_analyze.py`
6. Re-based allocation: a synthetic file with a known lead-in puts section boundaries
   at the re-based times; `lead_in_s` is set.
7. Cut-to-click forces `lead_in_s == 0`.

`tests/test_controller.py`
8. `render_preview(with_context=True)` → `_preview_offset == drums_pad` for positive,
   **negative**, and zero nudge (never negative).
9. Short lead-in → front-pad; the click is complete and `_preview_offset` absorbs the
   deficit.
10. `play_section` on the last section of a mixed preview stops at the drums' end, not
    the track's; two consecutive `play_section` calls both slice correctly.
11. Sample-rate mismatch (`render_preview(sample_rate=1000)` with a 44.1k context)
    resamples or raises — never silently mixes.
12. Aligned export shifts every event by exactly `round(offset*ppq*tempo/60)` ticks;
    unaligned export is byte-identical to today.
13. `mix_warnings` fires on accumulated drift > half a beat and on a > 1 bar length
    mismatch; empty immediately after Build (drift is 0 by construction).
14. `.ppd` round-trips the block including `auto_offset_s`; a missing file warns
    rather than raising; an old `.ppd` without the block still loads.
15. `render_variation(with_context=True)` mutates no held state — including
    `_preview_offset` and `_context_*`.

`tests/test_ui.py` + `tests/test_playhead.py` (offscreen)
16. Mix checkbox disabled with no track, enabled + ON after `load_context_audio`.
17. All new widgets are disabled during a render (`_set_controls_enabled`).
18. `with_context`/gains/offset reach `_RenderWorker` via its constructor.
19. Warning label hidden when `mix_warnings` is empty.

`tests/test_drop.py`
20. Analyze loads the context audio on the worker thread; a decode failure surfaces a
    status message and does not break `specBuilt`.

## Build order

1. `playback` (mix pads, overlay, normalisation) + tests 1–5.
2. `analyze` re-basing + tests 6–7.
3. `controller` (offset math, play_section clamp, sample-rate guard, export
   alignment, warnings, persistence) + tests 8–15.
4. `ui` (transport widgets, worker plumbing, drop-view load, prefs) + tests 16–20.
5. Full suite + diff-gate review.

## As built (2026-08-28)

Built as planned, with these deliberate deviations:

1. **`mix` normalisation was NOT changed.** The plan said "normalise before applying
   user gains" for monotonicity. On inspection the existing post-gain
   peak-normalisation scales drums and bed *equally*, so the drums:bed ratio is
   exactly `drums_gain/bed_gain` regardless — the non-monotonicity the plan-gate
   flagged does not exist. Changing it would have altered the default path's output
   and broken the byte-identity guard for no gain. A test
   (`test_mix_gain_ratio_is_monotonic`) now pins the ratio property instead.
2. **`section_ticks`/`song_ticks` were added to the ENGINE**, not the controller.
   The plan put the length maths in `app/controller.py`; that duplicates
   `compute_section_markers`' integer maths in the app layer, which the project's
   architecture rule forbids ("never port music logic up into the app"). They are
   additive engine functions; golden output is unchanged.
3. **`_play_head_s` is also set by `render_preview`,** not only by
   `play`/`play_section`. Without it the playhead mapping is only valid after a
   `play()` call — the existing regression test
   `test_countin.py::test_playhead_skips_count_in` calls `_position_to_grid`
   straight after a render and caught this.
4. **`load_context_audio` gained a `buffer=` parameter** so the drop view's analysis
   worker can hand over an already-decoded buffer (the plan called for
   worker-thread decoding but did not say how the buffer would cross over).
5. **`_AnalyzeWorker` gained a `context_failed` signal** so a decode failure is a
   status message rather than a failed analysis.

## Diff-gate findings, fixed (2026-08-28)

The diff-gate review found one blocker and nine lesser defects, all invisible to
the then-passing suite. Every one is fixed, each with a regression test:

1. **BLOCKER — the mix never engaged from the UI.** `_start_render` called
   `_set_controls_enabled(False)` *before* reading `_mix_enabled()`, which is
   `mix_chk.isEnabled() and isChecked()` — so `with_context` was always False on
   the only path that reaches it. The flag is now captured first.
   (`test_start_render_passes_the_mix_flag_end_to_end`)
2. **Dry last-section audition lost its 2 s decay tail** — the tail was applied only
   to the mixed branch. It belongs to every render.
3. **`render_variation` read live controller state on the worker thread.** Now takes
   an immutable `context_snapshot()` taken on the UI thread; `_mix_variation` is a
   static, snapshot-only function.
4. **The playhead died for the whole take whenever there was a lead-in.**
   `_tick_playhead` treated "before tick 0" as "ended" and stopped its timer.
   `_position_to_grid` now returns a `LEAD_IN` sentinel, distinct from `None`.
5. **The count-in click could clip a mixed preview** — it was overlaid after
   `mix`'s peak-normalisation. `mix(normalize=False)` + `playback.peak_normalize`
   now normalise once, over the final signal.
6. **A mis-detected late "first downbeat" collapsed the arrangement to one section.**
   The lead-in is bounded to `MAX_LEAD_IN_BARS` (4), and boundaries within a bar of
   the new start are dropped.
7. **`align_export` was stored inside the context block**, so it was lost for a
   track-less project and left over from the previous one on load. Now top-level.
8. **Cross-view race:** a drop-view analysis writes mix state and invalidates the
   preview from its own thread while a Generate render runs. `DropView.busy` now
   drives `GenerateView.set_external_busy`, which freezes the view and refuses
   `_start_render`.
9. **`mix_warnings` never reported a failed context restore** — a moved audio file
   warned once at load, then exports silently lost the alignment. Now tracked in
   `_context_error` and surfaced until a successful load.
10. Four weak tests replaced (a gain-monotonicity test that could not fail, a
    variation test that would pass with the bed dropped, two change-detectors).

**Not fixed, by owner decision:** the mixed preview runs the full length of the
track (padding the drums), so `_preview_buf` holds a full copy of the audio. That
is the owner's explicit "full track length" choice; `play_section` is clamped, and
the variations path slices the bed to the drums' span.

New tests: `tests/test_context_mix.py` (35), `tests/test_context_mix_ui.py` (19),
plus 3 in `tests/test_analyze.py`, 6 in `tests/test_playback.py`, and 1 in
`tests/test_playhead.py`. Suite: 300 passing.
