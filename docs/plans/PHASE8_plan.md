# Phase 8 — Enhancements (DRAFT for Plan-gate)

Post-core polish, built now that F1–F4 + persistence (6a) + undo/redo (6b) +
packaging (7) are solid. Phase 8 is a **menu of independent features**, each
shippable alone with its own diff-gate + commit. This doc plans all of them and
proposes a build order; implement incrementally.

Nine items = the eight `BUILD_PLAN.md` §"Phase 8" enhancements + the **playhead**
deferred out of Phase 6.

## Proposed sub-phase order (value-vs-cost, each a standalone commit)

| Sub | Feature | Why here |
|-----|---------|----------|
| 8a | Drag-out MIDI | Highest value, small surface — completes the core UX |
| 8b | Verify EZ Drummer 3 map | Owner-in-loop note audition; promote out of UNVERIFIED |
| 8c | Playhead | Transport polish; the one Phase-6 carry-over |
| 8d | Section markers in export | Small engine touch, high DAW value |
| 8e | Section lock on regenerate | Medium; changes the regen model |
| 8f | Tap tempo + half/double-time toggle | Small UI + per-section feel |
| 8g | Count-in / click track | Playback render addition |
| 8h | Batch variations (N seeds) + A/B compare | Larger; audition UX |

Recommend shipping **8a** first, then reassess. Items are independent — the order
can change without rework.

## Owner decisions (LOCKED 2026-07-03)

- **8b = VERIFY the existing `EZ_DRUMMER_3` map, not add new ones.** Owner only owns
  EZ Drummer 3, so unverifiable presets (SD3/AD2/GGD) are out. 8b becomes: audition
  `Controller.write_note_ladder(path, output_map="EZ_DRUMMER_3")` in EZD3, correct
  any wrong articulation notes in `output_maps.py`, then remove `EZ_DRUMMER_3` from
  `UNVERIFIED_MAPS`. (This is also the standing CLAUDE.md open follow-up.) The note
  correction + promotion is a manual/owner-in-the-loop step.
- **8e = structural-only lock.** Pin `section["groove"]` + `fill` before a reseed so
  the locked section keeps the same part; humanize jitter may still re-roll (NOT
  byte-identical audio). Full pattern/jitter freeze is explicitly out of scope.
- **8h — batch variations + A/B stays IN Phase 8.**

## Per-sub-phase design

### 8a — Drag-out MIDI (`QDrag` + file URL)
- New `DragExportButton`/widget in `generate_view` transport: on drag-start, render
  the current spec to a `.mid` in a temp/cache dir (reuse `controller.export` to a
  managed path), build a `QDrag` carrying a `QMimeData` with the file URL
  (`setUrls([QUrl.fromLocalFile(path)])`), and start the drag.
- Reuse the held seed so the dragged file == the previewed/exported one.
- **Resolved (plan-gate):** file-based drag (QDrag needs a file URL). Render via
  `controller.export` to a managed path in `tempfile.gettempdir()/kickflip-shuffle/`
  (created lazily; no such convention exists yet — add one). File must exist BEFORE
  `QDrag.exec()`; register temp files for cleanup on `MainWindow.closeEvent`. Do NOT
  reuse the 6a `_last_export` path (that's the user's chosen export, separate).
- Risk 🟡: temp dir lifetime must outlive the drag. Files: `generate_view.py`, small
  `app/ui/drag.py` (temp-dir + QDrag helper).

### 8b — Verify the EZ Drummer 3 output map
- Owner auditions `engine.note_ladder` for `EZ_DRUMMER_3` in EZ Drummer 3
  (`Controller.write_note_ladder(path, output_map="EZ_DRUMMER_3")`), reports which
  articulations land wrong; correct those note numbers in `output_maps.py`; then
  remove `EZ_DRUMMER_3` from `UNVERIFIED_MAPS` (drops the "(unverified)" tag in the
  picker). New unverifiable presets (SD3/AD2/GGD) are OUT — owner can't validate.
- Risk 🔵: purely the note-value correctness, which only the sampler audition can
  confirm — this sub-phase is owner-in-the-loop, not autonomous. Files:
  `output_maps.py`; test still asserts every map defines all 17 `ROLES` and
  `GENERAL_MIDI == GM`.

### 8c — Playhead
- `QTimer` (~30 Hz) in `generate_view`, started on play / stopped on stop, polling
  `controller.playback_position` (seconds). Convert to (section, bar, step) via
  spec tempo/ppq/section bars and draw a position line on the `StepGrid` (and/or a
  cursor on the timeline). Stop-reset on end.
- **Resolved (plan-gate):** `controller.playback_position` returns 0.0 when there is
  no player (before first play) — so GATE the playhead on transport, not on polling
  position: start the QTimer in the play handler, stop+reset it in the stop/finish
  handler (don't infer "stopped" from position==0). `Player.position` = seconds
  (`cursor/sample_rate`); `sec_per_tick = 60 / (tempo * ppq)`.
- Risk 🟡: position→grid mapping must match the render's tempo/bar math; timer must
  not fire after `shutdown()` (tear it down there). Files: `generate_view.py`,
  `editor_widgets.py` (StepGrid paint overlay).

### 8d — Section markers in export
- Emit MIDI markers at section boundaries so the DAW timeline shows the arrangement.
  `build_song`/`write_midi` currently pass flat `(tick,note,vel,dur)` events with no
  section info. Additive approach: `build_song` also returns/attaches a list of
  `(tick, label)` section boundaries; `write_midi` gains an optional `markers=` param
  writing `MetaMessage("marker", name=…, time=…)`. Default path unchanged (no
  markers) → **golden stays byte-identical**.
- **Resolved (plan-gate):** do NOT change `build_song`'s signature. Add a separate
  read-only `engine.compute_section_markers(spec) -> [(tick, label)]` that walks the
  sections computing cumulative ticks (bars × ppq × beats_per_bar); `write_midi`
  gains `markers=None` (writes `MetaMessage("marker")` only when passed — default
  path byte-identical). **Label source:** `section.get("label")` → else `role` →
  else `groove`; add an optional `section["label"]` field (additive, ignored by
  build_song). `controller.export` computes markers from the spec and passes them.
- Risk 🟡: `markers=None` default keeps golden byte-identical (verify). Files:
  `engine/generate.py` (`compute_section_markers`, `write_midi` param),
  `controller.export`, golden test unaffected.

### 8e — Section lock on regenerate
- Add optional `section["locked"] = True`. `new_seed()`+regenerate: for locked
  sections, pin the currently-resolved `groove` (and `fill`) into the section dict
  BEFORE reseeding so `_resolve_groove` uses the explicit value (no rng draw);
  unlocked sections re-`_pick` off the new seed. UI: a lock toggle per timeline row.
- **Resolved (plan-gate):** `resolved_bar` returns pattern ROWS, not the groove
  name — so add `controller.resolved_groove(section_index) -> name` (reads the
  seed-resolved pick via the engine's `_resolve_groove`/`_pick` path) to read what to
  pin. `_resolve_groove` early-returns on `section["groove"]` (verified), so pinning
  freezes it. `locked` is an additive section key (build_song/write_midi/
  `_prune_patterns`/persistence ignore unknown keys — verify persistence round-trips
  it).
- Risk 🟡: pin BEFORE reseed; a regenerate-with-locks is a tracked undo edit
  (snapshot once). Files: `controller.py` (`resolved_groove`, regenerate-with-locks),
  `editor_widgets.py` (lock toggle), `generate_view.py`.

### 8f — Tap tempo + half/double-time toggle
- Tap tempo: a button; average inter-tap intervals → BPM → `controller.set_tempo`
  (already tracked/undoable from 6b). Half/double: per-section toggle that scales
  the section's feel — either a `feel` field the engine honours or a groove swap;
  confirm whether this maps to an existing axis/groove or needs an engine field.
- **Owner decision (LOCKED): full engine `feel` field** = `section["feel"]` in
  `{normal (default/absent), half, double}`, time-scaling that section's bars.
- **Tap tempo:** a "Tap" button; average recent inter-tap intervals -> BPM ->
  `controller.set_tempo` (tracked/undoable). Reset the tap buffer after a long gap
  (>2 s). No engine change.
- **Feel = per-section bar-duration scale.** A bar's tick width becomes
  `STEPS * step_ticks * feel` where `feel` = 1 (normal) / 2 (half, bar twice as
  long) / 0.5 (double, bar half as long). Step spacing within the bar scales the
  same way, so the groove keeps 16 steps but plays slower/faster.
  - **`_iter_bars` must switch from `bar_index * STEPS * step_ticks` to a CUMULATIVE
    running `bar_start`** (bars are no longer uniform width). Absent/`normal` feel =
    scale 1.0 -> identical to today -> **golden byte-identical** (guard).
  - **Downstream tick consumers must all use the same cumulative/scaled math:**
    `compute_section_markers` (section start ticks), `resolved_bar` (its `target`
    is a bar COUNT, not ticks — likely unaffected, but the rows themselves don't
    depend on feel; verify), and the playhead `_position_to_grid` (seconds->bar/step
    must account for per-section feel). List every consumer; a missed one =
    playhead/marker drift on feel!=normal sections.
  - **Integer scaling via (num, den)** (plan-gate): `normal=(1,1)`, `half=(2,1)`,
    `double=(1,2)`. `scaled_step_ticks = step_ticks * num // den`;
    `scaled_bar_ticks = STEPS * step_ticks * num // den`. At ppq=480
    (step_ticks=120) all stay integral; document that ppq must be divisible by 8
    for `double`.
  - **dur scales with feel** (plan-gate 🔴 resolved): note dur =
    `max(1, scaled_step_ticks - 2)` (keep the 2-tick gap, proportional). Normal ->
    `step_ticks - 2` unchanged.
  - **`feel` is independent of 8e lock** — locking freezes groove/fill only, not
    feel. `feel` is an additive section key; set via update_section (tracked); a
    feel control in the section editor.
  - `compute_section_markers` AND `_position_to_grid` MUST both iterate sections
    accumulating `scaled_bar_ticks` (not uniform `bar_index * bar_ticks`). New 8f
    tests use a cumulative-aware tick helper (not the uniform one in
    `tests/test_patterns.py`).
- Risk 🔴: golden byte-identity for the cumulative-bar_start refactor (normal path
  must not move a single tick). Risk 🟡: every tick consumer must adopt scaled math.
  Files: `engine/generate.py` (_iter_bars, compute_section_markers, feel helper),
  `app/controller.py` (set_section_feel), `app/ui/generate_view.py` (_position_to_grid,
  tap tempo), `app/ui/editor_widgets.py` (feel control).

### 8g — Count-in / click track
- Add an optional click/count-in to the PREVIEW render only (not the export .mid):
  synth or sample a metronome for N beats before playback so the context mix lines
  up. `playback.render_events`/context-mix path gains a `count_in` option.
- **Resolved (plan-gate):** `render_events` is shared by `render_preview` AND
  `audition` AND (transitively) the export path — so do NOT add `count_in` to
  `render_events`. Instead WRAP: `render_preview` prepends N metronome beats/clicks
  to the buffer it returns (or renders a short click buffer and concatenates). Export
  never touches this path → exported MIDI stays clean automatically.
- Risk 🔵: keep it in the preview wrapper only. Files: `playback.py` (click helper),
  `controller.render_preview`, `generate_view.py`.

### 8h — Batch variations (N seeds) + A/B compare
- Batch: generate N seeds, render each, list to audition, "keep" one (sets held
  seed/spec). A/B: hold two rendered buffers + seeds, toggle between them.
- **Resolved (plan-gate):** the controller is NOT thread-safe — `render_preview`
  mutates `_spec`/`_preview_buf`/`_seed`, and `_RenderWorker` already warns of this
  (generate_view render disables edits during a render). So do NOT run N parallel
  workers. **SERIALIZE:** render each seed one at a time (single worker, a queue),
  each into a STANDALONE buffer via a non-mutating helper (mirror 5c's `audition` —
  render a deep-copied spec to a returned buffer without touching held state). A/B
  state (the (seed, buffer) pairs) lives in a dedicated `variations` UI component /
  controller helper, NOT in `_preview_buf`.
- Risk 🟡: N buffers = memory; sequential = slower but safe. Largest item; split
  batch vs A/B if needed. Files: new `app/ui/variations_view.py` (or dialog),
  `controller` batch/audition-to-buffer helpers.

## Cross-cutting

- **Golden byte-identity** stays the guard for any engine touch (8d markers, 8e
  lock, 8f feel): default path must not change. Verify per sub-phase.
- **Undo/redo** — new spec-mutating actions (8e lock, 8f) must snapshot via the
  existing tracked mutators or a new one; don't bypass the stack.
- Each sub-phase: plan-gate (if it touches the engine or is non-trivial) →
  implement → diff-gate → commit, per the project cadence.

## Test plan (per sub-phase)

- 8a: drag builds a real .mid at a URL (headless: assert the mime/url + file).
- 8b: every map in `OUTPUT_MAPS` defines all 17 `ROLES`; `GENERAL_MIDI` still ==
  `GM` (existing guard).
- 8c: position→(section,bar,step) mapping unit-tested against known tempo/ppq;
  timer stops on shutdown.
- 8d: `write_midi(markers=…)` writes marker metas; no-marker call byte-identical to
  today; golden green.
- 8e: locked section keeps its groove across a reseed; unlocked changes; undoable.
- 8f/8g: tap→BPM math; count-in only in preview, absent from export.
- 8h: N-seed batch renders; A/B holds two buffers; threads torn down.

## Files (superset — per sub-phase subsets)

- `engine/generate.py` (8d markers, 8e lock support, 8f feel), `engine/output_maps.py`
  (8b)
- `app/controller.py` (drag/export path, markers, locks, batch, count-in)
- `app/playback.py` (8g count-in)
- `app/ui/generate_view.py`, `app/ui/editor_widgets.py` (playhead, lock toggle,
  drag, tap tempo), possibly `app/ui/drag.py` / `variations_view.py`
- `tests/` per sub-phase
