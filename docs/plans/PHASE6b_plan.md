# Phase 6b — Undo/redo for the arrangement editor (DRAFT for Plan-gate)

Spec-snapshot undo/redo living in the controller (owner call 2026-07-03), wired to
Edit-menu Undo/Redo + shortcuts. Covers every arrangement mutation (sections,
per-section fields, 16-step grid, tempo). New-document loads reset the stack.

## Owner decisions (LOCKED 2026-07-03)

- **Spec-snapshot stack in the controller** — deep-copied JSON specs; each tracked
  mutation pushes the pre-edit spec; undo/redo swaps the current spec. Simple,
  headless-testable, uniform across all edit types. Depth-capped (100).
- **Undo history is NOT persisted** in `.ppd` (already locked in 6a).

## Facts (verified)

- Controller spec-mutating methods today: `update_section`, `set_sections`,
  `set_bar_pattern`, `clear_bar_pattern` (arrangement edits) and the load
  boundaries `song_from_profile`, `build_spec_from_ui_state`, `load_project`,
  `spec_from_analysis`.
- **Tempo has no dedicated mutator** — `generate_view._on_bpm_changed` rebuilds the
  whole spec via `build_spec_from_ui_state(profile, sections=…, tempo=value)`. So
  `build_spec_from_ui_state` is used for BOTH bpm edits and fresh construction and
  cannot be a blanket reset boundary.
- Controller is plain Python (no Qt) — it cannot refresh the UI; the UI must
  re-read `controller.spec` after undo/redo.

## Controller changes (`app/controller.py`) — headless, unit-tested

1. State: `self._undo = []`, `self._redo = []`, `_HISTORY_CAP = 100`.
2. `_snapshot()` (private): if `self._spec is not None`, append
   `copy.deepcopy(self._spec)` to `_undo` (drop oldest past cap) and clear `_redo`.
   Call at the TOP of each tracked mutator, before the change.
3. `_reset_history()` (private): clear both stacks. Call in the load boundaries
   `song_from_profile`, `build_spec_from_ui_state`, `load_project`,
   `spec_from_analysis`.
4. Add **`set_tempo(value)`**: mutate `self._spec["tempo"] = float(value)` in place
   with a `_snapshot()` first; `_invalidate_preview()`. (Replaces the bpm rebuild —
   see UI change 8. This is why bpm no longer routes through
   `build_spec_from_ui_state`, so tempo edits are tracked, not reset.)
5. Wire `_snapshot()` into the mutators, skipping true no-ops (plan-gate):
   - `set_bar_pattern`, `set_sections`: snapshot at top (always change).
   - `clear_bar_pattern`: snapshot INSIDE the `if patterns:` branch (a clear with
     no override present must not push a phantom undo step).
   - `update_section`: snapshot only `if fields` (an empty call changes nothing).
   - `set_tempo`: guard-before-snapshot (item 4).
6. `undo()` / `redo()`:
   - `undo()`: if `_undo`, push `deepcopy(self._spec)` to `_redo`, set
     `self._spec = self._undo.pop()`, `_invalidate_preview()`, return True; else
     False.
   - `redo()`: symmetric.
   - `can_undo()` / `can_redo()` booleans for action enable-state.
   Deepcopy on the way onto `_redo` so the live spec and the stacked copy never
   alias.

## UI changes

7. **`main_window.py`** — Edit menu: Undo (`Ctrl+Z`), Redo (`Ctrl+Shift+Z`).
   Handlers call `controller.undo()/redo()` then
   `generate_view.load_current_spec(generate_view.current_section_index() or 0)` to
   re-sync timeline/editor/grid/bpm. Enable-state (`can_undo/can_redo`) refreshed:
   on `generate_view.arrangementChanged`, after undo/redo, and on the Edit menu's
   `aboutToShow` (belt-and-suspenders so the QAction — hence its shortcut — is
   always current).
8. **`generate_view.py`** — `_on_bpm_changed` calls the new `controller.set_tempo(
   value)` instead of `build_spec_from_ui_state`. Add a single
   `arrangementChanged = Signal()`, emitted from the existing handlers
   `_on_section_edited` (SectionEditor.changed), `_on_sections_changed`
   (SectionTimeline.sectionsChanged), the StepGrid `edited` connection, and
   `_on_bpm_changed`. `build_spec_from_ui_state` stays a reset boundary (still the
   fresh-construction entry point; no longer on the bpm path).

## Risks / guards

- 🟡 **bpm snapshot spam** — a QSpinBox drag fires `valueChanged` per integer step,
  each snapshotting. Acceptable (cap bounds it); optional debounce noted as a
  follow-up, not in scope. Do NOT snapshot when the value is unchanged
  (`set_tempo` no-ops if `float(value) == spec["tempo"]`).
- 🟡 **Undo across a document load** — loads reset history, so you cannot undo past
  an Open/New/profile-switch. Intended.
- 🟡 **Selection after undo** — `current_section_index()` may exceed the restored
  section count; `load_current_spec` already clamps (6a).
- 🔵 **Snapshot before vs after** — snapshot-before-mutation means the stack holds
  pre-edit states; the live spec is the newest. Verified consistent with the
  undo/redo swap above.
- 🔵 **Browser apply** — `apply_groove/fill_to_current_section` route through
  `update_section`, so browser edits become undoable for free.

## Test plan (`tests/test_undo.py`)

- Controller: edit → undo restores prior spec; redo re-applies; `can_undo/redo`
  transitions; new edit after undo clears redo; `set_tempo` tracked + no-op when
  unchanged; load boundaries reset history; deepcopy isolation (undo target not
  aliased); cap enforced (oldest dropped).
- UI (offscreen): make a section edit, Undo menu → timeline reflects revert; Redo →
  reapplied; bpm change is undoable; Undo disabled at history bottom.

## Files

- `app/controller.py` (history stacks, `_snapshot`/`_reset_history`, `set_tempo`,
  `undo`/`redo`/`can_undo`/`can_redo`, wire mutators + reset boundaries)
- `app/ui/main_window.py` (Edit menu + enable-state)
- `app/ui/generate_view.py` (bpm → `set_tempo`, `arrangementChanged` signal)
- `tests/test_undo.py` (new)
