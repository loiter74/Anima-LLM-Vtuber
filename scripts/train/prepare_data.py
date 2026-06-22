#!/usr/bin/env python3
"""一键数据预处理：切片 → 归一化 → 音高增强 → 数据集划分.

Input:  data/training/raw/*.wav
Output: data/training/{ready/{train,val}, processed, augmented}

Usage:
    python scripts/train/prepare_data.py
    python scripts/train/prepare_data.py --raw-dir ./my_audio --output ./my_dataset
"""
import random
import shutil
from pathlib import Path

import librosa
import numpy as np
import pyloudnorm as pyln
import pyworld as pw
import soundfile as sf
import yaml
from loguru import logger


def load_config() -> dict:
    p = Path(__file__).parent / "config.yaml"
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── Step 1: Slice ────────────────────────────────────────────────


def _detect_silence(audio, sr, threshold_db, min_silence_s):
    """Find silent regions. Returns list of (start_sample, end_sample)."""
    fl = int(sr * 0.05)
    hl = fl // 2
    rms = librosa.feature.rms(y=audio, frame_length=fl, hop_length=hl)[0]
    thresh = 10 ** (threshold_db / 20)
    is_silent = rms < thresh
    min_frames = int(min_silence_s * sr / hl)
    regions = []
    start = None
    for i, s in enumerate(is_silent):
        if s and start is None:
            start = i
        elif not s and start is not None:
            if i - start >= min_frames:
                regions.append((start * hl, i * hl))
            start = None
    if start is not None and len(is_silent) - start >= min_frames:
        regions.append((start * hl, len(is_silent) * hl))
    return regions


def _slice(input_path: Path, output_dir: Path, cfg: dict) -> list[Path]:
    """Slice audio into non-silent segments (4-15s)."""
    sr = cfg["target_sr"]
    threshold = cfg["silence_threshold"]
    min_dur = cfg["min_duration"]
    max_dur = cfg["max_duration"]

    audio, orig_sr = librosa.load(str(input_path), sr=None, mono=True)
    if orig_sr != sr:
        audio = librosa.resample(audio, orig_sr=orig_sr, target_sr=sr)

    silences = _detect_silence(audio, sr, threshold, 0.5)
    if not silences:
        if len(audio) / sr >= min_dur:
            out = output_dir / f"{input_path.stem}.wav"
            sf.write(str(out), audio, sr)
            return [out]
        return []

    outputs = []
    prev = 0
    for idx, (start, end) in enumerate(silences):
        seg = audio[prev:start]
        dur = len(seg) / sr
        if dur >= min_dur:
            if dur > max_dur:
                mid = len(seg) // 2
                for pi, sp in enumerate([0, mid]):
                    part = seg[sp:sp + mid]
                    if len(part) / sr >= min_dur:
                        out = output_dir / f"{input_path.stem}_seg{idx}_p{pi}.wav"
                        sf.write(str(out), part, sr)
                        outputs.append(out)
            else:
                out = output_dir / f"{input_path.stem}_seg{idx}.wav"
                sf.write(str(out), seg, sr)
                outputs.append(out)
        prev = end
    trail = audio[prev:]
    if len(trail) / sr >= min_dur:
        out = output_dir / f"{input_path.stem}_trail.wav"
        sf.write(str(out), trail, sr)
        outputs.append(out)
    return outputs


# ── Step 2: Normalize ────────────────────────────────────────────


def _normalize(input_path: Path, sr: int, target_loudness: float):
    """Resample + loudness normalize in-place."""
    audio, orig_sr = librosa.load(str(input_path), sr=None, mono=True)
    if orig_sr != sr:
        audio = librosa.resample(audio, orig_sr=orig_sr, target_sr=sr)
    meter = pyln.Meter(sr)
    loudness = meter.integrated_loudness(audio)
    audio = pyln.normalize.loudness(audio, loudness, target_loudness)
    peak = np.max(np.abs(audio))
    if peak > 0.99:
        audio = audio * (0.99 / peak)
    sf.write(str(input_path), audio, sr)
    return float(librosa.get_duration(y=audio, sr=sr))


# ── Step 3: Pitch Augment ────────────────────────────────────────


def _pitch_shift(audio: np.ndarray, sr: int, semitones: float) -> np.ndarray:
    """WORLD vocoder pitch shift (preserves formants)."""
    f0, t = pw.harvest(audio.astype(np.float64), sr)
    f0 = pw.stonemask(audio.astype(np.float64), f0, t, sr)
    sp = pw.cheaptrick(audio.astype(np.float64), f0, t, sr)
    ap = pw.d4c(audio.astype(np.float64), f0, t, sr)
    f0_shifted = f0.copy()
    mask = f0 > 0
    f0_shifted[mask] = f0[mask] * (2 ** (semitones / 12))
    return pw.synthesize(f0_shifted, sp, ap, sr).astype(np.float32)


def _augment(input_dir: Path, output_dir: Path, cfg: dict) -> list[Path]:
    """Generate pitch-shifted copies."""
    shifts = cfg["pitch_shifts"]  # [0, -2, +2]
    low_shift = cfg["extend_low_shift"]  # +4
    low_thresh = cfg["low_pitch_threshold"]  # 400 Hz

    outputs = []
    for wav in sorted(input_dir.glob("*.wav")):
        audio, sr = librosa.load(str(wav), sr=None, mono=True)
        f0, _ = pw.dio(audio.astype(np.float64), sr)
        median_pitch = float(np.median(f0[f0 > 0])) if np.any(f0 > 0) else 0

        for shift in shifts:
            out = output_dir / f"{wav.stem}_shift{shift:+d}.wav"
            if shift == 0:
                sf.write(str(out), audio, sr)
            else:
                sf.write(str(out), _pitch_shift(audio, sr, float(shift)), sr)
            outputs.append(out)

        if 0 < median_pitch < low_thresh:
            out = output_dir / f"{wav.stem}_shift+{low_shift}.wav"
            sf.write(str(out), _pitch_shift(audio, sr, float(low_shift)), sr)
            outputs.append(out)

    return outputs


# ── Main ─────────────────────────────────────────────────────────


def main():
    config = load_config()
    raw_dir = Path(config["data"]["raw_dir"])
    processed_dir = Path(config["data"]["processed_dir"])
    augmented_dir = Path(config["data"]["augmented_dir"])
    ready_dir = processed_dir.parent / "ready"

    audio_cfg = config["audio"]
    aug_cfg = config["augmentation"]
    sr = audio_cfg["target_sr"]

    # Ensure dirs
    for d in [processed_dir, augmented_dir, ready_dir / "train", ready_dir / "val"]:
        d.mkdir(parents=True, exist_ok=True)

    # Find input audio
    audio_files = (
        list(raw_dir.rglob("*.wav")) +
        list(raw_dir.rglob("*.flac")) +
        list(raw_dir.rglob("*.mp3"))
    )
    if not audio_files:
        logger.warning(f"No audio files in {raw_dir}")
        return

    # Step 1-2: Slice + Normalize (done together per file)
    logger.info(f"📂 Found {len(audio_files)} files in {raw_dir}")
    all_sliced = []
    for fpath in audio_files:
        try:
            sliced = _slice(fpath, processed_dir, audio_cfg)
            for s in sliced:
                _normalize(s, sr, audio_cfg["target_loudness"])
            all_sliced.extend(sliced)
        except Exception as e:
            logger.error(f"  ✗ {fpath.name}: {e}")

    total_dur = sum(
        float(librosa.get_duration(path=str(p))) for p in all_sliced
    ) if all_sliced else 0
    logger.info(f"✅ Slice+Normalize: {len(all_sliced)} clips, {total_dur:.0f}s")

    # Step 3: Pitch Augmentation
    augmented = _augment(processed_dir, augmented_dir, aug_cfg)
    logger.info(f"✅ Pitch Augment: {len(augmented)} clips (+{len(augmented)-len(all_sliced)} shifted)")

    # Step 4: Train/Val Split
    source = augmented_dir if augmented else processed_dir
    wavs = list(source.glob("*.wav"))
    random.Random(42).shuffle(wavs)
    split = int(len(wavs) * 0.9)
    for f in wavs[:split]:
        shutil.copy2(str(f), str(ready_dir / "train" / f.name))
    for f in wavs[split:]:
        shutil.copy2(str(f), str(ready_dir / "val" / f.name))

    logger.info(f"✅ Dataset ready: {len(wavs)} files → {ready_dir}")
    logger.info(f"   Train: {split}  |  Val: {len(wavs) - split}")


if __name__ == "__main__":
    main()
