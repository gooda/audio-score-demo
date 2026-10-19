"""Generate synthetic reference/user audio pairs for demo evaluation."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 22050
OUT = Path(__file__).resolve().parent / "samples"


def note_hz(midi: float) -> float:
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def synth_melody(
    midi_notes: list[float],
    note_dur: float = 0.35,
    gap: float = 0.05,
    vibrato_hz: float = 0.0,
    vibrato_cents: float = 0.0,
    time_stretch: float = 1.0,
    noise_amp: float = 0.0,
    amp: float = 0.35,
) -> np.ndarray:
    parts = []
    for m in midi_notes:
        dur = note_dur * time_stretch
        n = int(SR * dur)
        t = np.arange(n) / SR
        f0 = note_hz(m)
        if vibrato_hz > 0:
            f0 = f0 * (2 ** (vibrato_cents / 1200.0 * np.sin(2 * np.pi * vibrato_hz * t)))
        # simple harmonic stack (more voice-like than pure sine)
        phase = 2 * np.pi * np.cumsum(f0) / SR
        wave = (
            0.6 * np.sin(phase)
            + 0.25 * np.sin(2 * phase)
            + 0.1 * np.sin(3 * phase)
        )
        # ADSR-ish envelope
        atk = max(1, int(0.02 * SR))
        rel = max(1, int(0.05 * SR))
        env = np.ones(n)
        env[:atk] = np.linspace(0, 1, atk)
        env[-rel:] = np.linspace(1, 0, rel)
        wave = wave * env * amp
        parts.append(wave)
        g = int(SR * gap * time_stretch)
        if g > 0:
            parts.append(np.zeros(g))
    y = np.concatenate(parts) if parts else np.zeros(1)
    if noise_amp > 0:
        y = y + noise_amp * np.random.randn(len(y))
    y = y / (np.max(np.abs(y)) + 1e-9) * 0.85
    return y.astype(np.float32)


def synth_speechish(seed: int, n_syllables: int = 6, base_midi: float = 60) -> np.ndarray:
    """Pseudo-speech: irregular pitch contour + formant-ish noise bursts."""
    rng = np.random.default_rng(seed)
    parts = []
    for i in range(n_syllables):
        dur = float(rng.uniform(0.18, 0.35))
        n = int(SR * dur)
        t = np.arange(n) / SR
        midi = base_midi + float(rng.uniform(-3, 5)) + 2 * np.sin(2 * np.pi * 3 * t)
        f0 = note_hz(midi)
        phase = 2 * np.pi * np.cumsum(f0) / SR
        # buzz + band noise
        buzz = 0.4 * np.sin(phase) + 0.2 * np.sin(2 * phase)
        noise = rng.normal(0, 0.15, n)
        # simple resonance via moving average envelope
        env = np.hanning(n)
        syllable = (buzz + noise) * env * 0.5
        parts.append(syllable)
        parts.append(np.zeros(int(SR * rng.uniform(0.04, 0.12))))
    y = np.concatenate(parts)
    y = y / (np.max(np.abs(y)) + 1e-9) * 0.85
    return y.astype(np.float32)


def write(path: Path, y: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), y, SR)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    melody = [60, 62, 64, 65, 67, 65, 64, 62, 60]  # C major ascending/descending

    meta = []

    # (a) near-perfect: same melody, tiny vibrato + noise
    ref_a = synth_melody(melody, vibrato_hz=5, vibrato_cents=8)
    usr_a = synth_melody(melody, vibrato_hz=5.2, vibrato_cents=10, noise_amp=0.01)
    write(OUT / "a_near_perfect_ref.wav", ref_a)
    write(OUT / "a_near_perfect_user.wav", usr_a)
    meta.append(
        {
            "id": "a",
            "name": "近乎完美模仿",
            "ref": "a_near_perfect_ref.wav",
            "user": "a_near_perfect_user.wav",
            "expected_overall": "85–98",
            "note": "同一旋律，极小颤音与噪声差异",
        }
    )

    # (b) same contour, wrong key (+5 semitones)
    ref_b = synth_melody(melody, vibrato_hz=4.5, vibrato_cents=6)
    usr_b = synth_melody([m + 5 for m in melody], vibrato_hz=4.5, vibrato_cents=6)
    write(OUT / "b_wrong_key_ref.wav", ref_b)
    write(OUT / "b_wrong_key_user.wav", usr_b)
    meta.append(
        {
            "id": "b",
            "name": "调性偏移（旋律同、音高错）",
            "ref": "b_wrong_key_ref.wav",
            "user": "b_wrong_key_user.wav",
            "expected_overall": "85–98（去全局移调后；key_shift≈500 cents）",
            "note": "升高 5 个半音。Demo 音准会减去全局 key shift，故音准仍高；细节里可见 key_shift_cents≈500。若游戏要罚跑调，需另加绝对音高项。",
        }
    )

    # (c) right pitch, wrong timing (1.45x stretch)
    ref_c = synth_melody(melody, vibrato_hz=4.5, vibrato_cents=6)
    usr_c = synth_melody(melody, time_stretch=2.0, gap=0.18, vibrato_hz=4.5, vibrato_cents=6)
    write(OUT / "c_wrong_timing_ref.wav", ref_c)
    write(OUT / "c_wrong_timing_user.wav", usr_c)
    meta.append(
        {
            "id": "c",
            "name": "音高对、节奏慢",
            "ref": "c_wrong_timing_ref.wav",
            "user": "c_wrong_timing_user.wav",
            "expected_overall": "65–85（节奏项明显偏低，总分被音准/内容拉高）",
            "note": "同一音高序列，整体拉长约 2 倍；请重点看节奏分而非总分",
        }
    )

    # (d) different content
    ref_d = synth_melody(melody, vibrato_hz=4.5, vibrato_cents=6)
    usr_d = synth_speechish(seed=42, n_syllables=7, base_midi=55)
    write(OUT / "d_different_content_ref.wav", ref_d)
    write(OUT / "d_different_content_user.wav", usr_d)
    meta.append(
        {
            "id": "d",
            "name": "内容完全不同",
            "ref": "d_different_content_ref.wav",
            "user": "d_different_content_user.wav",
            "expected_overall": "30–55",
            "note": "参考是旋律，模仿是伪语音音节；内容分为 MFCC 代理，不会像 ASR 那样接近 0",
        }
    )

    with open(OUT / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(meta)} pairs to {OUT}")


if __name__ == "__main__":
    main()
