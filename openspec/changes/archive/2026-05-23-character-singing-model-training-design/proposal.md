# Character Singing Voice Model Training Design — 赛马娘 / Uma Musume

**Date:** 2026-05-23
**Status:** draft
**Target Character:** 诗歌剧 (Nice Nature) — CV: Hikaru Toono
**GPU:** NVIDIA RTX 5090D 24GB VRAM
**Use Case:** Anima 唱歌集成 + 独立 RVC 使用

## Overview

为动漫角色训练 RVC v2 歌声模型，集成到 Anima 的唱歌 Pipeline。重点强化高音表现。整套流程设计为**可重复范式（paradigm）**，同一套脚本换角色数据即可复用。

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Paradigm Pipeline                           │
│                                                                 │
│  Stage 1: DATA COLLECTION                                       │
│  ├─ uma-voice-dataset-creator → 游戏语音 (.acb → .wav)          │
│  ├─ yt-dlp + Demucs → B站翻唱人声分离                           │
│  └─ HuggingFace → 已有台词数据集                                │
│                                                                 │
│  Stage 2: PREPROCESS (全脚本自动化)                              │
│  ├─ slice → 静音切除 + 4-15s 切片，覆盖全音域                   │
│  ├─ WORLD pitch augment → ±2 semitones 音高数据增强             │
│  ├─ denoise → UVR5 降噪/去混响                                 │
│  ├─ normalize → 响度归一化 + 统一 48kHz                         │
│  └─ split → 训练/验证 90%/10%                                   │
│                                                                 │
│  Stage 3: TRAIN (RVC WebUI)                                     │
│  ├─ 内置预处理 → HuBERT 768-dim + RMVPE F0 + 切片              │
│  ├─ 模型训练 → RVC v2, 48kHz, batch=16, epochs=300-500         │
│  └─ 建索引 → FAISS IVF 特征索引                                │
│                                                                 │
│  Stage 4: DEPLOY (脚本自动化)                                    │
│  ├─ 复制 .pth → RVC weights/                                   │
│  ├─ 复制 .index → RVC logs/                                    │
│  └─ 更新 config/singing.yaml                                    │
│                                                                 │
│  Stage 5: INFERENCE                                             │
│  ├─ Anima: B站链接 → 分离 → RVC → 混音 → 输出                 │
│  └─ Standalone: RVC WebUI / Python infer.py                     │
└─────────────────────────────────────────────────────────────────┘
```

## Stage 1: Data Collection

### Data Sources

| Source | Tool | Est. Volume | Quality |
|--------|------|-------------|---------|
| Game client voice | `uma-voice-dataset-creator` | 500-2000+ clips | ★★★★★ Clean |
| Bilibili covers | yt-dlp + Demucs separation | 5-10 songs | ★★★★ Needs separation |
| HuggingFace dataset | `Plachta/Umamusume-voice-text-pairs` | ~1000 utterances | ★★★★ Clean |

### Target

- **Total clean vocal duration:** 30-60 minutes
- **Singing data:** at least 10 minutes (critical for high-pitch performance)
- **Pitch coverage:** must include character's highest notes

## Stage 2: Preprocessing Pipeline

### Scripts Structure

```
scripts/train/
├── config.yaml                # 数据集配置（角色信息、参数）
├── 01_collect_data.py         # 从游戏/B站/HF收集原始音频
├── 02_slice_and_denoise.py   # 切片 + 降噪 + 去混响
├── 03_normalize.py            # 响度归一化 + 48kHz统一采样率
├── 04_augment_pitch.py        # WORLD 音高增强
├── 05_split_dataset.py        # 训练/验证集划分
└── README.md                  # 使用说明
```

### High-Pitch Augmentation (04_augment_pitch.py)

```python
# Core logic — WORLD-based pitch shift data augmentation
for audio in dataset:
    keep_original(audio)                    # 保留原版
    augment(audio, shift=+2)                # +2 semitones
    if estimate_pitch(audio) < 400 Hz:      # 中低音片段额外增强
        augment(audio, shift=+4)
    augment(audio, shift=-2)                # 向下增强泛化
```

### Audio Requirements

- Format: WAV 16-bit (or FLAC)
- Sample rate: 48kHz (保留高音谐波)
- Clip length: 4-15 seconds (RVC 内部会再切到 4s)
- SNR: > 20dB (否则需要降噪)
- No reverb/echo (用 UVR5 DeReverb 处理)

## Stage 3: RVC Training Configuration

### Training Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Sample rate | **48kHz** | 保留高音谐波，优于 40kHz |
| Model version | **v2** | ContentVec 768-dim，显著优于 v1 |
| F0 method | **rmvpe** | 专为歌声设计，InterSpeech 2023 SOTA |
| Batch size | **16** | 5090D 24GB 足够 |
| Epochs | **300-500** | 30-60min 数据，300 轮收敛 |
| Enable F0 | **Yes** | 必须启用，否则丢失旋律 |
| Pretrained model | `f0G48k.pth` + `f0D48k.pth` | 48kHz 预训练权重 |
| Save frequency | Every **50** epochs | 可回溯最佳 checkpoint |

### Training Steps (RVC WebUI)

```
1. 打开 RVC WebUI → 训练标签页
2. 设置实验名: shige_utage（诗歌剧）
3. 选择处理后的数据集目录
4. Target sample rate: 48000
5. Version: v2
6. 预处理 → 等待 HuBERT + RMVPE 特征提取完成
7. 设置训练参数（如上表）
8. 开始训练 → 300 epochs（约 2-4 小时）
9. 建索引 → FAISS IVF256 index
10. 测试推理 → 验证效果
11. 如效果不够 → 继续训练到 500 epochs 或调整数据
```

## Stage 4: Anima Integration

### Config Changes

```yaml
# config/singing.yaml
rvc:
  model_name: "shige_utage.pth"
  index_path: "logs/shige_utage.index"
  f0_method: "rmvpe"
  f0_up_key: 0
  index_rate: 0.75
  filter_radius: 3
  rms_mix_rate: 0.25
  protect: 0.33
```

### File Deployment

```bash
# 复制模型文件到 RVC 目录
cp output/shige_utage.pth C:/Users/30262/RVC20240604Nvidia/weights/
cp output/shige_utage.index C:/Users/30262/RVC20240604Nvidia/logs/
```

### Deploy Script (deploy_to_anima.py)

自动完成：
1. 复制 .pth 和 .index
2. 更新 config/singing.yaml
3. 验证推理是否正常

## Stage 5: Inference & High-Pitch Optimization

### Anima Pipeline Integration

对现有 `svc_pipeline.py` 无改动需求 —— 只需更新配置。RVCBridge 自动使用新模型。

### High-Pitch Inference Parameters

```yaml
# 推理时高音优化参数
rvc:
  f0_up_key: 0          # 源调合适时保持 0
  # 如源调偏低: +2 到 +5
post_process:
  high_shelf_gain: 3.0  # 10kHz 高频提升 +3dB
  presence_boost: 1.5   # 4kHz 临场感提升 +1.5dB
  de_ess: true          # 去齿音（高频提升后必需）
```

### Standalone Usage

```bash
# 直接用 RVC WebUI 推理
# 或用命令行:
python rvc_infer.py \
  --model shige_utage \
  --input song.wav \
  --f0_method rmvpe \
  --f0_up_key 0 \
  --index_rate 0.75
```

## High-Pitch Enhancement Strategy Summary

| Layer | Technique | Where |
|-------|-----------|-------|
| **Data** | 包含最高音歌曲数据 | Stage 1 |
| **Augmentation** | WORLD pitch shift ±2/±4 semitones | Stage 2 |
| **Training** | 48kHz + RMVPE + v2 | Stage 3 |
| **Inference** | f0_up_key 调整 + index_rate=0.75 | Stage 4/5 |
| **Post-processing** | 10kHz 高频提升 + 临场感 EQ | Stage 5 |

## Paradigm Repeatability

整套流程设计为可复用范式：

```bash
# 换一个新角色只需要:
# 1. 准备新角色的音频数据到 raw_data/ 目录
# 2. 修改 config.yaml 中的角色名
# 3. 运行脚本
python scripts/train/01_collect_data.py    # (如果手动收集可跳过)
python scripts/train/02_slice_and_denoise.py
python scripts/train/03_normalize.py
python scripts/train/04_augment_pitch.py
python scripts/train/05_split_dataset.py
# 4. RVC WebUI 训练（参数同上，只需改实验名）
# 5. python scripts/train/deploy_to_anima.py
```

## Future Iterations (Stage 2)

1. **脚本化 RVC 训练** — 直接调用 RVC 训练核心，完全一键自动化
2. **GPT-SoVITS 双模训练** — 增加 TTS 歌声生成能力
3. **自动音域检测** — 分析角色音频自动推荐 f0_ceil/f0_floor
4. **音色相似度评估** — 自动评估模型与原声的相似度

## References

- RVC WebUI: https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI
- uma-voice-dataset-creator: https://github.com/sumomomomomo/uma-voice-dataset-creator
- HuggingFace Umamusume dataset: Plachta/Umamusume-voice-text-pairs
- SingAug (pitch augmentation): arXiv:2203.17001
- RMVPE (pitch extraction): InterSpeech 2023
- Energy-Balanced Flow Matching: arXiv:2512.04793
