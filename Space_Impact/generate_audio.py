"""
Space Impact Sound Effect Generator
====================================
Generates all WAV sound effects for the Space Impact game using pure
synthesis (sine waves, noise, envelopes).  No external audio files needed.

Output format: mono, 16-bit signed PCM, 22050 Hz
This is the exact format required by CircuitPython's audiocore.WaveFile.

Run on your host PC:
    python generate_audio.py

Then copy the generated .wav files to /AudioFiles/ on your CircuitPython board.
"""

import numpy as np
import wave
import struct
import os
import sys

SAMPLE_RATE = 22050
MAX_AMP     = 32767   # 16-bit signed max


def _save_wav(filepath, samples):
    """Save a numpy float64 array (range -1.0 to 1.0) as a 16-bit mono WAV."""
    # Clip and convert to int16
    clipped = np.clip(samples, -1.0, 1.0)
    int_samples = (clipped * MAX_AMP).astype(np.int16)

    with wave.open(filepath, "w") as wf:
        wf.setnchannels(1)          # mono
        wf.setsampwidth(2)          # 16-bit
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(int_samples.tobytes())

    size = os.path.getsize(filepath)
    dur  = len(samples) / SAMPLE_RATE
    print(f"  Created {os.path.basename(filepath):30s}  "
          f"{dur:.2f}s  {size:>6,d} bytes")


def _sine(freq, duration, amplitude=1.0):
    """Generate a sine wave."""
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    return amplitude * np.sin(2.0 * np.pi * freq * t)


def _noise(duration, amplitude=1.0):
    """Generate white noise."""
    n = int(SAMPLE_RATE * duration)
    return amplitude * (np.random.random(n) * 2.0 - 1.0)


def _envelope(samples, attack=0.01, decay=0.0, sustain_level=1.0, release=0.01):
    """Apply an ADSR-ish amplitude envelope."""
    n = len(samples)
    env = np.ones(n)

    att_n = int(attack * SAMPLE_RATE)
    rel_n = int(release * SAMPLE_RATE)
    dec_n = int(decay * SAMPLE_RATE)

    # Attack ramp
    if att_n > 0:
        env[:att_n] = np.linspace(0, 1, att_n)

    # Decay to sustain level
    if dec_n > 0 and att_n + dec_n < n:
        env[att_n:att_n + dec_n] = np.linspace(1, sustain_level, dec_n)
        env[att_n + dec_n:-rel_n if rel_n > 0 else n] = sustain_level

    # Release ramp
    if rel_n > 0:
        env[-rel_n:] = np.linspace(env[-rel_n] if rel_n < n else sustain_level, 0, rel_n)

    return samples * env


def _pitch_sweep(start_freq, end_freq, duration, amplitude=1.0):
    """Generate a frequency sweep (linear)."""
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    freq = np.linspace(start_freq, end_freq, len(t))
    phase = 2.0 * np.pi * np.cumsum(freq) / SAMPLE_RATE
    return amplitude * np.sin(phase)


# ---------------------------------------------------------------------------
# Sound effect generators
# ---------------------------------------------------------------------------

def generate_shoot(out_dir):
    """Short laser 'pew' sound -- quick high-pitched sweep down."""
    dur = 0.10
    sweep = _pitch_sweep(2000, 400, dur, 0.8)
    # Add a bit of harmonics
    sweep += _pitch_sweep(4000, 800, dur, 0.2)
    result = _envelope(sweep, attack=0.002, release=0.03)
    _save_wav(os.path.join(out_dir, "si_shoot.wav"), result)


def generate_explosion(out_dir):
    """Small explosion -- noise burst with low-freq rumble."""
    dur = 0.30
    noise_part = _noise(dur, 0.6)
    rumble     = _sine(80, dur, 0.4) + _sine(50, dur, 0.3)
    mixed      = noise_part + rumble
    result     = _envelope(mixed, attack=0.005, decay=0.05,
                           sustain_level=0.4, release=0.15)
    _save_wav(os.path.join(out_dir, "si_explosion.wav"), result)


def generate_powerup(out_dir):
    """Positive chime -- ascending arpeggio."""
    notes = [523, 659, 784, 1047]  # C5, E5, G5, C6
    note_dur = 0.08
    gap      = 0.005
    parts    = []
    for freq in notes:
        tone = _sine(freq, note_dur, 0.7)
        tone = _envelope(tone, attack=0.005, release=0.02)
        parts.append(tone)
        parts.append(np.zeros(int(SAMPLE_RATE * gap)))
    result = np.concatenate(parts)
    _save_wav(os.path.join(out_dir, "si_powerup.wav"), result)


def generate_hit(out_dir):
    """Damage/impact -- short harsh buzz with noise."""
    dur   = 0.20
    buzz  = _sine(150, dur, 0.5)
    # Square-ish wave by clipping
    buzz  = np.clip(buzz * 3, -0.5, 0.5)
    noise_part = _noise(dur, 0.3)
    mixed = buzz + noise_part
    result = _envelope(mixed, attack=0.002, decay=0.03,
                       sustain_level=0.3, release=0.10)
    _save_wav(os.path.join(out_dir, "si_hit.wav"), result)


def generate_boss_explode(out_dir):
    """Big boss explosion -- longer, deeper, more dramatic."""
    dur = 0.55
    # Heavy noise
    noise_part = _noise(dur, 0.5)
    # Deep rumble
    rumble = _sine(40, dur, 0.5) + _sine(60, dur, 0.3) + _sine(30, dur, 0.2)
    # Mid crunch
    crunch = _pitch_sweep(500, 50, dur, 0.3)
    mixed  = noise_part + rumble + crunch
    result = _envelope(mixed, attack=0.005, decay=0.1,
                       sustain_level=0.5, release=0.25)
    _save_wav(os.path.join(out_dir, "si_boss_explode.wav"), result)


def generate_gameover(out_dir):
    """Defeat jingle -- descending minor notes."""
    # G4, Eb4, C4, G3 (descending minor feel)
    notes    = [392, 311, 262, 196]
    note_dur = 0.35
    gap      = 0.05
    parts    = []
    for i, freq in enumerate(notes):
        tone = _sine(freq, note_dur, 0.6)
        # Add slight vibrato on last note
        if i == len(notes) - 1:
            t = np.linspace(0, note_dur, int(SAMPLE_RATE * note_dur), endpoint=False)
            vibrato = 0.1 * np.sin(2 * np.pi * 5 * t)
            tone = 0.6 * np.sin(2 * np.pi * (freq + vibrato * freq * 0.02) * t)
        tone = _envelope(tone, attack=0.01, decay=0.05,
                         sustain_level=0.8, release=0.1)
        parts.append(tone)
        parts.append(np.zeros(int(SAMPLE_RATE * gap)))
    result = np.concatenate(parts)
    _save_wav(os.path.join(out_dir, "si_gameover.wav"), result)


def generate_level_clear(out_dir):
    """Victory fanfare -- ascending major arpeggio with sustained finish."""
    # C5, E5, G5, C6 (major arpeggio) then sustained C6
    notes = [
        (523, 0.15),   # C5
        (659, 0.15),   # E5
        (784, 0.15),   # G5
        (1047, 0.50),  # C6 (held)
    ]
    gap = 0.02
    parts = []
    for freq, dur in notes:
        tone = _sine(freq, dur, 0.6)
        # Add octave harmonic for brightness
        tone += _sine(freq * 2, dur, 0.15)
        tone = _envelope(tone, attack=0.01, decay=0.02,
                         sustain_level=0.8, release=0.08)
        parts.append(tone)
        parts.append(np.zeros(int(SAMPLE_RATE * gap)))

    # Final chord: C5 + E5 + G5 + C6 together
    chord_dur = 0.6
    chord = (_sine(523, chord_dur, 0.3) +
             _sine(659, chord_dur, 0.25) +
             _sine(784, chord_dur, 0.25) +
             _sine(1047, chord_dur, 0.2))
    chord = _envelope(chord, attack=0.02, release=0.3)
    parts.append(chord)

    result = np.concatenate(parts)
    _save_wav(os.path.join(out_dir, "si_level_clear.wav"), result)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    # Determine output directory
    # Default: the AudioFiles directory alongside PyKit-Explorer-Code-Modules
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Go up to the workshop root, then to the Code-Modules AudioFiles
    workshop_root = os.path.dirname(script_dir)
    code_modules  = os.path.join(os.path.dirname(workshop_root),
                                 "PyKit-Explorer-Code-Modules", "AudioFiles")

    if os.path.isdir(code_modules):
        out_dir = code_modules
    else:
        # Fallback: create AudioFiles next to this script
        out_dir = os.path.join(script_dir, "AudioFiles")
        os.makedirs(out_dir, exist_ok=True)

    print(f"Generating Space Impact sound effects...")
    print(f"Output directory: {out_dir}")
    print("-" * 60)

    np.random.seed(42)  # reproducible noise

    generate_shoot(out_dir)
    generate_explosion(out_dir)
    generate_powerup(out_dir)
    generate_hit(out_dir)
    generate_boss_explode(out_dir)
    generate_gameover(out_dir)
    generate_level_clear(out_dir)

    print("-" * 60)
    print(f"\nSuccess! 7 WAV files generated in: {out_dir}")
    print("Format: mono, 16-bit PCM, 22050 Hz")
    print("\nCopy these files to /AudioFiles/ on your CircuitPython board:")
    for name in ["si_shoot", "si_explosion", "si_powerup", "si_hit",
                 "si_boss_explode", "si_gameover", "si_level_clear"]:
        print(f"  {name}.wav")


if __name__ == "__main__":
    main()
