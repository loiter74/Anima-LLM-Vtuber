# Training Paradigm — Character Singing Voice Model

## Quick Start

```bash
# 1. Put raw audio in data/training/raw/
# 2. One command: prep → train → deploy
python -m scripts.train.cli --character shige_utage

# Or step by step:
python scripts/train/prepare_data.py                         # 数据预处理
python -m scripts.train.cli --character shige_utage --skip-prep  # 训练+部署
python -m scripts.train.cli --character shige_utage --deploy-only  # 仅部署
python -m scripts.train.cli --character shige_utage --epochs 500   # 自定义轮数
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
└── ready/            # Final dataset for RVC training
```

## CLI Reference

| Flag | Description |
|------|-------------|
| `-c, --character` | Character name (from config.yaml) |
| `-d, --data` | Custom data directory |
| `-e, --epochs` | Training epochs (default: 300) |
| `-b, --batch-size` | Batch size (default: 16) |
| `--sr` | Sample rate (default: 48000) |
| `--skip-prep` | Skip data preparation |
| `--preprocess-only` | Only preprocess, no training |
| `--deploy-only` | Only deploy existing model |
| `--dry-run` | Show commands without running |
