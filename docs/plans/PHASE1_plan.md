# Phase 1 — Engine-as-library (FINAL, decisions locked)

Goal: make `engine` a clean importable library, add the 4 additive extensions, lock behavior with a golden-master regression test. **Hard constraint: `GENERAL_MIDI` output on fixed golden specs stays byte-identical to the current engine.**

## LOCKED (Plan-gate: forced by byte-identical constraint)
- **Output-map = resolve-at-build.** `build_song(spec, ..., output_map=GENERAL_MIDI)`, `note = output_map[inst]`. Events stay `(t, note, vel, dur)`.
- **half_time_shuffle = define-only.** Add groove + grooves.md entry; do NOT wire into barker/tre_cool pools. Opt-in via explicit `section["groove"]`.
- **Maps complete-keyed.** Both maps contain all 17 `GM` keys; `GENERAL_MIDI` == `GM` exactly. Incomplete = KeyError at `:563`.
- **_resolved_bar_rows scope:** helper = `_normalize` + `_apply_axes` + optional `_add_crash_accent` ONLY. groove_name/fill_name stay resolved in the section loop. build_song passes its OWN rng into the helper; helper never creates a Random.
- **W0 oracle frozen from ORIGINAL generate.py BEFORE W1**, fixed int seeds.

## DECISIONS (owner — RESOLVED)
- **A = All 7 axes per-section, humanize 3-tier kept.** `sec["axes"]` partial dict, per-key fallback to global. humanize resolves `sec.axes → spec.overrides → spec → profile` (keep its existing 3-tier; do not collapse). 4 shaping axes + breakdown + fill_prob use per-key `{**global, **sec.axes}`.
- **G = MIRROR.** resolved_bar replays the rng stream to a `(section, bar)` index so it EXACTLY equals the bar build_song renders (pre-jitter). Heavier/coupled, but UI edits the true pattern.
- **E = Ship EZ_DRUMMER_3 best-effort + note-ladder validator.** All 17 keys from Toontrack's GM-superset keymap, VALUES flagged UNVERIFIED. Add a note-ladder `.mid` generator to validate in EZD3. GENERAL_MIDI is the byte-identical default.
- **F = Author missing grooves.md entries now** (16 grooves + 9 fills) so list_* returns full descriptions.
- **D = pytest** dev dep (`requirements-dev.txt`), explicit install before W6.

## Engine facts (verified)
- `note = GM[inst]` at `:563`; global axes `:528–532`; humanize 3-tier `:532` (`ov.get("humanize", spec.get("humanize", prof["humanize"]))`).
- Per-bar `:551–572`: normalize → apply_axes (rng: ornament/double_bass/syncopation probabilistic) → crash (bar0) → per-step humanize jitter (rng). Fill bars bypass axes.
- `_resolve_groove` + fill decision + fill pick draw rng ONCE PER SECTION before per-bar apply_axes.
- grooves.md: 9/25 grooves (§3) + 4/13 fills (§4) documented parseably; rest §8 prose only.
- `song_from_profile` (:489) never emits `sec["axes"]`; per-section axes reach engine via raw specs the UI/controller builds (no plumbing added to song_from_profile this phase).

## Work items
- **W0 — Golden baseline FIRST.** From current generate.py, capture `build_song` events (json) for ≥4 specs (pop_punk w/ crash_in + fill; ramones; one with spec-level humanize; one using uncommon insts china/ride_bell/toms) at fixed int seeds → `tests/golden/*.json`. Oracle.
- **W1 — `engine/output_maps.py`.** `GENERAL_MIDI` (==GM, 17 keys), `EZ_DRUMMER_3` (17 keys, UNVERIFIED values), `list_output_maps()`. Wire `output_map` kwarg into build_song (default byte-identical). Golden after.
- **W2 — Per-section axes** (A). Per-key `{**global, **sec.get("axes",{})}` for 4 shaping + breakdown + fill_prob; humanize explicit 3-tier + optional `sec.axes["humanize"]`. Global-only path identical. Golden after.
- **W3 — `resolved_bar(spec, section_index, bar_index, seed, *, output_map=GENERAL_MIDI)`** (G=MIRROR) + extract `_resolved_bar_rows` (scope locked). Replays the section loop with a seeded rng, consuming every draw through the target bar's apply_axes, returns inst→[16 vels] PRE jitter — exactly the rows build_song uses at that position. build_song refactored to route per-bar resolution through the same helper. Golden after (the critical refactor).
- **W4 — List helpers.** `list_profiles/list_grooves/list_fills` → keys + descriptions from grooves.md (parsed). Depends on W6-doc authoring (F). Export from `__init__`.
- **W5 — `half_time_shuffle` groove** + §3 entry (define-only). Swung 16ths, ghost snare, backbeat on 3.
- **W6-doc — Author grooves.md** §3/§4 entries for the 16 + 9 undocumented (F).
- **W8 — Note-ladder validator.** Helper/CLI that emits a `.mid` playing each of the 17 insts once in sequence, for auditing a map (esp. EZ_DRUMMER_3) in EZD3. Uses the same `output_map` path.
- **W7 — `__init__` exports** (output maps, list_*, resolved_bar, note-ladder) + `import engine` smoke.
- **W9 — Tests** (pytest; install first): (a) golden == GENERAL_MIDI [THE guard]; (b) per-section axes: global-only byte-identical; axes-bearing identical up to first axes section; (c) resolved_bar MIRROR == build_song's actual pre-jitter rows at the same (section,bar) [now testable under G]; (d) list helpers return all keys + non-empty descriptions; (e) EZ_DRUMMER_3 has all 17 keys, differs from GM only by mapping.

## Sequencing
W0 → W1 → W2 → W3 (risky refactor) → W4/W5/W6-doc/W8 (parallel) → install pytest → W9 → W7. Golden test after W1, W2, W3 each.

## Risks
1. **W3 MIRROR replay fidelity** — replay must consume the exact same draw sequence as build_song (per-section groove/fill picks + per-bar apply_axes + per-bar jitter for skipped bars). Any divergence = resolved_bar lies. Test (c) + golden guard it. This is the heaviest item.
2. Per-section axis 0→nonzero crossing changes downstream draws — by design; test (b) asserts identity only up to first axes section.
3. EZD3 note values UNVERIFIED — flagged; validate via W8 ladder in EZD3.
4. grooves.md authoring — additive doc edit.

## Diff-gate
After implementation, before commit/push: spawn `code-reviewer` on the `git diff` (needs the restart that enabled it). Fix findings → commit → push.
