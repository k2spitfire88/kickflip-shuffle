"""Playback (F4) — render a spec's drum events to audio through the bundled
FluidR3_GM soundfont (pyfluidsynth), play/stop/seek over sounddevice, and mix the
rendered drums over a loaded audio track ("hear it over my track").

Design (offline render -> buffer -> device):
  * `render_events` synthesises a whole song to a numpy float buffer with
    fluidsynth in synth-only mode (no audio driver) — deterministic and testable
    without any audio hardware.
  * `Player` is the ONLY component that touches an audio device; it streams a
    pre-rendered buffer via a sounddevice callback with a frame cursor.

Importing this module is side-effect free (no device opened, no stream started).
A fresh synth (with the soundfont) is created per render: reuse bleeds reverb/voice
state across renders and breaks determinism, while the sf2 is mmap-fast (~0.15s).
"""
import threading
from pathlib import Path

import numpy as np
import fluidsynth
import sounddevice as sd
import soundfile as sf

from app._bootstrap import resource_root
DEFAULT_SOUNDFONT = resource_root() / "assets/soundfonts/FluidR3_GM.sf2"


def click_track(beats, tempo, *, sample_rate=44100, freq=1000.0):
    """A `beats`-beat metronome count-in as a stereo float32 buffer at `tempo`.
    Preview-only (prepended to the drum preview); never part of exported MIDI."""
    if beats <= 0 or tempo <= 0:
        return np.zeros((1, 2), dtype=np.float32)
    beat = 60.0 / float(tempo)
    total = int(round(beats * beat * sample_rate))
    buf = np.zeros((max(total, 1), 2), dtype=np.float32)
    click_len = min(int(0.03 * sample_rate), total or 1)
    t = np.arange(click_len) / sample_rate
    blip = (0.5 * np.sin(2 * np.pi * freq * t) * np.exp(-t * 40.0)).astype(np.float32)
    for b in range(int(beats)):
        start = int(round(b * beat * sample_rate))
        end = min(start + click_len, total)
        if end > start:
            buf[start:end, 0] += blip[:end - start]
            buf[start:end, 1] += blip[:end - start]
    return buf
DRUM_CHANNEL = 9          # GM channel 10
DRUM_BANK = 128          # GM percussion bank
_INT16_FULL_SCALE = 32768.0


def render_events(events, *, tempo, ppq, sample_rate=44100,
                  soundfont=DEFAULT_SOUNDFONT, tail=2.0):
    """Render `(tick, note, vel, dur)` events to a stereo float32 buffer (n, 2).

    Events carry concrete MIDI notes on the drum channel (already resolved via an
    output map). Timing is derived from `tempo`/`ppq` (build_song's tempo is inert,
    so the caller passes spec["tempo"]). A `tail` of silence-decay is appended so
    cymbals ring out — GM percussion are one-shots that ignore note-off, so note
    duration does not truncate the sound; the tail covers natural decay.

    A fresh Synth is created per call (sf2 is mmap-fast, ~0.15s) and deleted after:
    reverb/chorus are disabled and a fresh synth guarantees a clean voice state, so
    renders are bit-deterministic (a reused synth bleeds reverb/voices across
    renders and is NOT deterministic).
    """
    if not Path(soundfont).exists():
        raise FileNotFoundError(
            f"Soundfont not found: {soundfont}. Download FluidR3_GM.sf2 into "
            f"assets/soundfonts/ (see CLAUDE.md / docs); it is gitignored (~140MB).")

    fs = fluidsynth.Synth(samplerate=float(sample_rate))
    try:
        # Disable FX: deterministic renders + a dry drum stem to mix over a track.
        fs.setting("synth.reverb.active", 0)
        fs.setting("synth.chorus.active", 0)
        sfid = fs.sfload(str(soundfont))
        if sfid == -1:                      # sfload returns -1, it does not raise
            raise RuntimeError(f"fluidsynth failed to load soundfont: {soundfont}")
        fs.program_select(DRUM_CHANNEL, sfid, DRUM_BANK, 0)

        sec_per_tick = 60.0 / (tempo * ppq)
        sr = int(sample_rate)
        # Absolute-sample timeline (no per-gap rounding drift). on=1 sorts after
        # off=0 at the same index, matching write_midi's off-before-on ordering.
        timeline = []
        last_index = 0
        for tick, note, vel, dur in events:
            on_i = round(tick * sec_per_tick * sr)
            off_i = round((tick + dur) * sec_per_tick * sr)
            timeline.append((on_i, 1, int(note), int(vel)))
            timeline.append((off_i, 0, int(note), 0))
            last_index = max(last_index, off_i)
        timeline.sort(key=lambda x: (x[0], x[1]))

        end_index = last_index + round(tail * sr)
        chunks = []
        pos = 0
        for index, kind, note, vel in timeline:
            gap = index - pos
            if gap > 0:
                chunks.append(fs.get_samples(gap))   # int16 interleaved, len 2*gap
                pos = index
            if kind == 1:
                fs.noteon(DRUM_CHANNEL, note, vel)
            else:
                fs.noteoff(DRUM_CHANNEL, note)
        if end_index > pos:
            chunks.append(fs.get_samples(end_index - pos))
    finally:
        fs.delete()

    if chunks:
        interleaved = np.concatenate([np.asarray(c, dtype=np.int16) for c in chunks])
    else:
        interleaved = np.zeros(0, dtype=np.int16)
    return (interleaved.astype(np.float32) / _INT16_FULL_SCALE).reshape(-1, 2)


def load_audio(path, *, sample_rate=44100):
    """Load an audio file as a stereo float32 buffer (n, 2) at `sample_rate`."""
    data, file_sr = sf.read(path, always_2d=True)        # (frames, channels) float64
    data = data.astype(np.float32)
    if data.shape[1] == 1:                               # mono -> stereo
        data = np.repeat(data, 2, axis=1)
    elif data.shape[1] > 2:
        data = data[:, :2]
    if file_sr != sample_rate:
        import librosa
        # librosa.resample works along the last axis; transpose to (channels, n).
        data = librosa.resample(data.T, orig_sr=file_sr, target_sr=sample_rate,
                                axis=-1).T.astype(np.float32)
    return np.ascontiguousarray(data)


def mix(drums, bed, *, drums_gain=1.0, bed_gain=0.8):
    """Sum two stereo float32 buffers (pad shorter to longer). Peak-normalise only
    if the result would clip (|x| > 1)."""
    n = max(len(drums), len(bed))
    out = np.zeros((n, 2), dtype=np.float32)
    out[:len(drums)] += drums.astype(np.float32) * drums_gain
    out[:len(bed)] += bed.astype(np.float32) * bed_gain
    peak = float(np.max(np.abs(out))) if out.size else 0.0
    if peak > 1.0:
        out = out / peak
    return out


def has_output_device():
    """True if an audio output device is available (headless-safe)."""
    try:
        sd.query_devices(kind="output")
        return True
    except Exception:
        return False


class Player:
    """sounddevice transport over a held buffer. The only device-touching code.

    A single OutputStream is reused; play/pause/stop/seek move or reset a frame
    cursor that the realtime callback reads under a lock.
    """

    def __init__(self):
        self._buffer = np.zeros((0, 2), dtype=np.float32)
        self._sr = 44100
        self._cursor = 0
        self._lock = threading.Lock()
        self._stream = None

    def load(self, buffer, sample_rate):
        self.stop()
        sr = int(sample_rate)
        # A pre-existing stream is fixed at its creation samplerate; drop it so
        # _ensure_stream rebuilds at the new rate (else playback runs wrong-speed).
        if self._stream is not None and sr != self._sr:
            self._stream.close()
            self._stream = None
        self._buffer = np.ascontiguousarray(buffer, dtype=np.float32)
        self._sr = sr
        with self._lock:
            self._cursor = 0

    def _callback(self, outdata, frames, time_info, status):
        with self._lock:
            start = self._cursor
            end = min(start + frames, len(self._buffer))
            n = end - start
            outdata[:n] = self._buffer[start:end]
            self._cursor = end
        if n < frames:
            outdata[n:] = 0                  # zero-fill the tail of the final block
            raise sd.CallbackStop            # stop cleanly instead of repeating it

    def _ensure_stream(self):
        if self._stream is None:
            self._stream = sd.OutputStream(
                samplerate=self._sr, channels=2, callback=self._callback)

    def play(self):
        with self._lock:
            if self._cursor >= len(self._buffer):
                self._cursor = 0
        # A stream that finished (raised CallbackStop at the end) or was aborted
        # (stop/pause) cannot be reliably resumed with .start() — PortAudio treats
        # the callback as done. Rebuild a fresh stream so every Play works, not
        # just the first.
        if self._stream is not None and not self._stream.active:
            self._stream.close()
            self._stream = None
        self._ensure_stream()
        self._stream.start()

    def pause(self):
        if self._stream is not None and self._stream.active:
            self._stream.abort()             # keep cursor

    def stop(self):
        if self._stream is not None and self._stream.active:
            self._stream.abort()
        with self._lock:
            self._cursor = 0

    def seek(self, seconds):
        with self._lock:
            self._cursor = int(np.clip(round(seconds * self._sr), 0, len(self._buffer)))

    @property
    def position(self):
        with self._lock:
            return self._cursor / self._sr if self._sr else 0.0

    @property
    def is_playing(self):
        return self._stream is not None and self._stream.active
