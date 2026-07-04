# Apply-era-to-your-song + Lock tempo (DRAFT for Plan-gate)

Make the workflow "upload a song, set its BPM, generate drums in a specific
drummer-era's style at that BPM" work end-to-end. Today the Era dropdown REBUILDS
a fresh default arrangement at the era's midpoint tempo — discarding an uploaded
song's structure and the user's BPM. This changes era selection on an EXISTING
spec to **re-flavor in place** (keep sections + tempo), and adds a **Lock tempo**
toggle so Regenerate doesn't re-roll a chosen BPM.

## Owner decision (LOCKED 2026-07-04)

- Build it. Plan-gate before implementing.

## Facts (verified)

- Groove resolution reads `profile_view(spec["profile"], spec.get("era"))` for
  pools + axis globals (`_iter_bars`). So setting `spec["era"]` on an EXISTING
  role-based spec makes its sections resolve from the era pools — no rebuild
  needed.
- Dropped-song sections are ROLE-based (`analyze.spec_from_analysis` → `result.
  sections` = `[{role, bars, fill_at_end?, crash_in?}]`), so they re-flavor.
  Explicit-groove sections (locked / browser-applied / hand-set) keep their groove
  — expected.
- `song_from_profile(era)` currently: rebuilds default arrangement + era midpoint
  tempo + `tempo_range`, resets undo. `_on_era_changed` calls it (rebuild).
- `regenerate` re-rolls `spec["tempo"]` within `spec["tempo_range"]` if present.
  So "no re-roll" = drop `tempo_range`.
- INVARIANT so far: `song_from_profile` is the only writer of `spec["era"]` and it
  co-writes `spec["tempo"]`. New writer `apply_era` runs on a spec that ALREADY has
  a tempo, so `spec["tempo"]` stays present — the tempo fallbacks stay valid.

## Controller changes (`app/controller.py`)

1. `apply_era(era, *, keep_tempo=True)`: re-flavor the CURRENT spec, keeping
   sections. Snapshot first (undoable — it's an edit, NOT a new document, so do
   NOT `_reset_history`). Then:
   - `era` truthy → `spec["era"] = era`; falsy → `spec.pop("era", None)`.
   - `keep_tempo=True` → keep `spec["tempo"]`; `spec.pop("tempo_range", None)`
     (Regenerate won't re-roll — pins the user's BPM).
   - `keep_tempo=False` → set `spec["tempo"]` = era midpoint + `spec["tempo_range"]`
     from `profile_view(profile, era)` (Regenerate explores the era's range).
   - `_invalidate_preview()`. Returns the spec.
2. `set_tempo_locked(on)`: `on` → `spec.pop("tempo_range", None)`; `off` → restore
   the current era's range (from `profile_view`) if an era is set. Tracked
   (snapshot) — it changes regenerate behaviour, minor; or untracked (a transport
   setting). Recommend UNtracked (it's a mode, not a musical edit).

## UI changes (`app/ui/generate_view.py`)

3. **`_on_era_changed`**: when a spec exists, call `apply_era(era,
   keep_tempo=self.lock_tempo.isChecked())` instead of `song_from_profile`
   (rebuild). Refresh the editor preserving the section selection (timeline/grid/
   bpm). Era switching now KEEPS your song + (optionally) tempo.
   - Profile selection (`_on_profile_selected`) is UNCHANGED — picking a new
     drummer still builds a fresh default song.
4. **Lock tempo** `QCheckBox` by the BPM stepper → `controller.set_tempo_locked`.
   Auto-check it in `_on_spec_built` (a dropped song has a target BPM to keep).
5. Status hint: "Applied <era> — kept your song + tempo."

## Drop-audio path

- Already: Drop builds a spec (flat profile, analyzed/known tempo, role sections)
  → `specBuilt` → Generate `load_current_spec` → era combo populates for that
  profile. With change #3, picking an era there re-flavors the dropped song at its
  BPM. No Drop-view change needed beyond auto-locking tempo (#4). (If the drop
  profile is flat/eraless, no era combo — user first picks an era-capable drummer
  in the Drop profile list.)

## Risks / guards

- 🟡 **era-without-tempo invariant** — `apply_era` sets era but not tempo
  (keep_tempo). Safe only because the current spec already has a tempo; assert/
  require a held spec. Never call `apply_era` on a spec lacking `tempo`.
- 🟡 **only role-based sections re-flavor** — explicit-groove sections (8e lock,
  browser-apply, manual groove) keep their groove. Intended; surface nothing, but
  document. A freshly-dropped or freshly-profiled song is all role-based → fully
  re-flavors.
- 🟡 **undo** — `apply_era` snapshots (undoable, restores prior era/tempo/range).
  It does NOT reset history (keeps the document). Regenerate/seed still not in
  undo (unchanged).
- 🔵 **tempo_range lifecycle** — apply_era(keep_tempo) drops range; profile switch
  rebuilds flat (no range). No stale range leaks. `.ppd` round-trips era +
  tempo_range as-is.
- 🔵 **golden** — apply_era mutates only the held runtime spec; build_song on fixed
  golden specs is untouched. No golden risk.

## Test plan (`tests/test_apply_era.py`)

- `apply_era("<era>")` on a role-based spec: sets era, KEEPS sections + tempo,
  drops tempo_range; grooves now resolve from era pools (a role section's resolved
  groove is in the era's pool). Undoable (snapshot restores prior era/tempo).
- `apply_era(era, keep_tempo=False)`: sets era midpoint + tempo_range.
- `apply_era(None)`: clears era → flat resolution.
- `set_tempo_locked(True)` drops tempo_range so `regenerate` keeps tempo;
  `False` restores range so regenerate re-rolls.
- UI: era change on an existing spec keeps sections (count unchanged) + tempo;
  Lock-tempo checkbox drives keep_tempo; dropped-song (specBuilt) auto-locks.
- Integration: build a role-based spec at a set tempo → apply an era → tempo
  unchanged, section count unchanged, resolved grooves come from the era pool.

## Files

- `app/controller.py` (`apply_era`, `set_tempo_locked`)
- `app/ui/generate_view.py` (`_on_era_changed` → apply, Lock-tempo checkbox,
  `_on_spec_built` auto-lock)
- `tests/test_apply_era.py` (new)
