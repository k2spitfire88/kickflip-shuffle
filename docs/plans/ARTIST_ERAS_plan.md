# Artist eras — model B (era selector) (DRAFT for Plan-gate)

One profile per artist + an **era dropdown** that swaps the era's groove pools +
axis fingerprint + tempo, so a drummer covers their evolution (early Tré Cool ≠
American Idiot ≠ Saviors). Additive + golden-safe: a spec with no era behaves
exactly as today. See [[artist-era-model]].

## Owner decisions (LOCKED 2026-07-04)

- **Model B** (era selector on one profile), not era-variant profiles / wider pools.
- **Eras = curated style-break buckets**, hand-authored, owner-refined per artist.
- **Pilot artists = Green Day (`tre_cool`) + Relient K (`relient_k`)** with the era
  lists below; the other 19 artists follow later (same research→refine→plan loop).
- Process: I research + propose era buckets → owner refines the ones they know →
  fold into this plan-gate.

## Data shape (additive)

A profile MAY carry an ordered `eras` list; each era-block has the same fields the
flat profile has today:

```
PROFILES["tre_cool"] = _p(era="90s_skate", tempo=180, verse=[...], ..., **axes,
    eras=[
      {"label": "Dookie–Nimrod (94–97)", "tempo": 182,
       "verse": [...], "chorus": [...], "bridge": [...], "intro": [...],
       "fills": [...], "ghost": .., "ornament": .., ... 7 axes ..},
      {"label": "Warning (2000)", ...},
      ...
    ])
```

- The flat top-level pools/axes/tempo stay as the **default** (era=None → today's
  behaviour, byte-identical). The `eras` blocks are the selectable variants.
- `spec` gains an optional `era` (the era `label`). Persisted in `.ppd` with the
  rest of the spec; absent in old files → default (backward-compatible).

## Engine changes (`engine/generate.py`) — golden-critical, additive

1. **`profile_view(profile_name, era=None) -> dict`**: returns the EFFECTIVE
   `{verse, chorus, bridge, intro, fills, tempo, + 7 axes}`.
   - **era=None ⇒ return the flat `PROFILES[name]` object UNCHANGED** (same dict,
     no copy-mutation) — this is the byte-identity guarantee (plan-gate 🔴).
   - **era set ⇒ return a NEW merged dict** (never mutate `PROFILES`): the
     era-block's fields over the flat profile.
   - **Pools (`verse/chorus/bridge/intro/fills`) are REQUIRED-COMPLETE per
     era-block** — no partial pool fallback (partial pools would silently mix
     eras, plan-gate 🟡). **Axes + tempo MAY fall back per-key** to the flat
     profile (independent scalars, safe to inherit).
2. **`_iter_bars`** reads pools + axis globals from `profile_view(spec["profile"],
   spec.get("era"))` instead of `PROFILES[spec["profile"]]` directly. `_resolve_
   groove` / `resolved_section_grooves` / `resolved_bar` inherit it (they drive
   `_iter_bars`). **No era ⇒ flat profile ⇒ byte-identical (golden guard).**
3. **`song_from_profile(name, overrides=None, era=None)`**: tempo from
   `profile_view(name, era)` (NOT the flat `PROFILES[name]["tempo"]` — plan-gate
   🔴); stores `spec["era"]=era` (omit key when None). Sections stay role-based;
   groove resolution picks from the era pools via step 2.
   - **INVARIANT (plan-gate 🟡):** `song_from_profile` is the ONLY writer of
     `spec["era"]`, and it ALWAYS co-writes `spec["tempo"]` from the era. So the
     many `PROFILES[profile]["tempo"]` fallbacks (export/render_preview/audition/
     build) stay correct — they only fire when `spec["tempo"]` is absent, which
     never happens for an era spec. Never inject `spec["era"]` by another path.
     `load_project`/`spec_from_analysis` need NO era param (era rides the loaded
     spec / analysis songs stay flat).
4. Re-export `profile_view`; `list_profiles()` gains an `eras: [labels]` field per
   profile (empty for flat profiles) so the UI can populate the picker.

## Controller changes (`app/controller.py`)

5. `song_from_profile(profile, overrides=None, era=None)` passthrough (+ store era).
6. `global_axes()` reads `engine.profile_view(spec["profile"], spec.get("era"))`
   so the section-editor sliders show the SELECTED ERA's fingerprint baseline.
7. `list_profile_eras(profile) -> [labels]` for the UI picker.

## UI changes (`app/ui/generate_view.py`)

8. An **Era** `QComboBox` beside/under the profile list. On profile select:
   populate eras (from `list_profile_eras`); hidden/disabled for flat profiles.
   Default selection = the profile's designated default era (or "— default —").
9. On era change → `controller.song_from_profile(profile, era=era)` →
   `_refresh_from_spec`. An era switch is a **new document** → controller resets
   undo history (like a profile switch); confirm profile-switch already does.
10. `AxisFingerprint` in the profile row may show the default-era axes (minor).

## Persistence / undo

- `spec["era"]` rides the existing `.ppd` save/load (whole-spec) — round-trips
  free. Old `.ppd` without `era` → default. `load_current_spec` already re-selects
  the profile; also re-select the era combo from `spec.get("era")`.
- Era switch rebuilds the spec → `_reset_history()` (new document), consistent
  with 6b.

## Pilot era content — DRAFT (owner to refine each pool/axis)

Grooves/fills below must all exist in `GROOVES`/`FILLS` (plan-gate verifies). These
are STARTING proposals from the research; the owner refines the ones they know.

### Green Day / `tre_cool` (one drummer; stylistic eras)
| Era | tempo | verse pool (draft) | signature axes |
|-----|-------|--------------------|----------------|
| Dookie–Nimrod (94–97) | 182 | skank, two_step, verse_basic, ramones_buzzsaw | ghost .4 orn .4 fill .8 |
| Warning (2000) transitional | 150 | verse_basic, surf, two_step | ghost .3 orn .5 fill .55 |
| American Idiot–21CB (04–09) | 160 | verse_basic, verse_doubles, tribal_toms, surf | ghost .5 orn .6 sync .3 fill .85 |
| ¡Uno!–Revolution Radio (12–16) | 172 | verse_basic, four_floor, skank, surf | ghost .4 orn .4 fill .7 |
| Father of All (2020) departure | 156 | four_floor, disco_punk, two_step | ghost .3 orn .3 sync .4 fill .5 hum .7 |
| Saviors (2024) classic return | 170 | verse_basic, two_step, skank, longview_tom | ghost .45 orn .5 fill .8 |

### Relient K / `relient_k` (lineup break at era 2)
| Era | tempo | verse pool (draft) | signature axes |
|-----|-------|--------------------|----------------|
| Relient K (2000) pre-Douglas | 172 | skank, verse_basic, surf, two_step | ghost .3 orn .3 fill .6 |
| Anatomy–Two Lefts (01–03) | 176 | verse_doubles, skank, surf, two_step | ghost .4 orn .6 sync .4 fill .85 |
| Mmhmm–Five Score (04–07) | 168 | verse_16th, verse_doubles, surf, emo_syncopated | ghost .5 orn .7 sync .5 db .2 fill .85 |
| FANSD (2009) | 165 | verse_16th, verse_doubles, emo_syncopated | ghost .5 orn .7 sync .6 db .2 fill .8 |

(Chorus/bridge/intro/fills per era drafted in the implementation; owner refines.)

## Risks / guards

- 🔴 **Golden byte-identity** — `profile_view(name, None)` MUST equal the flat
  profile exactly; `_iter_bars` with no era unchanged. Guard = golden test.
- 🟡 **`tre_cool`/`relient_k` current default output** — they're NOT in golden, but
  adding `eras` must not change their era=None output. Keep flat pools as-is; eras
  are additive.
- 🟡 **UI default era** — decide what era=None means for an era-profile: the flat
  default (current sound) or the profile auto-selects a designated era on load.
  Recommend flat default + the picker starts on a designated "signature" era only
  when the user opens the profile fresh (owner call).
- 🟡 **Undo/persistence** — era in spec; era switch resets history; `.ppd`
  round-trips era; old files default. Verify load re-selects the era combo.
- 🔵 **Axis-fingerprint viz** shows flat vs era axes — cosmetic; pick one.

## Test plan

- `profile_view(name)` == flat profile; `profile_view(name, era)` == era-block
  (with fallback for unspecified keys); unknown era → flat.
- Golden green (no-era path unchanged).
- `song_from_profile(profile, era=)` → era tempo + era-pool grooves resolve.
- Every era-block's pools ⊆ GROOVES, fills ⊆ FILLS (no runtime KeyError).
- controller.global_axes reflects the selected era; UI era picker rebuilds spec +
  resets undo; `.ppd` era round-trip; old `.ppd` (no era) loads as default.

## Files

- `engine/generate.py` (`profile_view`, `_iter_bars`/`song_from_profile` era read,
  `tre_cool`/`relient_k` `eras` data), `engine/__init__.py` (re-export)
- `app/controller.py` (era passthrough, `global_axes`, `list_profile_eras`)
- `app/ui/generate_view.py` (Era combo + wiring), `app/ui/editor_widgets.py` (n/a)
- `tests/test_eras.py` (new)
