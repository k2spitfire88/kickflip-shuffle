# Phase 5a-ii — Arrangement editor + editable 16-step grid (DRAFT for Plan-gate)

Goal: full arrangement editing on top of the 5a-i Generate view —
- **Arrangement timeline**: add / remove / reorder sections.
- **Per-section editor**: role | groove | fill | crash_in + 7 per-section axis sliders.
- **Editable 16-step grid** (`QPainter`): edits the REAL pattern via a new additive
  engine extension (`section["patterns"]` override) and regenerates/exports it.

## Owner decisions (LOCKED 2026-06-30)
- **Everything now** (timeline + per-section editing + grid in one phase).
- **Grid is editable via an additive engine extension** — a per-bar pattern
  override `build_song` uses verbatim when present; the groove-resolution path is
  unchanged when absent, so `GENERAL_MIDI` golden output stays byte-identical.

## Plan-gate fixes folded (2026-06-30)
8 must-fixes + MED/LOW resolved below. Verified: `_resolved_bar_rows` is the ONLY
per-bar rng consumer (section draws sit above the loop) → golden holds iff
`_bar_override` is a pure dict lookup with zero draws on the `None` path; `ROLES`
== the 17 `GM` keys and `output_maps.py` fails at import if a registered map omits
a role → `omap[inst]` total for override keys ⊆ `GM`.

## Engine extension (`engine/generate.py`) — additive, golden-guarded
Today (verified): `_iter_bars` per bar does `rows = _resolved_bar_rows(...)`
(normalize + `_apply_axes` [rng draws] + optional crash), then humanize jitter at
event emission. `resolved_bar` and `build_song` both consume `_iter_bars`, so they
mirror by construction.

**Shape:** a section may carry `"patterns": {bar_index: {inst: [16 vels]}}` —
a per-BAR override (the grid edits one (section, bar) at a time). JSON round-trips
make keys strings; accept `int` or `str` bar keys. Values are POST-normalize,
PRE-jitter velocities (0..127) — exactly what `resolved_bar` returns and the grid
edits.

**Pipeline change** (in `_iter_bars`, per bar `b`):
```
ov_rows = _bar_override(sec, b)              # sec["patterns"][b], normalized, or None
if ov_rows is not None:
    rows = ov_rows                           # verbatim; SKIP _resolved_bar_rows
else:
    rows = _resolved_bar_rows(base, sec, b, bars, want_fill, fill_name, ax, rng)
```
- Override bar uses the user's rows directly (no re-`_apply_axes`, no re-crash —
  the edited rows already are the final pre-jitter pattern). Humanize jitter still
  applies at emission (events stay the playback/export source).
- **rng:** an overridden bar skips that bar's `_apply_axes` draws, so the stream
  shifts for LATER bars — by design (it is an edited song, not the baseline). The
  section-level draws (`_resolve_groove`, fill pick) still happen so the
  arrangement stays coherent. A spec with NO `patterns` anywhere consumes the
  identical draw sequence → **golden byte-identical** (the guard).
- `resolved_bar(si, bi)` for an overridden bar returns the override (same
  `_iter_bars` path → mirror preserved).

**Helpers:**
- `_bar_override(sec, b)`: PURE dict lookup, ZERO rng draws, no control-flow change
  on the `None` path (golden invariant — state in docstring). Reads `sec.get(
  "patterns")`, matches `b` accepting int OR str key, returns a **deep copy** of the
  rows (never a live alias into the spec — else `resolved_bar` would hand the UI a
  mutable reference that bypasses validation/invalidation) or `None`. [HIGH alias]
- `_validate_pattern(rows)`: **RAISE `ValueError`** (not clamp) when any key ∉ `GM`,
  any value is not a length-`STEPS` list of ints, or any vel ∉ 0..127. Empty `{}`
  and all-zero rows are LEGAL (a silent bar — emits no events, draws no jitter).
  [MED clamp-vs-raise]
- **Bar-key normalization**: store/read bar keys as **int** everywhere. `_bar_override`
  coerces; `set_bar_pattern` writes int; `.ppd` load coerces str→int; so `0` and
  `"0"` can never coexist. [MED int/str]

**Engine tests** (extend `tests/`):
- Existing golden suite UNCHANGED → byte-identical guard still green (no `patterns`).
- Override honoured: a spec with `patterns` on (section s, bar b) → that bar's
  events derive from the override notes/velocities; bars BEFORE it identical to the
  no-override spec.
- **Later-bar mirror WITH override** [HIGH]: add a spec containing a mid-song
  override to `test_resolved_bar.py::SPECS` so `resolved_bar(b+k) ==` build_song's
  bar `b+k` is asserted for bars AFTER the override (the property the rng-shift
  reasoning rests on).
- `resolved_bar(s, b)` == the override for an overridden bar; the returned dict is a
  COPY (mutating it does not change the spec).
- Malformed override (bad inst / wrong length / non-int / out-of-range vel) →
  `ValueError`; empty/all-zero override → a silent bar, no crash.
- **Export across maps with override** [MED]: `write_midi` with `EZ_DRUMMER_3` + an
  override using a non-groove voice (e.g. cowbell) — locks the `ROLES`==`GM` total-map
  guarantee.

## Controller (`app/controller.py`)
**Do NOT route per-section/arrangement edits through `build_spec_from_ui_state`** —
it stores `sections` verbatim AND rebuilds `overrides={}` from scratch, so it would
drop `patterns` and reset globals. Instead mutate the existing spec/section dicts in
place. [CRITICAL drop]
- `set_bar_pattern(section_index, bar_index, rows)`: `engine._validate_pattern(rows)`;
  `self._spec["sections"][si].setdefault("patterns", {})[int(bar_index)] =
  deepcopy(rows)`; invalidate preview; return spec.
- `clear_bar_pattern(section_index, bar_index)`: delete `int(bar_index)` (and a
  stray str form) from the section's `patterns`; drop the dict if empty; invalidate.
- `set_sections(sections)`: reorder/add/remove using the ACTUAL existing dict
  references (so `patterns`/unknown keys survive); assign `self._spec["sections"]`;
  **prune** each section's `patterns` entries with `bar >= section["bars"]`;
  leave profile/overrides/tempo/ppq untouched; invalidate.
- `update_section(index, **fields)`: copy the EXISTING section dict, overlay only the
  changed fields (role/groove/fill/crash_in/bars/axes), write back; if `bars` shrank,
  **prune** out-of-range `patterns`; invalidate. Never rebuilds the whole spec. [CRITICAL]
- `resolved_bar` already reads overrides through `_iter_bars` (returns a copy).
- **Invalidate the held preview buffer** (`self._preview_buf = None`) on EVERY spec
  mutation AND on `set_seed`/`new_seed` (a reroll changes the render but is not a spec
  edit — `play()` gates on `_preview_buf`, so a stale buffer would replay the old
  render). [MED seed-invalidation]

## UI
New widgets (`app/ui/`), wired into the Generate view (the keyart empty-state area
becomes the editor once a profile is selected):
- `section_timeline.py` — `SectionTimeline(QWidget)`: a horizontal row of section
  chips (role + bars); **Add**/**Remove**/**move-left/right** buttons; selecting a
  chip emits `sectionSelected(index)`. Drives `controller.set_sections`.
- `section_editor.py` — `SectionEditor(QWidget)`: for the selected section —
  role `QComboBox` (intro/verse/chorus/bridge), groove `QComboBox`
  (`list_grooves`, + "(from role)" = unset), fill `QComboBox`
  (`list_fills` + "none"), crash_in `QCheckBox`, bars `QSpinBox`, and 7 axis
  `QSlider`s (0..100 -> 0..1) labelled by axis. Changes -> `controller.update_section`.
- `step_grid.py` — `StepGrid(QWidget)`: a `QPainter` grid with a FIXED row per role
  in **canonical `ROLES` order** (all 17, stable — not dict order, and lets the user
  ADD a voice not yet in the bar). [MED row-order, add-instrument] 16 columns (beats
  shaded every 4). Cells seeded from `resolved_bar(si, bi)` (missing roles = zeros).
  A bar selector (`QSpinBox`) picks the bar; **clamp it to the section's `bars` on
  every refresh** (a shrunk section would otherwise `IndexError`). [MED selector] Click
  a cell -> toggle on/off (full velocity); each edit builds the override =
  `{role: row for role in ROLES if any(row)}` and calls `controller.set_bar_pattern`.
  "Reset bar" -> `clear_bar_pattern` (re-seed from the regenerated `resolved_bar`).
  `sizeHint`/`minimumSize` set.
- `generate_view.py`: host the three widgets; on profile-select / regenerate /
  section change, refresh timeline + editor + grid from `controller.spec` /
  `resolved_bar`. Keep BPM/seed/transport/export from 5a-i. Block signals on
  programmatic widget refresh (as in 5a-i).

State coupling: every edit goes through the controller; the spec stays the single
source of truth; preview buffer invalidated on edit (re-render on next Play).

## Tests (`tests/test_ui.py`, offscreen; + engine/controller tests)
UI (monkeypatched playback as in 5a-i):
1. Timeline Add appends; Remove shrinks; move-left/right reorders (assert order);
   move guarded at ends; selection follows the moved chip.
2. SectionEditor: role/groove/fill/crash_in/bars -> the selected section dict
   updates; an axis slider sets `section["axes"][k]`. Programmatic refresh blocks
   signals on combos/spinboxes/sliders.
3. StepGrid shows 17 `ROLES` rows; seeded cells match `resolved_bar(si, bi)`.
4. Grid cell click -> `set_bar_pattern` called; `spec["sections"][si]["patterns"]
   [bi]` set (int key); `resolved_bar` returns the edit; "Reset bar" clears it;
   adding a role not previously present works (palette is all 17 roles).
5. **Preserve override through an arrangement edit** [HIGH]: set an override, then
   reorder via the timeline / `update_section` -> the override survives at the right
   (section, bar). Plus: a seed reroll invalidates the preview buffer.
6. Regression: existing 5a-i tests still pass (profile/BPM/output-map/export).
Controller/engine: the engine + controller tests above (golden, override-honoured,
later-bar mirror, validation-raises, key normalization, patterns-preserved).

## Sequencing
1. Engine `patterns` override + helpers + engine tests (golden FIRST, must stay green).
2. Controller `set_bar_pattern`/`clear_bar_pattern`/`set_sections`/`update_section`
   + preview-invalidation + tests.
3. `SectionTimeline` + wiring + tests.
4. `SectionEditor` + wiring + tests.
5. `StepGrid` (render then edit) + wiring + tests.
6. Full suite green (83 + new); manual `python main.py` smoke.

## Gates
- Plan-gate: `Plan` agent critique (esp. the engine rng/golden reasoning + the
  pattern shape) -> fold -> owner approval.
- Diff-gate: `code-reviewer` on `git diff --cached` -> fix -> commit -> push.

## Risks
1. **Golden byte-identical** — the override path must be unreachable without
   `patterns`; engine golden suite is the guard (run after the engine change FIRST).
2. **rng-stream shift on override** — intended; documented; `resolved_bar` mirror
   still holds (same `_iter_bars`). Don't try to "preserve" draws for overridden bars.
3. **Pattern validation** — malformed overrides must raise, not silently corrupt.
4. **JSON str bar-keys** — `_bar_override` accepts int or str keys (Phase-6 .ppd
   persistence round-trips as str).
5. **UI breadth** — three new widgets; keep each thin and controller-driven; block
   signals on refresh; invalidate preview on edit.
6. **No new randomness**; engine override is deterministic given the spec.
