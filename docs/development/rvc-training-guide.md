# RVC WebUI Training Guide

> 配套 `scripts/train/` 范式使用。完成数据预处理后，用本指南训练模型。

## Overview

The preprocessing scripts (`scripts/train/02` through `05`) produce a ready-to-train dataset at `data/training/ready/`. This guide covers the manual RVC WebUI training step — the only non-automated part of the pipeline.

## Step 1: Launch RVC WebUI

```bash
cd C:/Users/30262/RVC20240604Nvidia
python webui.py
```

Open browser at `http://127.0.0.1:7865`

## Step 2: Go to "Train" tab

### 2a: Experiment Name
- Enter: `shige_utage` (matching `config.yaml` → `character.name`)

### 2b: Target Sample Rate
- Select: **48000** (matching `config.yaml` → `rvc.sample_rate`)

### 2c: Version
- Select: **v2** (ContentVec, 768-dim)

### 2d: Training Data Path
- Browse and select: `data/training/ready/`

### 2e: One-click Preprocessing
- Click: **Preprocess**
- Wait for: HuBERT feature extraction + RMVPE F0 extraction (check console for completion)
- This generates: `.npy` feature files for each audio clip

## Step 3: Train

### Parameters

| Field | Value | Note |
|-------|-------|------|
| Batch size | **16** | 5090D 24GB can handle this |
| Number of epochs | **300** | Start here, go to 500 if needed |
| Save every N epochs | **50** | Allows backtracking to best checkpoint |
| Pretrained G | `f0G48k.pth` | 48kHz generator (must match sample rate) |
| Pretrained D | `f0D48k.pth` | 48kHz discriminator |

### Start Training
- Click: **Train**
- Expected time: **2-4 hours** on RTX 5090D (for 300 epochs, ~30-60 min data)
- Monitor loss curves in WebUI — they should be steadily decreasing

### Checkpoint Selection
After training completes, try checkpoints at different epochs:
- **300** (last): Usually best if loss was still decreasing
- **250**: Try if 300 shows artifacts
- **200**: Fallback if overfitting
- The best checkpoint is typically the last one before validation loss plateaus

## Step 4: Build Index

- Go to "Index" sub-tab
- Click: **Build Index**
- This creates `logs/shige_utage.index`
- The FAISS index stores feature vectors for timbre retrieval

## Step 5: Quick Test

- Go to "Inference" tab
- Load model: `shige_utage`
- Upload a test audio file (preferably a song segment not in training data)
- Set parameters:

| Parameter | Value |
|-----------|-------|
| f0_method | `rmvpe` |
| f0_up_key | 0 (adjust if needed) |
| index_rate | 0.75 |
| filter_radius | 3 |
| rms_mix_rate | 0.25 |
| protect | 0.33 |

- Click "Convert" and listen to the result

## Step 6: Deploy to Anima

After training and testing:

```bash
python scripts/train/deploy_to_anima.py
```

This copies the model config into `config/singing.yaml` automatically.

## Expected Results

With 30-60 min clean data + 300 epochs on RTX 5090D:

| Metric | Expected |
|--------|----------|
| Voice similarity | 80-90% (with 30+ min data) |
| High-pitch quality | Good (helped by pitch augmentation in step 4) |
| Artifacts | Minimal (with clean training data) |
| Training time | 2-4 hours |

## Troubleshooting

| Issue | Likely Cause | Fix |
|-------|--------------|-----|
| Metallic/robotic sound | Overfitting | Try earlier checkpoint (epoch 200) |
| Voice doesn't match character | Insufficient data | Add more character-specific audio, especially singing |
| High notes sound weak/absent | No high-note data in training set | Add songs with high notes, check `04_augment_pitch.py` ran correctly |
| Training loss not decreasing | Data quality issue | Check for corrupted audio, background noise |
| CUDA out of memory | Batch too large | Reduce batch size from 16 to 12 or 8 |
| Index build fails | Not enough features | Check feature extraction completed successfully |

## Repeat for New Characters

This whole process is designed to be a **repeatable paradigm**. For a new character:

```bash
# 1. Edit scripts/train/config.yaml → change character.name
# 2. Place raw audio in data/training/raw/
# 3. Run preprocessing
python scripts/train/02_slice_and_denoise.py
python scripts/train/03_normalize.py
python scripts/train/04_augment_pitch.py
python scripts/train/05_split_dataset.py
# 4. RVC WebUI — same steps, change experiment name
# 5. Deploy
python scripts/train/deploy_to_anima.py
```
