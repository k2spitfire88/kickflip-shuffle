# Phase 4 — Playback (F4) (DRAFT for Plan-gate)

Goal: `app/playback.py` — render a spec's drums to audio through bundled
FluidR3_GM via pyfluidsynth, play/stop/seek over `sounddevice`, and mix the
rendered drums over a loaded audio track ("hear it over my track"). Fills the
controller's `render_preview`/`play`/`stop` stubs.

## Owner decisions (LOCKED 2026-06-29)
- **Offline render -> numpy buffer -> sounddevice.** fluidsynth in synth-only
  mode (no audio driver); pull PCM with `get_samples`; `sounddevice` streams the
  pre-rendered buffer; transport = a frame cursor into it.
- **Full Phase 4 incl. context mix** — render drums over a loaded audio file.
- **Test the offline render with real fluidsynth + the sf2; gate device playback**
  (skip when no audio output device).

## Verified facts
- libfluidsynth 2.5.5 (brew) loads; `assets/soundfonts/FluidR3_GM.sf2` (142MB,
  RIFF) `sfload` OK; `program_select(9, sfid, 128, 0)` (GM drum bank) OK.
- `Synth(samplerate).get_samples(n)` -> int16 ndarray, interleaved stereo,
  length `2*n`; `np.asarray(s).reshape(-1,2)/32768.0` -> float stereo. A kick
  renders non-silent (peak ~0.08). Do NOT call `fs.start()` (that opens a live
  driver) — synth-only `get_samples` needs no device.
- Events from `build_song` are `(tick, note, vel, dur)` with concrete MIDI notes
  already baked via the output map, on channel 9. Tempo from `spec["tempo"]`,
  ppq from `spec["ppq"]` (build_song tempo param inert).

## Plan-gate fixes folded (2026-06-29)
All 7 must-fixes + HIGH/MED/LOW resolved below. Probe confirmed: fluidsynth render
is bit-deterministic even with default reverb/chorus ON; `get_samples(0)` is a safe
no-op; `sfload` returns `-1` (does NOT raise) on a bad path; `query_devices` works
here but can raise headless.

## `app/playback.py`
Module constant: `DEFAULT_SOUNDFONT = Path(__file__).resolve().parents[1] /
"assets/soundfonts/FluidR3_GM.sf2"`.

**Synth lifecycle — fresh per render (cache reversed).** The Plan-gate "cache the
synth" HIGH was tested and REVERSED: a reused synth + `system_reset()` is NOT
deterministic (reverb/voice state bleeds across renders → consecutive renders
differ). A FRESH `Synth` per `render_events` IS bit-deterministic, and loading the
mmap'd sf2 + rendering is only ~0.15s — negligible for preview. So: create a synth,
disable reverb+chorus, sfload, render, `fs.delete()` in `finally`.

**`render_events(events, *, tempo, ppq, sample_rate=44100, soundfont=DEFAULT_SOUNDFONT, tail=2.0) -> np.ndarray`**
- **Guard explicitly**: `if not Path(soundfont).exists(): raise FileNotFoundError(...
  download step ...)`. Fresh `Synth`; `setting("synth.reverb.active",0)` +
  `"synth.chorus.active",0` (determinism + dry stem to mix over a track); `sfload`,
  assert `sfid != -1` (sfload doesn't raise) else `RuntimeError`;
  `program_select(9, sfid, 128, 0)` (GM drums); `fs.delete()` in `finally`.
- Absolute-sample timeline (NO per-gap rounding drift): `on_i =
  round(tick/ppq*60/tempo*sr)`, `off_i = round((tick+dur)/ppq*60/tempo*sr)`.
  Collect `(sample_index, kind, note, vel)`; sort by `(index, off<on)`.
- Walk: between successive absolute indices render exactly `gap` frames via
  `get_samples(gap)` (gap may be 0 → safe no-op); apply `noteon`/`noteoff` (ch 9).
  Total length is EXACTLY `last_index + round(tail*sr)` — render the trailing tail.
  NOTE: GM bank-128 percussion are one-shots that IGNORE note-off; `dur`/offs don't
  truncate drum sound — natural decay is covered by `tail`, not by `dur`. [MED]
- `np.frombuffer/asarray` → `reshape(-1,2).astype(float32)/32768.0`. Return stereo
  `(n,2) float32`. Do NOT `delete()` the cached synth. Deterministic (no rng).

**`load_audio(path, *, sample_rate=44100) -> np.ndarray`** — `soundfile.read` →
`(frames, channels) float64`. Mono → duplicate to `(n,2)`. Resample with the
CORRECT axis when file sr differs (`librosa.resample(y.T, orig, target, axis=-1).T`
or per-channel) — wrong axis silently corrupts stereo. `astype(float32)`. [HIGH]

**`mix(drums, bed, *, drums_gain=1.0, bed_gain=0.8) -> np.ndarray`** — pad shorter
to longer; `out = drums*drums_gain + bed*bed_gain` (stays float32); peak-normalise
ONLY when `max|out|>1` (divide by scalar max). Both `(n,2) float32`, same sr. [LOW]

**`has_output_device() -> bool`** — `try: sd.query_devices(kind="output"); return
True except Exception: return False` (headless-safe). [MED]

**`class Player`** — `sounddevice` transport over a held buffer, the ONLY device
code (render/mix/load stay device-free/testable):
- `load(buffer, sample_rate)`, `play()`, `stop()`, `pause()`, `seek(seconds)`,
  `position -> seconds`, `is_playing`.
- **Callback** reads `buffer[cursor:cursor+frames]` into `outdata`; at end-of-buffer
  it **zero-fills the remainder of `outdata` and raises `sd.CallbackStop`** (else
  PortAudio repeats the last block). [MUST-FIX 1]
- **`cursor` guarded by a `threading.Lock`** — the callback runs on a realtime
  thread; `seek/pause/stop/play` mutate cursor from the control thread. All
  reads/writes under the lock. [MUST-FIX 2]
- **Lifecycle**: keep one `OutputStream`; `stop()`=abort+`cursor=0`, `pause()`=
  abort+keep cursor, `play()`=(re)`start()` (reopen if closed; never start a closed
  stream); `seek` clamps `cursor` to `[0, len(buffer)]`. [MED lifecycle, LOW seek]

## Controller wiring (`app/controller.py`)
- **Lazy-import** `playback` INSIDE `render_preview`/`play` (not at module top), so
  `generate`/`export` (which need no audio) still work if libfluidsynth/portaudio is
  missing or broken. Call **module-qualified** `playback.render_events(...)` and
  `playback.Player(...)` so tests can monkeypatch them. [MUST-FIX 4,7 / HIGH import]
- `render_preview(self, spec=None, *, seed=None, sample_rate=44100, with_context=False) -> np.ndarray`
  — build events with **GENERAL_MIDI** (preview = GM stand-in, consistent with
  `generate`; sf2 is a GM bank, EZD3 notes would mis-trigger). Held-seed contract
  (materialise + hold, like `generate`). `playback.render_events` (tempo/ppq from
  spec). If `with_context` and a context track is loaded, `mix` it. Holds
  `self._preview_buf`, `self._preview_sr`.
- `load_context_audio(self, path)` -> `self._context_audio` via `playback.load_audio`.
- `play(self)` — lazy-init `self._player` via `playback.Player`; **render-on-demand**
  if no preview held BUT a spec is available (uses current/held spec); if neither
  preview nor spec → **raise `ValueError`** (clear, no-spec path). `load` buffer +
  `play()`. [MUST-FIX 6]
- `stop(self)` — `self._player.stop()` if a player exists (else no-op).
- `seek(self, seconds)` / `playback_position` passthroughs to the player.
- `render_preview`/`play`/`stop` **lose their NotImplementedError stubs** — no
  Phase-4 stubs remain. Player opens its stream lazily on `play`, never at import.

## Tests
`tests/test_playback.py` — **module-level `skipif(not DEFAULT_SOUNDFONT.exists())`**
on all real-render tests (sf2 is gitignored → absent on a clean checkout/CI; this
is SEPARATE from the device gate). [MUST-FIX 3]
1. `render_events` on a 2-event spec -> `(n,2) float32`, peak `>0` (non-silent =>
   drum bank works), length **exactly** `last_on_index + round(tail*sr)` (we
   control the sample count — assert the exact frame count, not a tolerance). [MED]
2. Determinism: two renders of the same events are `array_equal` (holds with
   reverb/chorus on + cached synth via system_reset).
3. Channel-9 sanity: a single kick event renders non-silent. (Do NOT assert `dur`
   shortens audio — GM percussion ignores note-off.) [MED]
4. `mix`: drums + synthetic sine bed -> length == max(len), non-silent; silent bed
   leaves drums unchanged (drums_gain=1.0); >1 peak path normalises.
5. `load_audio`: write a wav (at a sr != 44100 to cover resample; and a mono file
   to cover mono->stereo) -> `(n,2) float32` at requested sr.
6. Missing soundfont: `render_events(..., soundfont=<bad path>)` raises
   `FileNotFoundError` (explicit exists() check, not sfload). [MUST-FIX 5]

`@pytest.mark.audio` + `skipif(not has_output_device())` (device-gated):
7. `Player.load(small_buffer)` + `play()` then `stop()`; cursor/state transitions
   (seek clamps; pause keeps cursor; stop resets) — asserts wiring, not sound.

`tests/test_controller.py` — drop `render_preview`/`play`/`stop` from the
stub-raises list (all three were stubs). Wiring tests **monkeypatch
`app.playback.render_events`** (return a tiny non-silent buffer) and
`app.playback.Player` (a fake recording load/play/stop) so NO real audio/device is
touched: assert `render_preview` holds the buffer + used GENERAL_MIDI; `play`
renders-on-demand then load/play; `play` with no preview AND no spec raises
`ValueError`; `stop` calls the player. (Real fluidsynth render covered only by
test_playback skipif-guarded tests.)

conftest: ADD the `audio` marker, KEEPING the existing `slow` line. [LOW]

## Files
- `app/playback.py` (new)
- `app/controller.py` (edit: render_preview/play/stop bodies + context audio + Player)
- `tests/test_playback.py` (new)
- `tests/test_controller.py` (edit: stub list + wiring)
- `conftest.py` (edit: `audio` marker)
No engine edits. Deps (pyFluidSynth, sounddevice, soundfile, numpy) all present.

## Sequencing
1. `render_events` + soundfont path/guard (the core; test 1-3,6 first).
2. `load_audio` + `mix` (tests 4-5).
3. `Player` (device-gated test 7).
4. Controller wiring (render_preview/play/stop/context) + stub-list edit + marker.
5. Full suite green (55 + new); device tests skip cleanly when headless.

## Gates
- Plan-gate: `Plan` agent critique -> fold -> owner approval. **If the spend
  limit blocks the agent, self-critique inline** (as in Phase 3) and flag it.
- Diff-gate: `code-reviewer` on `git diff --cached` (same spend-limit fallback)
  -> fix -> commit (Co-Authored-By trailer) -> push `main`.

## Risks
1. **Device in CI/headless** — only `Player` touches a device; render/mix/load are
   device-free. Device tests gated by `has_output_device()` (exception-safe) +
   `audio` marker. Render tests separately gated by `skipif(not sf2.exists())`.
2. **get_samples timeline drift** — use ABSOLUTE sample indices, render exact gaps;
   total length is `last_index + round(tail*sr)` (exact, asserted as a frame count).
3. **Preview vs export map** — render MUST use GENERAL_MIDI (GM sf2); EZD3 notes
   would mis-trigger. Locked to GM like `generate`.
4. **Audio-lib import coupling** — controller lazy-imports `playback`; importing
   never opens a stream; Player opens lazily on `play`. App MIDI path works without
   audio libs.
5. **Render determinism** — a REUSED synth bleeds reverb/voices and is NOT
   deterministic; use a FRESH synth per render with reverb/chorus OFF (bit-equal,
   verified). sf2 is mmap-fast (~0.15s/render), so per-call load is negligible.
6. **Soundfont absence on a clean checkout** — sf2 gitignored; render guards with an
   explicit `exists()` FileNotFoundError; tests skipif-guarded; Phase 7 bundles it.
7. **Realtime-callback races** — `cursor` shared callback/control thread → guarded by
   `threading.Lock`; callback zero-fills + `CallbackStop` at end.
8. **No new randomness** — render is deterministic; do not introduce rng.
