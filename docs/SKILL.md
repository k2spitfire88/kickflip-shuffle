---
name: pop-punk-drums
description: >
  Generate idiomatic pop-punk drum tracks as General-MIDI files for EZ Drummer 3,
  Superior Drummer 3, or Logic Pro. Use this whenever the user wants drums, a beat,
  a groove, or a drum MIDI part in a pop-punk / punk / Blink-182 / Green Day /
  New Found Glory style — including when they upload an audio file and want drums
  written to fit it, give a tempo and want a part built, or ask to develop or
  refine pop-punk drum patterns. Trigger even if they just say "make me a drum
  track" in a conversation that's about pop punk, and whenever EZ Drummer,
  Superior Drummer, EZD3, or SD3 come up alongside drum writing.
---

# Pop-Punk Drums

Produce a pop-punk drum part as a `.mid` file the user drags onto their EZ Drummer 3
track (or into any DAW). The output is General-MIDI-mapped, so it plays correctly
through EZD3, Superior Drummer 3, or Logic's stock instruments with no remapping.

## What this skill gives you

- A **groove library** tuned to the idiom: skank/double-time, surf-beat verses,
  16th kick doubles, ghost-note verses, crash-driven choruses, half-time
  breakdowns, ride-based pre-choruses.
- A **fill library** with the genre's rudimental/drumline flavor.
- A **generator** that assembles sections into a full arrangement, places fills at
  transitions, and humanizes velocity and timing.

The musical knowledge (why these grooves, what tempos, how to arrange) lives in
`references/grooves.md`. The engine lives in `scripts/generate.py`.

## Workflow

### Step 1 — read the reference
Read `references/grooves.md` first. It defines every groove and fill (with grid
notation), the tempo guide, the song-structure conventions, and the GM note map.
Don't write patterns from memory — use the library so the part is consistent and
idiomatic.

### Step 2 — establish the inputs
You need: **tempo** (BPM), **style/feel**, and ideally a **section map**. Sources:
- The user states them → use directly.
- The user uploads an **audio file** → analyze it for tempo, beat grid, section
  boundaries, and an energy curve (use `librosa`), then map louder sections to
  crash choruses and quieter ones to sparser verses. Confirm the detected tempo
  with the user, and ask whether the track was cut to a click (fixed grid) or
  loosely played (follow detected beats).
- Only a vibe is given → pick tempo from the reference's tempo guide and use a
  standard verse/chorus/bridge structure.

If the request is ambiguous on feel or structure and you can't infer it, ask one
focused question before generating — but a sensible default arrangement is better
than stalling.

### Step 3 — build a song spec
Assemble a JSON spec of sections. Each section names a groove, a length in bars,
and optionally a fill (on its last bar) and a crash entrance. Schema:

```json
{
  "ppq": 480,
  "humanize": 1.0,
  "sections": [
    {"groove": "verse_basic",  "bars": 8, "fill": "snare_buildup"},
    {"groove": "chorus_crash", "bars": 8, "crash_in": true, "fill": "tom_descend"},
    {"groove": "halftime",     "bars": 4},
    {"groove": "skank",        "bars": 4, "crash_in": true}
  ]
}
```

Groove names: `verse_basic`, `skank`, `surf`, `verse_doubles`, `verse_16th`,
`two_step`, `ramones_buzzsaw`, `four_floor`, `dbeat`, `blast_beat`, `ska_punk`,
`double_bass_verse`, `disco_punk`, `tribal_toms`, `emo_syncopated`,
`trap_hat_modern`, `halftime`, `breakdown_chug`, `gang_break`, `longview_tom`,
`chorus_crash`, `chorus_open_hat`, `chorus_ride_bell`, `chorus_doublebass`,
`verse_ride`.
Fill names: `tom_descend`, `snare_buildup`, `halfbar_toms`, `triplet_snare`,
`ramones_crash`, `dbeat_roll`, `marching_toms`, `sparse_tom`, `double_bass`,
`blast`, `china_choke`, `linear`, `tom_around`.

### Profiles and the parameter space (covering the whole genre)

Pop punk spans many eras and subgenres, so the engine models the *axes* the genre
varies along; a band is a point in that space, not a hardcoded special case. A
**profile** is a named coordinate that sets a tempo, per-role groove pools, a fill
pool, and feel axes: `ghost` (ghost notes), `ornament` (hi-hat filigree /
ride-bell), `double_bass` (16th double-kick density), `syncopation` (kick
push/displacement), `breakdown` (chance a bridge becomes a half-time chug), and
`humanize` (looseness; lower = tighter). Profiles are grouped by era: generic
(`pop_punk`), first-wave (`ramones`), '90s skate (`tre_cool`, `offspring`,
`mxpx`, `skate_punk`), 2000s mall (`barker`, `good_charlotte`, `simple_plan`,
`new_found_glory`, `sum41`, `fall_out_boy`, `all_time_low`), emo crossover
(`paramore`, `jimmy_eat_world`), easycore/2010s (`easycore`, `neck_deep`),
revival/2020s (`revival_2020s`, `pop_punk_pop`), and ska-punk (`ska_punk`).
Run `python scripts/generate.py --list-profiles` to see them with their axes.

Use a profile two ways:
- Quick: `python scripts/generate.py --profile easycore --tempo 182 --out d.mid`
  builds a standard arrangement, picking grooves per section from the profile.
- In a spec: set `"profile": "<name>"` at the top level and use `"role"`
  (`intro`/`verse`/`chorus`/`bridge`) instead of `"groove"` to let the profile
  pick; set `"fill_at_end": true` to let it choose a fill. With a `breakdown`
  axis > 0, `bridge` sections may resolve to a `breakdown_chug`/`gang_break`.

**Reaching a point no preset covers** (a band you don't have a profile for, or
the user's own song): set `"overrides"` to dial axes directly — e.g. snotty fast
early Green Day is `tre_cool` + `{"tempo": 200, "ornament": 0.2, "ghost": 0.2}`;
heavier metalcore-leaning easycore (A Day To Remember territory) is `easycore` +
`{"double_bass": 1.0, "breakdown": 1.0, "ghost": 0.3}`. This is the intended way
to fit any band or song, not just the named ones.

Follow the arrangement conventions in the reference: choruses get
`chorus_crash` + `crash_in`, transitions get a fill on the leading section's last
bar, verse 2 can be busier than verse 1, bridges contrast via `halftime` or `skank`.

### Step 4 — generate
Run the generator with the user's tempo and your spec:

```bash
python scripts/generate.py --tempo <BPM> --song spec.json --out pop_punk_drums.mid --seed 1
```

(Use `--seed` for repeatable humanization so you can regenerate the same part.)
For a quick demo without a spec, omit `--song` to use the built-in full arrangement.

### Step 5 — deliver and offer refinement
Save the `.mid` to the outputs directory and present it. Tell the user the
arrangement (section breakdown and tempo) and remind them it's an idiomatic
starting point: in EZD3 they can swap kits, set the snare to rimshot on backbeats,
run velocity/humanize, and audition Bandmate/Tap2Find variations. Offer to adjust
tempo, swap grooves per section, change fills, or rebalance energy.

## Editing patterns by hand

To add or tweak a groove, edit the `GROOVES` dict in `scripts/generate.py`. Each
groove is a 16-step (16th-note) bar: either a `{step: velocity}` dict or a full
16-element list. Step 0 = beat 1, step 4 = beat 2, step 8 = beat 3, step 12 = beat
4; the "&" of a beat is 2 steps after it. Ghost notes ≈ velocity 38-45, body hits
≈ 78-95, accents ≈ 95-114. Fills are functions returning a one-bar groove.

## Notes on other tools

- **Superior Drummer 3**: same GM file works. For SD3's extended articulations
  (extra hat openings, flams, choke), hover a drum in SD3 to read its mapped note
  and adjust the note numbers in the groove.
- **Logic Pro**: the MIDI imports straight onto a software-instrument track. If the
  user wants on-the-fly note remapping or humanizing inside Logic, a Scripter
  (JavaScript) MIDI plugin can do it — offer to write one.
- This skill writes MIDI only; it can't audition audio or operate the plugin GUI.
