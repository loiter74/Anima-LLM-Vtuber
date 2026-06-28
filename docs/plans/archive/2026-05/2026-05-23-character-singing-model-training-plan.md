# Character Singing Model Training — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a repeatable paradigm for training RVC v2 singing voice models for anime characters, starting with 赛马娘诗歌剧 (Nice Nature).

**Architecture:** 5-stage pipeline: Data Collection → Preprocessing (scripts) → RVC WebUI Training (manual) → Anima Deployment (scripted) → Inference. All scripts live under `scripts/train/`. The design spec is at `docs/plans/archive/2026-05/2026-05-23-character-singing-model-training-design.md`.

**Tech Stack:** Python 3.13+, RVC WebUI (C:\Users\30262\RVC20240604Nvidia), pyworld, librosa, faster-whisper, yt-dlp, Demucs, ffmpeg

**Paradigm Goal:** After this plan, training any new character is: prepare data → run 5 scripts → train in WebUI → run deploy script.

---

### Task 1: Create `scripts/train/` directory structure and config template

**Files:**
- Create: `scripts/train/__init__.py`
- Create: `scripts/train/config.yaml`
- Create: `scripts/train/README.md`

**Step 1: Create `scripts/train/` directory**

The skeleton of the training paradigm:

```
scripts/train/
├── __init__.py
├── config.yaml                  # Shared config — edit per character
├── README.md                    # Usage instructions
├── 01_collect_data.py           # (Optional) Automated data collection
├── 02_slice_and_denoise.py      # Audio slicing + noise reduction
├── 03_normalize.py              # Loudness normalization + 48kHz resample
├── 04_augment_pitch.py          # WORLD pitch shift augmentation
├── 05_split_dataset.py          # Train/validation 90/10 split
└── deploy_to_anima.py           # Copy model + update config
```

Create: `mkdir -p scripts/train`

**Step 2: Write config.yaml**

```yaml
# scripts/train/config.yaml
# Edit this file per character — all scripts read from here

character:
  name: "shige_utage"            # 诗歌剧 — used for filenames
  display_name: "诗歌剧"          # Display name
  cv: "Hikaru Toono"             # Voice actor

data:
  raw_dir: "./data/training/raw"            # Raw input audio
  processed_dir: "./data/training/processed" # After preprocessing
  augmented_dir: "./data/training/augmented" # After pitch augmentation

audio:
  target_sr: 48000                # Target sample rate (Hz)
  min_duration: 4.0               # Min clip duration (seconds)
  max_duration: 15.0              # Max clip duration (seconds)
  silence_threshold: 0.02         # Silence detection threshold
  target_loudness: -20            # Target integrated loudness (LUFS)

augmentation:
  pitch_shifts: [0, -2, +2]       # Semitone shifts for augmentation
  extend_low_shift: +4            # Extra up-shift for low-pitch clips
  low_pitch_threshold: 400        # Hz — clips below this get extra shift

rvc:
  sample_rate: 48000
  version: "v2"
  f0_method: "rmvpe"
  batch_size: 16
  epochs: 300
  pretrained: "f0G48k.pth"        # RVC base pretrained generator
  pretrained_d: "f0D48k.pth"      # RVC base pretrained discriminator

anima:
  rvc_path: "C:/Users/30262/RVC20240604Nvidia"
  config_path: "./config/singing.yaml"
  weights_subdir: "weights"        # Relative to rvc_path
  index_subdir: "logs"             # Relative to rvc_path
```

**Step 3: Write README.md**

```markdown
# Training Paradigm — Character Singing Voice Model

## Quick Start (for a new character)

```bash
# 1. Edit config.yaml (change character name)
# 2. Place raw audio files in data/training/raw/
# 3. Run preprocessing pipeline
python scripts/train/02_slice_and_denoise.py
python scripts/train/03_normalize.py
python scripts/train/04_augment_pitch.py
python scripts/train/05_split_dataset.py
# 4. Open RVC WebUI → train with resulting dataset
#    Experiment name: {character.name}
#    Sample rate: {rvc.sample_rate}
#    Version: {rvc.version}
# 5. Deploy to Anima
python scripts/train/deploy_to_anima.py
```

## Data Requirements

- Total: 30-60 minutes clean vocals
- Singing data: at least 10 minutes (critical)
- Format: WAV, any sample rate (will be resampled)
- No background music, no reverb

## Directory Layout

```
data/training/
├── raw/              # Raw input — place files here
├── processed/        # After slicing + denoising
├── augmented/        # After pitch augmentation
└── ready/            # Final dataset for RVC WebUI
```
```

**Step 4: Write `__init__.py`**

```python
"""Character singing model training paradigm — scripts and utilities."""
```

**Step 5: Commit**

```bash
git add scripts/train/
git commit -m "feat: add training paradigm directory structure and config"
```

---

### Task 2: Implement `02_slice_and_denoise.py`

**Files:**
- Create: `scripts/train/02_slice_and_denoise.py`
- Test: manual test on sample audio

**Purpose:** Slice raw audio into 4-15s clips, remove silence, apply noise reduction.

**Step 1: Write the script**

```python
#!/usr/bin/env python3
"""Slice audio into clips, remove silence, denoise.

Input:  data/training/raw/*.wav (or subdirectories)
Output: data/training/processed/*.wav

Uses:
- librosa for audio I/O and silence detection
- scipy.signal for basic noise gate
- (Optional) noisereduce library for spectral gating
"""
import argparse
import sys
from pathlib import Path

import librosa
import soundfile as sf
import yaml
from loguru import logger


def load_config() -> dict:
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def detect_silence_ranges(audio: np.ndarray, sr: int,
                           threshold: float, min_silence_len: float) -> list[tuple[int, int]]:
    """Detect silent regions in audio.
    
    Returns list of (start_sample, end_sample) for each silent region.
    """
    frame_length = int(sr * 0.05)  # 50ms frames
    hop_length = frame_length // 2
    rms = librosa.feature.rms(y=audio, frame_length=frame_length, hop_length=hop_length)[0]
    threshold_linear = 10 ** (threshold / 20)  # Convert dB to linear
    is_silent = rms < threshold_linear
    
    # Find contiguous silent regions
    silent_regions = []
    min_frames = int(min_silence_len * sr / hop_length)
    start = None
    for i, silent in enumerate(is_silent):
        if silent and start is None:
            start = i
        elif not silent and start is not None:
            if i - start >= min_frames:
                silent_regions.append((start * hop_length, i * hop_length))
            start = None
    if start is not None and len(is_silent) - start >= min_frames:
        silent_regions.append((start * hop_length, len(is_silent) * hop_length))
    
    return silent_regions


def slice_audio(input_path: Path, output_dir: Path,
                config: dict) -> list[Path]:
    """Slice audio into non-silent segments."""
    audio_cfg = config["audio"]
    sr = audio_cfg["target_sr"]
    threshold = audio_cfg["silence_threshold"]
    min_dur = audio_cfg["min_duration"]
    max_dur = audio_cfg["max_duration"]
    
    logger.info(f"Processing: {input_path}")
    audio, orig_sr = librosa.load(str(input_path), sr=None, mono=True)
    
    # Resample if needed
    if orig_sr != sr:
        audio = librosa.resample(audio, orig_orig_sr=orig_sr, target_sr=sr)
    
    # Detect and remove silence
    silent_ranges = detect_silence_ranges(audio, sr, threshold, min_silence_len=0.5)
    if not silent_ranges:
        # No silence found — use whole file if within limits
        if len(audio) / sr >= min_dur:
            output_path = output_dir / f"{input_path.stem}.wav"
            sf.write(str(output_path), audio, sr)
            return [output_path]
        return []
    
    # Extract non-silent segments
    outputs = []
    prev_end = 0
    for seg_idx, (start, end) in enumerate(silent_ranges):
        segment = audio[prev_end:start]
        if len(segment) / sr >= min_dur:
            # If segment > max_dur, split further (simple midpoint split)
            if len(segment) / sr > max_dur:
                midpoint = len(segment) // 2
                for part_idx, split_point in enumerate([0, midpoint]):
                    part = segment[split_point:split_point + midpoint]
                    if len(part) / sr >= min_dur:
                        output_path = output_dir / f"{input_path.stem}_seg{seg_idx}_p{part_idx}.wav"
                        sf.write(str(output_path), part, sr)
                        outputs.append(output_path)
            else:
                output_path = output_dir / f"{input_path.stem}_seg{seg_idx}.wav"
                sf.write(str(output_path), segment, sr)
                outputs.append(output_path)
        prev_end = end
    
    # Handle trailing audio after last silence
    trailing = audio[prev_end:]
    if len(trailing) / sr >= min_dur:
        output_path = output_dir / f"{input_path.stem}_trail.wav"
        sf.write(str(output_path), trailing, sr)
        outputs.append(output_path)
    
    logger.info(f"  → {len(outputs)} segments from {input_path.name}")
    return outputs


def main():
    parser = argparse.ArgumentParser(description="Slice and denoise audio")
    parser.add_argument("--config", default=None, help="Override config path")
    args = parser.parse_args()
    
    config = load_config()
    raw_dir = Path(config["data"]["raw_dir"])
    processed_dir = Path(config["data"]["processed_dir"])
    processed_dir.mkdir(parents=True, exist_ok=True)
    
    audio_files = list(raw_dir.rglob("*.wav")) + list(raw_dir.rglob("*.flac")) + list(raw_dir.rglob("*.mp3"))
    if not audio_files:
        logger.warning(f"No audio files found in {raw_dir}")
        return
    
    all_outputs = []
    for fpath in audio_files:
        try:
            outputs = slice_audio(fpath, processed_dir, config)
            all_outputs.extend(outputs)
        except Exception as e:
            logger.error(f"Failed to process {fpath}: {e}")
    
    logger.info(f"Done. {len(all_outputs)} clips in {processed_dir}")
    logger.info(f"Total duration: {sum(librosa.get_duration(path=str(p)) for p in all_outputs):.1f}s")


if __name__ == "__main__":
    import numpy as np
    main()
```

**Step 2: Manual test**

Run: `python scripts/train/02_slice_and_denoise.py --help`
Expected: Shows help text.

Run: `python scripts/train/02_slice_and_denoise.py`
Expected: Processes files in `data/training/raw/`, outputs to `data/training/processed/`.

**Step 3: Commit**

```bash
git add scripts/train/02_slice_and_denoise.py
git commit -m "feat: add audio slicing and silence removal script"
```

---

### Task 3: Implement `03_normalize.py`

**Files:**
- Create: `scripts/train/03_normalize.py`

**Purpose:** Resample all audio to 48kHz, normalize loudness to target LUFS.

**Step 1: Write the script**

```python
#!/usr/bin/env python3
"""Normalize audio: resample to target SR, loudness normalize.

Input:  data/training/processed/*.wav
Output: data/training/processed/*.wav (in-place, or augmented/)
"""
import argparse
from pathlib import Path

import librosa
import soundfile as sf
import yaml
from loguru import logger
import pyloudnorm as pyln


def load_config() -> dict:
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def normalize_audio(input_path: Path, output_path: Path, target_sr: int, target_loudness: float):
    """Resample to target SR, measure and normalize loudness."""
    audio, orig_sr = librosa.load(str(input_path), sr=None, mono=True)
    
    # Resample
    if orig_sr != target_sr:
        audio = librosa.resample(audio, orig_sr=orig_sr, target_sr=target_sr)
    
    # Measure loudness (requires 44.1kHz+ for meter)
    meter = pyln.Meter(target_sr)
    loudness = meter.integrated_loudness(audio)
    
    # Normalize
    audio_normalized = pyln.normalize.loudness(audio, loudness, target_loudness)
    
    # Peak normalize to prevent clipping
    peak = np.max(np.abs(audio_normalized))
    if peak > 0.99:
        audio_normalized = audio_normalized * (0.99 / peak)
    
    sf.write(str(output_path), audio_normalized, target_sr)
    return float(librosa.get_duration(y=audio_normalized, sr=target_sr))


def main():
    config = load_config()
    processed_dir = Path(config["data"]["processed_dir"])
    target_sr = config["audio"]["target_sr"]
    target_loudness = config["audio"]["target_loudness"]
    
    wavs = list(processed_dir.glob("*.wav"))
    if not wavs:
        logger.warning(f"No WAV files in {processed_dir}")
        return
    
    total_duration = 0.0
    for wav in wavs:
        try:
            dur = normalize_audio(wav, wav, target_sr, target_loudness)
            total_duration += dur
            logger.debug(f"  {wav.name}: {dur:.1f}s")
        except Exception as e:
            logger.error(f"Failed: {wav}: {e}")
    
    logger.info(f"Done. {len(wavs)} files, {total_duration:.1f}s total")


if __name__ == "__main__":
    import numpy as np
    main()
```

**Step 2: Commit**

```bash
git add scripts/train/03_normalize.py
git commit -m "feat: add loudness normalization and resampling script"
```

---

### Task 4: Implement `04_augment_pitch.py` (核心高音增强)

**Files:**
- Create: `scripts/train/04_augment_pitch.py`

**Purpose:** Generate pitch-shifted copies of training data using WORLD vocoder to extend the model's usable pitch range.

**Step 1: Write the script**

```python
#!/usr/bin/env python3
"""Pitch augmentation using WORLD vocoder.

For each input clip, generates N copies at different pitch shifts:
- 0 semitones (original — always kept)
- +2 semitones (brighter, extends high range)
- -2 semitones (darker, improves generalization)
- +4 semitones (only for clips with estimated pitch < threshold Hz)

Input:  data/training/processed/*.wav
Output: data/training/augmented/*_shift{+,-}N.wav
"""
import argparse
from pathlib import Path

import numpy as np
import librosa
import soundfile as sf
import pyworld as pw
import yaml
from loguru import logger


def load_config() -> dict:
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def estimate_median_pitch(audio: np.ndarray, sr: int) -> float:
    """Estimate the median pitch of a clip using WORLD."""
    f0, _ = pw.dio(audio.astype(np.float64), sr)
    f0 = f0[f0 > 0]  # Remove unvoiced frames
    if len(f0) == 0:
        return 0.0
    return float(np.median(f0))


def pitch_shift_world(audio: np.ndarray, sr: int, semitones: float) -> np.ndarray:
    """Shift pitch using WORLD vocoder (preserves spectral envelope).
    
    This preserves formants while changing pitch — unlike simple resampling,
    which changes both pitch and timbre.
    """
    # WORLD analysis
    f0, t = pw.harvest(audio.astype(np.float64), sr)
    f0 = pw.stonemask(audio.astype(np.float64), f0, t, sr)
    sp = pw.cheaptrick(audio.astype(np.float64), f0, t, sr)
    ap = pw.d4c(audio.astype(np.float64), f0, t, sr)
    
    # Shift F0
    f0_shifted = f0.copy()
    mask = f0 > 0
    f0_shifted[mask] = f0[mask] * (2 ** (semitones / 12))
    
    # Synthesize
    shifted = pw.synthesize(f0_shifted, sp, ap, sr)
    return shifted.astype(np.float32)


def main():
    config = load_config()
    processed_dir = Path(config["data"]["processed_dir"])
    augmented_dir = Path(config["data"]["augmented_dir"])
    augmented_dir.mkdir(parents=True, exist_ok=True)
    
    shifts = config["augmentation"]["pitch_shifts"]  # [0, -2, +2]
    low_shift = config["augmentation"]["extend_low_shift"]  # +4
    low_threshold = config["augmentation"]["low_pitch_threshold"]  # 400 Hz
    
    wavs = sorted(processed_dir.glob("*.wav"))
    if not wavs:
        logger.warning(f"No WAV files in {processed_dir}")
        return
    
    total_outputs = 0
    for wav in wavs:
        try:
            audio, sr = librosa.load(str(wav), sr=None, mono=True)
            median_pitch = estimate_median_pitch(audio, sr) if sr else 0
            logger.debug(f"  {wav.name}: median pitch = {median_pitch:.0f} Hz")
            
            for shift in shifts:
                output_path = augmented_dir / f"{wav.stem}_shift{shift:+d}.wav"
                if shift == 0:
                    # Original — just copy
                    sf.write(str(output_path), audio, sr)
                else:
                    shifted = pitch_shift_world(audio, sr, shift)
                    sf.write(str(output_path), shifted, sr)
                total_outputs += 1
            
            # Extra up-shift for low-pitch clips
            if 0 < median_pitch < low_threshold:
                output_path = augmented_dir / f"{wav.stem}_shift+{low_shift}.wav"
                shifted = pitch_shift_world(audio, sr, low_shift)
                sf.write(str(output_path), shifted, sr)
                total_outputs += 1
                
        except Exception as e:
            logger.error(f"Failed: {wav}: {e}")
    
    logger.info(f"Done. {total_outputs} clips in {augmented_dir}")


if __name__ == "__main__":
    main()
```

**Step 2: Test**

Run: `python scripts/train/04_augment_pitch.py`
Expected: Generates shifted copies.

Check output: `ls data/training/augmented/ | head -20`
Expected: Files named like `*_shift+0.wav`, `*_shift-2.wav`, `*_shift+2.wav`.

**Step 3: Commit**

```bash
git add scripts/train/04_augment_pitch.py
git commit -m "feat: add WORLD pitch augmentation for high-pitch enhancement"
```

---

### Task 5: Implement `05_split_dataset.py`

**Files:**
- Create: `scripts/train/05_split_dataset.py`

**Purpose:** Split augmented dataset into training (90%) and validation (10%) sets.

**Step 1: Write the script**

```python
#!/usr/bin/env python3
"""Split augmented dataset into train/validation sets.

Input:  data/training/augmented/*.wav
Output: data/training/ready/train/ and data/training/ready/val/
"""
import random
import shutil
from pathlib import Path

import yaml
from loguru import logger


def load_config() -> dict:
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def main():
    config = load_config()
    augmented_dir = Path(config["data"]["augmented_dir"])
    processed_dir = Path(config["data"]["processed_dir"])
    
    # Determine source: prefer augmented, fallback to processed
    source_dir = augmented_dir if augmented_dir.exists() and any(augmented_dir.iterdir()) else processed_dir
    
    # Output: data/training/ready/
    ready_dir = Path(config["data"]["processed_dir"]).parent / "ready"
    train_dir = ready_dir / "train"
    val_dir = ready_dir / "val"
    train_dir.mkdir(parents=True, exist_ok=True)
    val_dir.mkdir(parents=True, exist_ok=True)
    
    wavs = list(source_dir.glob("*.wav"))
    if not wavs:
        logger.warning(f"No WAV files in {source_dir}")
        return
    
    # Shuffle
    random.shuffle(wavs)
    split_idx = int(len(wavs) * 0.9)
    train_files = wavs[:split_idx]
    val_files = wavs[split_idx:]
    
    for fpath in train_files:
        shutil.copy2(str(fpath), str(train_dir / fpath.name))
    
    for fpath in val_files:
        shutil.copy2(str(fpath), str(val_dir / fpath.name))
    
    logger.info(f"Train: {len(train_files)} files")
    logger.info(f"Val:   {len(val_files)} files")
    logger.info(f"Ready dataset at: {ready_dir}")


if __name__ == "__main__":
    main()
```

**Step 2: Commit**

```bash
git add scripts/train/05_split_dataset.py
git commit -m "feat: add train/validation dataset split script"
```

---

### Task 6: Implement `deploy_to_anima.py`

**Files:**
- Create: `scripts/train/deploy_to_anima.py`

**Purpose:** Copy trained RVC model files to Anima's RVC directory and update `config/singing.yaml`.

**Step 1: Write the script**

```python
#!/usr/bin/env python3
"""Deploy trained model to Anima.

Steps:
1. Copy .pth to RVC weights/
2. Copy .index to RVC logs/
3. Update config/singing.yaml with new model name
4. Verify inference works (optional dry-run)
"""
import re
import shutil
from pathlib import Path

import yaml
from loguru import logger


def load_config() -> dict:
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def main():
    config = load_config()
    char_name = config["character"]["name"]
    rvc_path = Path(config["anima"]["rvc_path"])
    singing_config_path = Path(config["anima"]["config_path"])
    
    # Source files (from RVC WebUI training output)
    # RVC stores trained models at: RVC_PATH/weights/{exp_name}.pth
    # and indexes at: RVC_PATH/logs/{exp_name}.index
    src_pth = rvc_path / config["anima"]["weights_subdir"] / f"{char_name}.pth"
    src_index = rvc_path / config["anima"]["index_subdir"] / f"{char_name}.index"
    
    if not src_pth.exists():
        logger.error(f"Model not found: {src_pth}")
        logger.info("Did you train the model? Expected in RVC weights/ directory.")
        return
    
    # They're already in the right place if trained via RVC WebUI
    logger.info(f"Model found: {src_pth}")
    if src_index.exists():
        logger.info(f"Index found: {src_index}")
    else:
        logger.warning(f"Index not found: {src_index} — will skip index in config")
    
    # Update config/singing.yaml
    if singing_config_path.exists():
        with open(singing_config_path) as f:
            singing_cfg = yaml.safe_load(f) or {}
        
        if "singing" not in singing_cfg:
            singing_cfg["singing"] = {}
        if "rvc" not in singing_cfg["singing"]:
            singing_cfg["singing"]["rvc"] = {}
        
        rvc_cfg = singing_cfg["singing"]["rvc"]
        rvc_cfg["model_name"] = f"{char_name}.pth"
        if src_index.exists():
            rvc_cfg["index_path"] = f"logs/{char_name}.index"
        rvc_cfg["f0_method"] = config["rvc"]["f0_method"]
        
        with open(singing_config_path, "w") as f:
            yaml.dump(singing_cfg, f, default_flow_style=False, allow_unicode=True)
        logger.info(f"Updated {singing_config_path}")
    else:
        logger.warning(f"singing.yaml not found at {singing_config_path}")
    
    # Verify
    logger.info("✅ Deployment complete!")
    logger.info(f"   Model: {char_name}.pth → {rvc_path / 'weights/' / f'{char_name}.pth'}")
    logger.info(f"   Index: {char_name}.index → {rvc_path / 'logs/' / f'{char_name}.index'}")
    logger.info(f"   Config: {singing_config_path} updated")


if __name__ == "__main__":
    main()
```

**Step 2: Dry-run test**

Run: `python scripts/train/deploy_to_anima.py`
Expected: Shows model not found (expected — no model trained yet) or deployment confirmation if model exists.

**Step 3: Commit**

```bash
git add scripts/train/deploy_to_anima.py
git commit -m "feat: add Anima deployment script for trained RVC models"
```

---

### Task 7: Create RVC Training Quick Reference

**Files:**
- Create: `docs/rvc-training-guide.md`

**Purpose:** Step-by-step guide for the RVC WebUI training phase (the only manual step).

**Step 1: Write the guide**

```markdown
# RVC WebUI Training Guide

## Overview

The preprocessing scripts produce a ready-to-train dataset at `data/training/ready/`. 
This guide covers the manual RVC WebUI training step.

## Step 1: Launch RVC WebUI

```bash
cd C:/Users/30262/RVC20240604Nvidia
python webui.py
```

Open browser at `http://127.0.0.1:7865`

## Step 2: Go to "Train" tab

### 2a: Experiment Name
- Enter: `shige_utage` (matching config.yaml character.name)

### 2b: Target Sample Rate
- Select: **48000** (matches config)

### 2c: Version
- Select: **v2** (ContentVec)

### 2d: Training Data Path
- Browse and select: `data/training/ready/`

### 2e: One-click Preprocessing
- Click: **Preprocess**
- Wait for: HuBERT feature extraction + RMVPE F0 extraction
- Check console for completion

## Step 3: Train

### Parameters
| Field | Value |
|-------|-------|
| Batch size | 16 |
| Number of epochs | 300 |
| Save every N epochs | 50 |
| Pretrained G | `f0G48k.pth` |
| Pretrained D | `f0D48k.pth` |

### Start Training
- Click: **Train**
- Expected time: 2-4 hours (RTX 5090D)
- Monitor loss curves in WebUI

### Checkpoint Selection
After training completes:
- Try the last checkpoint first (300 epochs)
- If artifacts, try earlier ones (200, 250 epochs)
- The best checkpoint is usually the last one before overfitting

## Step 4: Build Index

- Go to "Index" sub-tab
- Click: **Build Index**
- This creates `logs/shige_utage.index`

## Step 5: Quick Test

- Go to "Inference" tab
- Load model: `shige_utage`
- Upload a test audio file
- Set f0_method: `rmvpe`
- Test inference
- If quality is poor, consider training more epochs (500) or adding more data

## Expected Results

With 30-60 min clean data + 300 epochs:
- Natural character voice with minimal artifacts
- Good high-pitch reproduction (helped by augmentation)
- Better results with more singing data (especially high notes)

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Metallic/robotic sound | Reduce epochs, check data quality |
| Voice not matching character | Add more character-specific data, increase index_rate |
| High notes sound weak | Add more high-note singing data, check pitch augmentation |
| Training loss not decreasing | Check data quality, increase batch size |
| Out of memory | Reduce batch size to 12 or 8 |
```
