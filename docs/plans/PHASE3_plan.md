# Phase 3 — Audio analysis (F2) (DRAFT for Plan-gate)

Goal: `app/analyze.py` — librosa audio → an editable analysis → engine song
spec. Fills the controller's `analyze_audio` stub. Analysis is approximate and
**correctable** (user edits before `build_song`).

## Owner decisions (LOCKED 2026-06-29)
- **Return a rich `AnalysisResult`**, not a spec. A separate
  `spec_from_analysis(result, profile, ...)` builds the engine spec → the
  correction layer (tempo/roles/alignment) sits between detection and build.
- **Sections = structural boundaries + energy labels.** librosa structural
  segmentation sets boundaries; per-segment RMS assigns roles; **fixed-bar-chunk
  fallback** when segmentation confidence is low.
- **Analysis is profile-agnostic.** Profile supplied at `spec_from_analysis`.
- **Tests = mock-librosa units + one real smoke** on a numpy-generated click track.

## Engine facts (verified)
- Section roles the engine honours: `intro`, `verse`, `chorus`, `bridge`
  (`prechorus`→verse, `outro`→chorus via ROLE_FALLBACK; breakdown only via a
  `bridge` section + `breakdown` axis). Pool keys: verse/chorus/bridge/intro/fills.
- 13 fills (`tom_descend`, `snare_buildup`, …). Spec sections carry
  `role|groove`, `bars`, `fill|fill_at_end`, `crash_in`, optional `axes`.
- `build_song` deterministic given seed; analysis itself is deterministic given
  the file (no rng — do NOT introduce any).

## Plan-gate fixes folded (2026-06-29, re-run critique)
All six must-fixes resolved below; MED/LOW folded inline. Verified librosa 0.11
facts: `beat_track` tempo needs `float(np.ravel(t)[0])` and can return 0.0 +
EMPTY beats on weak material; `feature.rms(y=)` → `(1,n)`, use `[0]`;
`segment.agglomerative(feature, k)` → boundary FRAME indices incl. 0, NOT the
final frame, deterministic (no rng).

## `app/analyze.py`
**`@dataclass AnalysisResult`** (plain types, JSON-friendly for Phase 6):
- `tempo: float` (coerced scalar), `sr: int`, `duration: float`, `alignment: str`
  (the *effective* alignment — may be downgraded to `fixed_grid`; see below)
- `beat_times: list[float]`, `downbeat_times: list[float]` (every `beats_per_bar`-th
  beat — naive 4/4; `[]` when no beats found, flagged)
- `segments: list[(start, end)]` (seconds; last `end` == `duration`)
- `segment_energy: list[float]` (mean RMS per segment, normalised 0..1; see
  zero-range rule)
- `sections: list[dict]` (`{role, bars, fill_at_end?, crash_in?}`)
- `confidence: dict` — `tempo: float 0..1` (beat-interval regularity, **computed**,
  not a fictional API field; `0.0` when no beats), `segmentation:
  "structural"|"fixed_fallback"` (which path produced the segments)

**`analyze_audio(path, *, alignment="fixed_grid", known_tempo=None, beats_per_bar=4) -> AnalysisResult`**
1. `y, sr = librosa.load(path, mono=True)` (default sr=22050, deterministic).
2. **Always** run `tempo_est, beat_frames = librosa.beat.beat_track(y=y, sr=sr)`
   (need `beat_times` for `follow_beats` even when tempo is known). Coerce
   `tempo_est = float(np.ravel(tempo_est)[0])`. Final `tempo = known_tempo if
   known_tempo else (tempo_est or DEFAULT_TEMPO=120)`. [BLOCKER #2 / MED coercion]
   - `confidence["tempo"]`: `0.0` if `beat_frames` empty; else
     `1/(1+CV)` where CV = stdev/mean of beat intervals (regularity proxy).
3. `beat_times = frames_to_time(beat_frames)`; `downbeat_times =
   beat_times[::beats_per_bar]` (→ `[]` when empty). [BLOCKER #2]
4. **Segments** — feed a FEATURE (not a recurrence matrix) to agglomerative:
   `feat = librosa.feature.mfcc(y=y, sr=sr)`; `n = feat.shape[1]`.
   - **Structural path** when `n >= 2*k_req` AND `duration >= MIN_BARS*bar_secs`:
     `k = min(k_req, n)`; `bounds = librosa.segment.agglomerative(feat, k)` (frame
     idxs incl. 0); convert to times; **append `duration` as the terminal end** so
     all `k` segments survive. `confidence["segmentation"]="structural"`. [HIGH #3,#4]
     - `k_req` from duration: ~1 segment / 8 bars, clamped `2..8`.
   - **Fixed-chunk fallback** otherwise (short audio / `n<2` / too few frames /
     beats empty): split `[0,duration]` into `MIN_BARS`-bar chunks on the tempo
     grid. `confidence["segmentation"]="fixed_fallback"`. This is the **computable**
     trigger (no fictional "instability" metric). [HIGH #5]
5. Per-segment mean RMS via `librosa.feature.rms(y=y)[0]`, averaged over each
   segment's frame span → `segment_energy`.
6. **Pure mapping helpers (unit-tested, no librosa):**
   - `_normalize(energies) -> list[float]` — `(x-min)/(max-min)`; **if `max==min`
     (≤1 segment or flat) → all `0.5`** (no div-by-zero/NaN). [BLOCKER #1]
   - `_label_roles(norm) -> list[str]` — first segment = `intro`; otherwise
     two-band: `>=0.5 → chorus`, `<0.5 → verse`. **No auto-`bridge`/`outro`** this
     phase (numeric criterion would be arbitrary; bridge stays a UI choice). Flat
     input → all `verse` after the `intro`. [MED roles]
   - `_alloc_bars(boundary_times, tempo, beats_per_bar) -> list[int]` — cumulative:
     `bar_pos[i]=round(t_i*tempo/60/beats_per_bar)`, `bars=diff(bar_pos)`, each
     `max(1, ·)`. Σ bars tracks total length (no independent-round drift).
     [MED #_bars_for drift]
   - `_sections_from(roles, bars, norm) -> list[dict]` — assemble `{role, bars}`;
     `crash_in=True` on `chorus`; `fill_at_end=True` on a section whose successor
     is louder (`norm[i+1] > norm[i]`). Last section: no fill. [MED last/quiet roles]
7. **Effective alignment:** requested `follow_beats` is honored ONLY if
   `downbeat_times` non-empty — boundaries snap to nearest downbeat before
   `_alloc_bars`. Else **downgrade to `fixed_grid`** (bars straight from tempo) and
   record the effective value in `result.alignment`. [BLOCKER #2]

**`spec_from_analysis(result, profile, *, overrides=None, ppq=480) -> spec`**
- Validate `profile in PROFILES`. Assemble `{ppq, profile, tempo: result.tempo,
  overrides: overrides or {}, sections: result.sections}`. Pure assembly (mirrors
  `build_spec_from_ui_state`). Note: engine `breakdown` needs a `bridge` section
  **and** a `breakdown` axis — analysis sets neither, so labels map to plain
  grooves. [MED bridge clarification]

## Controller wiring (`app/controller.py`)
- Implement `analyze_audio(self, path, *, alignment="fixed_grid", known_tempo=None)
  -> AnalysisResult` (delegates to `analyze` module; stores `self._analysis`).
- Add `spec_from_analysis(self, profile, *, result=None, overrides=None) -> spec`
  — `profile` first (consistent w/ module's `(result, profile)` positional order at
  call sites); `result` defaults to held `self._analysis`; stores spec as current.
  [LOW signature consistency]
- `analysis` read property.
- **Remove `analyze_audio` from the NotImplementedError stubs**; `render_preview`,
  `play`, `stop` stay stubbed (Phase 4).

## Tests
`tests/test_analyze.py` — **pure-helper units (no librosa):**
1. `_normalize`: spread → 0..1; **`max==min` → all 0.5** (no NaN); single elem → 0.5.
2. `_label_roles`: first=intro; `>=0.5`→chorus, `<0.5`→verse; flat → intro then
   all verse; never emits bridge/outro.
3. `_alloc_bars`: known boundary times/tempo → expected bars; each `>=1`; Σ tracks
   total (no per-segment drift); sub-bar segment floored to 1.
4. `_sections_from`: roles+bars+norm → sections; `crash_in` on chorus;
   `fill_at_end` only when successor louder; last section no fill.
5. `spec_from_analysis`: hand-built `AnalysisResult` → spec `build_song` accepts &
   renders (non-empty events); unknown profile → `ValueError`.
6. **Fallback (computable trigger)**: an `AnalysisResult`/inputs with tiny duration
   or `n<2*k` → `segmentation=="fixed_fallback"` and uniform fixed-chunk sections.
   Forced by the concrete condition, not a mocked "instability".
7. **Empty-beats guard**: `follow_beats` requested but `downbeat_times==[]` →
   effective `alignment=="fixed_grid"`, no crash; `confidence["tempo"]==0.0`.

**One real smoke (real librosa, `tmp_path`):**
8. Build a strong periodic click via `librosa.clicks(times=np.arange(0,8,0.5),
   sr=sr)` (120 BPM), `soundfile.write` → `analyze_audio(path, known_tempo=120)`.
   Robust asserts: `np.isfinite(result.tempo)`, `result.tempo==120` (plumbed, not
   estimated), `len(result.sections)>=1`, `build_song(spec_from_analysis(result,
   "pop_punk"))` non-empty. **Avoid** asserting estimated tempo / exact segment
   count / exact downbeat positions (estimator wobble). [HIGH #6]

`tests/test_controller.py` — **update**: drop `analyze_audio` from the stub-raises
parametrize. Controller wiring test **monkeypatches `app.analyze.analyze_audio`**
to return a hand-built `AnalysisResult` (fast, deterministic) → assert
`analyze_audio` stores it and `spec_from_analysis` flows to a build. Real pipeline
stays covered by smoke #8 only. [LOW controller test speed/determinism]

## Files
- `app/analyze.py` (new)
- `app/controller.py` (edit: implement analyze_audio + add spec_from_analysis)
- `tests/test_analyze.py` (new)
- `tests/test_controller.py` (edit: stub list)
No engine edits. No new deps (librosa/soundfile/numpy/scipy already in requirements).

## Sequencing
1. `analyze.py` dataclass + pure helpers (`_label_roles`/`_bars_for`/`_sections_from`).
2. `analyze_audio` (librosa load/tempo/segment/rms) + fallback + alignment.
3. `spec_from_analysis`.
4. Controller wiring + stub-list edit.
5. Tests (units first, then real smoke); full suite green (42 + new).

## Gates
- Plan-gate: built-in `Plan` agent critiques THIS draft → fold → owner approval.
- Diff-gate: `git add` → `pr-review-toolkit:code-reviewer` on `git diff --cached`
  → fix → commit (Co-Authored-By trailer) → push `main`.

## Risks
1. **Structural segmentation unreliability** — flaky on rubato/ambient; mitigated
   by computable fixed-chunk fallback + correction layer. Smoke uses clean clicks.
2. **Downbeat approximation** — every-4th-beat is naive; `[]` when no beats; real
   downbeat tracking deferred; `follow_beats` downgrades to `fixed_grid` if empty.
3. **librosa 0.11 shapes** — VERIFIED: `beat_track` tempo → coerce
   `float(np.ravel(t)[0])`, can be 0.0 + empty beats; `rms(y=)[0]`;
   `agglomerative(feat,k)` returns frame idxs incl. 0, NOT terminal — append it.
4. **Smoke-test estimator wobble** — assert plumbed `known_tempo`, finiteness,
   `>=1` section; never an estimated BPM or exact segment count.
5. **No randomness** — `load`/`beat_track`/`agglomerative`/`rms` all deterministic;
   do not add rng. NaN/empty branches (folded above) are the only crash risk.
