# Phase 2 — Controller + headless smoke test (DRAFT for Plan-gate)

Goal: `app/controller.py` exposing the Phase-1 engine to a future UI as an
in-process API, plus a headless pytest that generates + exports a `.mid` with no
UI. No music logic added — controller only orchestrates engine calls.

## Owner decisions (LOCKED 2026-06-28)
- **Form = stateful `Controller` class.** Holds: current spec, selected output-map
  name, last seed, (playback handle reserved for Phase 4). UI instantiates one.
- **Future-phase methods = stub now, raise `NotImplementedError("Phase N: ...")`.**
  Locks the API surface; Phases 3/4 fill bodies only.
- **`build_spec_from_ui_state` = thin explicit version.** Explicit args
  (profile, axes overrides, section dicts, tempo, ppq) → valid engine spec. No
  speculative ui_state object; real mapper firms up Phase 5/6.
- **`export` = explicit out_path only.** Fixed-folder + Save-As default deferred
  to Phase 6 (BUILD_PLAN puts it there).

## Engine API consumed (Phase 1, verified)
- `song_from_profile(profile_name, overrides=None) -> spec`
- `build_song(spec, tempo=None, seed=None, output_map=None) -> events` —
  note baked via `output_map[inst]`; default `GENERAL_MIDI`. **tempo param inert.**
- `resolved_bar(spec, section_index, bar_index, seed=None, output_map=None) -> rows`
- `write_midi(events, out_path, tempo=170, ppq=480) -> path` — channel 9.
- `list_profiles/list_grooves/list_fills()`, `list_output_maps()`, `get_output_map(name)`.
- Spec schema: `{ppq, profile, tempo, overrides:{axes...}, sections:[{role|groove, bars, fill|fill_at_end, crash_in, axes?}]}`.

## Controller surface
Read-only passthroughs: `list_profiles`, `list_grooves`, `list_fills`, `list_output_maps`.

Spec construction:
- `song_from_profile(profile_name, overrides=None) -> spec` — passthrough; stores as current spec.
- `build_spec_from_ui_state(profile, *, axes=None, sections=None, tempo=None, ppq=480) -> spec`
  — thin assembler. Validates `profile in PROFILES`; if `sections` None, fall back to
  `song_from_profile` arrangement. `axes` → `overrides`. `tempo` → spec tempo
  (default profile tempo). Per-section `axes` pass through untouched. Stores as current spec.

Generation (preview path, GENERAL_MIDI):
- `generate(spec=None, *, seed=None) -> events` — `spec` defaults to current spec.
  **seed**: if `seed` given, store it; else if a seed is already held, reuse it;
  else **materialize a concrete int** `random.randrange(2**63)` and store THAT.
  Always pass a concrete int (never `None`) to `build_song` so a later seedless
  `export` reproduces exactly what was generated. Uses `GENERAL_MIDI` (preview =
  GM stand-in per EZD3-boundary copy).  [Plan-gate CRITICAL #2]
- `resolved_bar(section_index, bar_index, *, spec=None, seed=None) -> rows` —
  `spec` defaults to current; seed resolves via the same held-seed logic (concrete
  int) for MIRROR consistency with `generate`.  [Plan-gate LOW: spec default]

Export:
- `export(out_path, *, spec=None, output_map=None, seed=None) -> path`
  — `out_path` first positional (locked: explicit path). [Plan-gate CRITICAL #1: a
  non-default param cannot follow `spec=None`.]
  - `spec` defaults to current; `output_map` defaults to held selection
    (default `GENERAL_MIDI`); `seed` **uses** the held seed (materializing one if
    none held) → **exported .mid == previewed events**, but does **NOT overwrite**
    the held seed (export is a sink; only `generate`/`set_seed` mutate it).
    [Plan-gate LOW: side-effect]
  - Resolve map name → dict via `get_output_map` (str accepted) or accept a dict.
  - **Tempo sourced from spec** via `spec.get("tempo", PROFILES[spec["profile"]]["tempo"])`
    and `ppq = spec.get("ppq", 480)` (NOT bracket access — hand-built specs may omit
    keys; `build_song` itself uses `.get`). Passed to `write_midi`. Guards invariant #6.
    [Plan-gate MEDIUM: KeyError]
  - Rebuilds events with the chosen map (build_song bakes notes), then write_midi.
- Seed accessors (UI lock/reroll/display): `seed` property (read held int),
  `set_seed(n)`, `new_seed() -> int` (draw+store+return). [Plan-gate MEDIUM]
- `spec` property — read current spec (UI arrangement/grid render). [Plan-gate MEDIUM]
- `set_output_map(name)` / `output_map` property — held selection for the UI picker.
- `write_note_ladder(out_path, *, output_map=None)` passthrough — articulation
  audition for the output-map picker / EZD3 verification. [Plan-gate MEDIUM]

Future-phase stubs (signatures locked, bodies raise):
- `render_preview(self, spec=None)` → `NotImplementedError("Phase 4: F4 playback render")`
- `analyze_audio(self, path)` → `NotImplementedError("Phase 3: F2 audio analysis")`
- `play(self, ...)` / `stop(self)` → `NotImplementedError("Phase 4: F4 transport")`

## Determinism contract
seed plumbed UI→engine. Controller holds the last-used seed so generate→export
with no explicit seed yields the SAME events. Explicit seed on either call
overrides and updates the held seed.

## Output-map / preview boundary
- Preview/generate always GENERAL_MIDI (GM stand-in; final kit in DAW).
- export applies the selected map; same spec+seed → different note numbers per map,
  identical rhythm/velocity/timing. EZD3 differs from GM ONLY at `tom_hi` (50→48)
  today (UNVERIFIED, owner-tracked follow-up).

## Headless test — `tests/test_controller.py` (pytest)
Helper: `read_events(path)` — re-read a `.mid` via `mido`, pair `note_on`/`note_off`
by accumulating delta times, reconstruct `(tick, note, vel, dur)` for comparison.
[Plan-gate MEDIUM: write_midi emits split on/off w/ deltas; duration compare needs pairing.]

1. `generate` from `song_from_profile("pop_punk")`, fixed seed → non-empty,
   tick-sorted events; tuple shape `(tick, note, vel, dur)`.
2. Determinism — TWO cases [Plan-gate HIGH #3]:
   (a) explicit: `generate(seed=N)` then `export(seed=N)` → exported == generated;
   (b) **seedless path** (the one that actually breaks): fresh controller,
   `generate()` no seed → capture events → `export()` no seed → `read_events` ==
   generated. Guards the None-materialization bug.
3. `export` GM → file exists; `read_events`; all notes ∈ `GENERAL_MIDI.values()`;
   channel == 9; `round(mido.tempo2bpm(meta.tempo)) == spec["tempo"]` (avoid
   lossy bpm2tempo round-trip). [Plan-gate MEDIUM]
4. `export` EZD3 vs GM, **seed pinned to emit `tom_hi`** (e.g. 123 — verified to
   emit toms; assert the diff is actually exercised, else vacuous). [Plan-gate HIGH #4]
   Build remap generically: `remap = {GM[r]: EZD3[r] for r in ROLES}` (GM injective).
   Assert every EZD3-export note == `remap[gm_note]`; ticks/vels/durs identical.
   Survives future EZD3 correction — does NOT hard-code 50→48. [Plan-gate MEDIUM]
   NOTE: real EZD3 articulation audition is manual/UNVERIFIED (owner follow-up via
   `write_note_ladder`) — test asserts MAPPING correctness, not sampler sound.
5. `build_spec_from_ui_state(profile, axes=..., sections=[...])` → spec that
   `build_song` accepts. Per-section `axes` honored — assert on **`resolved_bar`
   rows** for a section with `axes={"double_bass":1.0}` vs without (full-event
   compare is seed-flaky; double_bass only fills empty kick steps prob 0.6).
   [Plan-gate LOW: flaky]
6. Stubs (`render_preview`, `analyze_audio`, `play`, `stop`) raise `NotImplementedError`.
7. Seed accessors: `new_seed()` returns int & changes `seed`; `set_seed(n)` →
   `generate()` reproducible. `spec` property returns last-built spec.

No new golden specs; reuse engine determinism. Existing 23 tests must stay green.

## Files
- `app/__init__.py` (new — make `app` a package).
- `app/controller.py` (new).
- `tests/test_controller.py` (new).
No engine edits. No UI. No deps added (mido already present).

## Sequencing
1. `app/__init__.py` + `Controller` skeleton (state + passthroughs).
2. spec construction (`song_from_profile`, `build_spec_from_ui_state`).
3. `generate` + `resolved_bar` + determinism (held seed).
4. `export` (tempo from spec, map resolution).
5. stubs.
6. `tests/test_controller.py`; run full suite (must be 23 + new green).

## Gates
- Plan-gate: spawn built-in `Plan` agent to critique THIS draft → fold → owner approval.
- Diff-gate: `git add` → spawn `pr-review-toolkit:code-reviewer` on `git diff --cached`
  → fix → commit (Co-Authored-By trailer) → push `main`.

## Risks
1. **Determinism leak**: if export rebuilds with a fresh rng seed != generate's,
   exported .mid != preview. Root cause = forwarding `None` to build_song. Fixed by
   materializing a concrete held int; tests #2a/#2b guard both paths.
2. **Tempo invariant**: forgetting spec tempo → write_midi default 170 wrong.
   Sourced via `.get` w/ profile fallback; test #3 asserts tempo meta.
3. **Map-as-str vs dict**: export accepts both; `get_output_map` for names.
4. **EZD3 not auto-verifiable**: test asserts mapping correctness only (generic
   remap, not hard-coded values); sound audition = manual owner follow-up via
   `write_note_ladder`.

## Deferred (not Phase 2)
- Export-time warn on UNVERIFIED output map [Plan-gate LOW] — `list_output_maps`
  already surfaces the verified flag; UI can warn at pick time in Phase 5/6.
