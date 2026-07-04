# Pop-Punk Drumming Reference

Idiomatic knowledge for writing pop-punk drum parts as MIDI. Read this when you
need to choose grooves, set tempo, place fills, or hand-edit patterns. The
generator (`scripts/generate.py`) implements everything below.

## Contents
1. The sound: what makes drumming "pop punk"
2. Tempo guide
3. Groove library (with grid notation)
4. Fills
5. Song-structure conventions
6. General MIDI drum map
7. Humanization & mixing notes

---

## 1. The sound

Pop punk is punk-rock energy with cleaner production and pop song-craft. Drumming
is fast, driving, and built on a small number of grooves that get *embellished*
rather than replaced — the underlying beat rarely changes within a section; the
drummer fills the cracks with extra kicks, ghost notes, and rudimental flourishes.

The signature ingredients:
- **Snare on the upbeat.** The defining move. Where straight rock puts the snare
  on 2 and 4, fast pop punk often puts it on *every upbeat* (the "&"s) — the
  "skank" or double-time polka beat. This is the single most genre-identifying
  groove.
- **Driving 8th-note hats**, frequently opened up ("sloshy") for aggression, and
  moved to the **crash on every quarter note** in choruses for a wall of sound.
- **16th-note kick doubles** — quick double strokes on the bass drum, usually
  leading into the snare. At fast tempos these need heel-toe/slide technique
  live, but in MIDI they're just two close 16ths.
- **Drumline/rudimental DNA.** Travis Barker brought marching-snare vocabulary in:
  single-stroke rolls, paradiddles, triplet snare figures, ghost notes. Fills
  often cascade down the toms as single-stroke rolls.
- **Surf and hip-hop inheritance.** The surf beat ("boom, duh-duh, boom, duh" —
  an extra snare on the & of 2) and occasional syncopated/hip-hop kick patterns
  show up, especially in verses.
- **Energy over polish.** Backbeats are often rimshots; the part should feel like
  it's surging forward.

Touchstone drummers/bands: Travis Barker (Blink-182), Tré Cool (Green Day),
Cyrus Bolooki (New Found Glory), plus the surf/drumline lineage behind them.

---

## 2. Tempo guide

Pop punk runs fast. Rough map (4/4 throughout):

| Feel | BPM | Notes |
|------|-----|-------|
| Mid-tempo anthem | 140-165 | Roomy backbeats, big choruses (e.g. "American Idiot" ~165-189) |
| Classic pop punk | 165-190 | The sweet spot; most Blink/NFG up-tempo tunes |
| Fast / skank | 185-210 | Double-time snare, galloping kick; the genre's high gear |
| Half-time *feel* | (host tempo) | Same BPM, snare on 3 only — for bridges/breakdowns |

When the user gives a tempo, trust it and anchor the grid there. If they only
give a vibe, pick from the table.

---

## 3. Groove library

Grid notation below: 16 cells = one 4/4 bar (16th notes). `x` = hit, `X` = accent,
`o` = open hat, `.` = rest. Beats fall on cells 1, 5, 9, 13.

### verse_basic — standard backbeat verse
```
Hat   X x x x X x x x X x x x X x x x   (8ths)
Snare . . . . X . . . . . . . X . . .   (2 & 4)
Kick  X . . . . . . . X . X . . . . .   (1, 3, &-of-3)
```

### skank — double-time / polka (the defining fast groove)
```
Hat   X . x . X . x . X . x . X . x .   (8ths)
Snare . . X . . . X . . . X . . . X .   (every upbeat)
Kick  X . . . X . . . X . . . X . . .   (every quarter)
```

### surf — surf-beat verse ("boom, duh-duh, boom, duh")
```
Hat   X x x x X x x x X x x x X x x x
Snare . . . . X . x . . . . . X . . .   (2, &-of-2, 4)
Kick  X . . . . . . . X . . . . . . .
```

### verse_doubles — verse with 16th kick doubles
```
Hat   X x x x X x x x X x x x X x x x
Snare . . . . X . . . . . . . X . . .
Kick  X . . . . . x x X . . . . . x x   (doubles before snare/bar end)
```

### verse_16th — busy 16th-hat verse with ghost notes (Barker "Down" flavor)
```
Hat   X x x x X x x x X x x x X x x x   (16ths)
Snare . . . . X . . g . . . . X . . g   (g = ghost note ~40 vel)
Kick  X . . . . . . . X . . x . . . .
```

### chorus_crash — crash on the quarters (big, open chorus)
```
Crash X . . . X . . . X . . . X . . .
Snare . . . . X . . . . . . . X . . .
Kick  X . x . . . . . X . x . . . . .
```

### chorus_open_hat — chorus riding open hats (less wall-of-sound)
```
Hat_o O o o o O o o o O o o o O o o o
Snare . . . . X . . . . . . . X . . .
Kick  X . . . . . . . X . x . . . . .
```

### halftime — bridge/breakdown, snare on 3 only
```
Hat   X . x . X . x . X . x . X . x .
Snare . . . . . . . . X . . . . . . .
Kick  X . . . . . . . . . . . X . x .
```

### verse_ride — calmer pre-chorus on the ride
```
Ride  X . x . X . x . X . x . X . x .
Bell  X . . . . . . . X . . . . . . .
Snare . . . . X . . . . . . . X . . .
Kick  X . . . . . . . X . . . . . . .
```

### two_step — two-step punk beat, kick on 1 and 3, backbeat on 2 & 4
### ramones_buzzsaw — relentless straight-8th buzzsaw, kick on every quarter
### four_floor — four-on-the-floor kick under a straight 2 & 4 backbeat
### dbeat — hardcore d-beat, backbeat 2 & 4 with the signature off-kick on the "e of 1"
### blast_beat — blast beat, full-tilt alternating kick/snare 8ths
### ska_punk — ska feel, rim backbeat with open-hat offbeat upstroke chops
### double_bass_verse — verse thickened with 16th double-kick clusters before the snare
### disco_punk — Fall Out Boy "Dance Dance" four-on-floor with open-hat offbeats
### tribal_toms — Paramore tom-driven groove, floor/low toms carrying the pulse
### emo_syncopated — mid-tempo emo with a syncopated kick and a ghost before 4
### trap_hat_modern — 2020s revival, trap-bounce 16th hats, sub kick, crisp snare
### breakdown_chug — easycore breakdown, china + half-time snare over chugging double kick
### gang_break — gang-vocal breakdown hit, crash + snare on 1 and 3, sparse
### longview_tom — Green Day "Longview" sparse tom-and-floor verse
### chorus_ride_bell — chorus riding the ride with bell accents on 1 and 3
### chorus_doublebass — big chorus, crash quarters over 16th double-kick
### half_time_shuffle — Barker/Purdie half-time shuffle: backbeat on 3, swung 16th hats, ghost snares
### marching — Latin/marching backbeat (Green Day "Holiday") with 16th snare accents and a floor-tom kick-back
### garage_stomp — big loose Motown/garage stomp (Green Day "Father of All" era): four-on-floor kick, huge 2 & 4, open-hat offbeats
### linear_tom — Dave-Douglas-style linear tom weave: syncopated kick, ghosted snare, tom fills folded into the groove

---

## 4. Fills

Pop-punk fills are short (half a bar to a bar), high-energy, and often
rudimental. The generator provides:

- **tom_descend** — single-stroke roll cascading down the toms over the last two
  beats. The workhorse fill into a chorus.
- **snare_buildup** — 16th-note snare with a crescendo (70→120 velocity). Classic
  pre-chorus lift.
- **halfbar_toms** — groove for the first half-bar, tom flurry on the second.
- **triplet_snare** — snare triplet figure into the downbeat (Barker-ism).
- **ramones_crash** — a bar of straight 8ths capped with a crash; no-frills '77 turnaround.
- **dbeat_roll** — galloping d-beat roll driving into the downbeat.
- **marching_toms** — rudimental marching-snare/tom flurry (the drumline DNA).
- **sparse_tom** — minimal single tom-hit pickup that leaves space.
- **double_bass** — double-kick burst under a snare accent.
- **blast** — a short blast-beat burst used as a fill.
- **china_choke** — a china hit choked into the downbeat.
- **linear** — linear fill: no two limbs strike together (kick/snare/tom interlock).
- **tom_around** — classic tom-around-the-kit, high tom down to floor.

Placement convention: put a fill on the **last bar** of a section that leads into
a new section (verse→chorus, chorus→verse). Don't fill every 4 bars mechanically;
fills mark transitions. Pair a fill with a `crash_in` on the section it leads to.

---

## 5. Song-structure conventions

A typical pop-punk arrangement:
```
Intro (2-4 bars, often a drum hook or the verse groove)
Verse 1 (8 bars)            -> snare_buildup or tom fill into chorus
Chorus 1 (8 bars, crash)    -> tom_descend back to verse
Verse 2 (8 bars)
Chorus 2 (8 bars, crash)
Bridge/breakdown (4-8 bars, halftime or skank for contrast)
Final chorus (8 bars, crash) -- sometimes doubled or with a tag
```
Choruses get the crash-driven groove and a crash accent on the downbeat
(`crash_in: true`). Bridges earn their contrast by dropping to half-time or
jumping to the double-time skank. Verses 2+ can be busier than verse 1
(16th hats, ghost notes) to keep momentum.

---

## 6. General MIDI drum map

EZD3, SD3, and Logic's instruments all read these. Start here; for SD3's extra
articulations, hover a drum in its interface to see the mapped note and adjust.

| Instrument | Note | Instrument | Note |
|-----------|------|-----------|------|
| Kick | 36 | Crash 1 | 49 |
| Side stick / rim | 37 | Crash 2 | 57 |
| Snare | 38 | Ride | 51 |
| Closed hi-hat | 42 | Ride bell | 53 |
| Pedal hi-hat | 44 | Splash | 55 |
| Open hi-hat | 46 | Hi tom | 50 |
| | | Mid tom | 47 / 48 |
| | | Low tom | 45 |
| | | Floor tom | 43 |

Drums live on MIDI channel 10 (zero-indexed channel 9).

---

## 7. Humanization & mixing notes

- **Velocity.** Accent downbeats (~95-114), keep ride/hat body around 78-90, drop
  ghost notes to ~38-45. The generator jitters velocity ±~8.
- **Timing.** A few ticks of micro-timing jitter keeps it from sounding
  programmed. Don't overdo it at fast tempos — pop punk is tight.
- **Rimshots.** For an authentic snare crack, set EZD3's snare articulation to
  rimshot on the backbeats.
- **Let EZD3 do the rest.** After importing, use EZD3's velocity editor,
  humanize, and Bandmate/Tap2Find features to refine. This MIDI is a strong,
  idiomatic *starting point* — not a finished performance.

---

## 8. Influence streams and the profile/axis system

Pop punk isn't one sound — it's a confluence. The groove library is organized so
each stream is represented, and the profile system lets you blend them:

- **Surf** → `surf` (the "boom, duh-duh, boom, duh" extra snare on the & of 2).
- **'77 punk / Ramones / power-pop** → `ramones_buzzsaw` (relentless 8ths, driving
  kick), `four_floor`.
- **Hardcore / skate punk** (Descendents, NOFX, Bad Religion) → `dbeat`, fast
  `skank`; profiles `skate_punk`, `mxpx`.
- **Ska-punk** → `ska_punk` (rim backbeat, open-hat offbeat chops).
- **Emo / mid-tempo crossover** → `halftime`.
- **Melodic / sparse** (Green Day "Longview") → `longview_tom`.
- **Hip-hop & drumline** (Travis Barker, Tré Cool's rudiments) → ghost notes in
  `verse_16th`, ride-bell in `chorus_ride_bell`, and the `marching_toms` /
  `triplet_snare` fills.

### The parameter space

A band is a *point*, not a category. The axes:

| Axis | What it controls |
|------|------------------|
| `tempo` | center of gravity (see the tempo guide) |
| role pools | which grooves a verse/chorus/bridge draws from |
| `fills` + `fill_prob` | which fills, and how often transitions get one |
| `ghost` | ghost-note presence (0 = none) |
| `ornament` | hi-hat filigree and ride-bell flips (0-1) |
| `double_bass` | 16th double-kick density (0-1) — NFG, easycore, Sum 41, FOB |
| `syncopation` | kick displacement / push (0-1) — disco-punk, emo |
| `breakdown` | chance a bridge becomes a half-time chug (0-1) — easycore |
| `humanize` | timing/velocity looseness (lower = tighter, cleaner) |

### Built-in profiles by era

Run `python scripts/generate.py --list-profiles` for the live table.

| Era | Profiles |
|-----|----------|
| generic | `pop_punk` (broad default, samples whole library) |
| first wave / '77 | `ramones` |
| '90s skate | `tre_cool`, `offspring`, `mxpx`, `skate_punk` |
| 2000s mall | `barker`, `good_charlotte`, `simple_plan`, `new_found_glory`, `sum41`, `fall_out_boy`, `all_time_low` |
| emo crossover | `paramore`, `jimmy_eat_world` |
| easycore / 2010s | `easycore`, `neck_deep` |
| revival / 2020s | `revival_2020s`, `pop_punk_pop` |
| ska-punk | `ska_punk` |

### New grooves and fills in the wider library

Grooves added for the subgenres: `two_step`, `blast_beat`, `double_bass_verse`,
`disco_punk` (FOB "Dance Dance" offbeat-hat feel), `tribal_toms` (Paramore
tom-driven), `emo_syncopated`, `trap_hat_modern` (2020s 16th-bounce hats over a
sub kick), `breakdown_chug` (china-on-quarters half-time), `gang_break` (open
half-time for gang vocals), `chorus_doublebass`. Fills added: `double_bass`,
`blast`, `china_choke`, `linear`, `tom_around`.

### Reaching any band or song

Because bands are points, anything between or beyond them is reachable by
overriding axes. One profile covers a band's whole range: early Green Day's
snotty speed is `tre_cool` + `{tempo: 200, ornament: 0.2, ghost: 0.2}`; the
*American Idiot* militancy is `tre_cool` + `{tempo: 175, ornament: 0.7,
fill_prob: 1.0}` with `marching_toms` fills. A heavier, metalcore-leaning
easycore (A Day To Remember territory) is `easycore` + `{double_bass: 1.0,
breakdown: 1.0, ghost: 0.3}`. For a band with no profile, start from the nearest
one and dial the axes, or start from `pop_punk` and narrow. This is how the
generator stays broad enough to encompass the genre rather than a fixed roster.
