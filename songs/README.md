# 角色中文翻唱工作区

这里是远坂凛中文歌声转换的单一离线工作目录。仓库已准备好配置、清单、固定划分、RVC
Baseline 计划、统一评测、AB 记录和分句精修流程；本地已导入角色游戏语音并完成首轮自动
质检，原始音频、处理结果、测试歌曲、模型权重和制作产物均不进入版本控制。

## 当前状态

| 阶段 | 已准备 | 等待你提供 |
| --- | --- | --- |
| 数据登记 | 远坂凛中文语音 693 条已归档；689 条有可用转写并登记到 `sources.csv` | 补写 4 条无文本语音 |
| 处理与质检 | 689 条已转为 48 kHz 单声道 PCM WAV；270 条自动标记优先复核 | 逐条人工听审并修正 ASR 回退文本 |
| 固定划分 | 按 `source_id` 分组的冻结命令 | 至少两个已接受来源组 |
| Baseline | RVC v2 + RMVPE 参数、fail-fast 命令计划 | GPU 峰值探针、正式训练 |
| 统一评测 | 低/中/高音区协议、版本和 AB 表 | 有合法使用权的固定中文测试片段 |
| 精修制作 | 分轨、分句、重生成、RX、DAW 交付协议 | 具体歌曲工程与人工制作 |
| 模型升级 | 同验证集收益门禁 | RVC 稳定后再评估新模型 |

## 目录

```text
songs/
├── project.toml                  # 唯一项目参数
├── manifests/                    # 来源、质检、划分、评测、版本、AB、分句任务
├── audio/                        # 本地原始/处理/训练/验证音频，不入库
├── runs/                         # checkpoint、index、日志、候选发布清单，不入库
├── evaluation/                   # 固定测试协议、输入和渲染
└── production/                   # 分轨、分句、RVC、RX、DAW、母带制作区
```

## 1. 收集期间

每个原始文件占 `manifests/sources.csv` 一行。`source_id` 必须稳定且唯一；同一段录音的
切片必须沿用同一个 `source_id`。`audio_relpath` 写相对本目录的路径，例如
`audio/raw/story-001.wav`。`source_reference` 记录游戏、章节或资源定位，`usage_rights`
记录素材使用依据；不要把不明来源资源混入数据集。

原始音频放入 `audio/raw/`，不要覆盖或重命名已经登记的文件。当前可先检查空骨架：

```powershell
py -3.13 -m scripts.train.workspace --project songs check --stage scaffold
```

## 2. 处理、质检和人工筛选

数据到齐后，运行格式统一和自动质检。它输出 48 kHz、单声道、PCM WAV，并把时长、峰值、
噪声底、近似 SNR、静音、削波、发声占比和 F0 范围写入 `clips.csv`：

```powershell
py -3.13 -m scripts.train.prepare_data --project songs --workers 4
```

自动指标只负责标记候选异常，不能替代耳朵。逐条试听后，把 `review_status` 从 `pending`
改为 `accepted` 或 `rejected`，填写 `reviewer` 和 `review_notes`。重点排除背景音乐、混响、
多人重叠、爆音、严重降噪、水声、错字和角色外声线。

复核完成后冻结验证集；命令默认拒绝覆盖已有 `split.csv`：

```powershell
py -3.13 -m scripts.train.workspace --project songs freeze-split
py -3.13 -m scripts.train.materialize_dataset --project songs
py -3.13 -m scripts.train.workspace --project songs check --stage dataset
```

新增数据应建立新的 dataset revision，旧版本及旧验证集继续保留用于回放，不要直接
`--force` 重算当前基线。Baseline 默认关闭音高增强；若后续启用，只能增强训练集。

## 3. RVC Baseline

先生成确定性计划，不启动 GPU：

```powershell
py -3.13 -m scripts.train.cli --project songs --run-id character-rvc-v001
```

实际训练前必须按根目录 GPU 规则记录显卡、显存、进程 PID 与完整命令行，确认同类任务唯一，
再用相同 batch 做有界峰值探针。只有探针保留至少 `max(总显存 25%, 6 GiB)` 空闲时，才把
证据写成 `templates/gpu-probe-evidence.json` 的结构并执行：

```powershell
py -3.13 -m scripts.train.cli --project songs --run-id character-rvc-v001 `
  --execute --gpu-probe-evidence songs/runs/character-rvc-v001/gpu-probe.json
```

训练 fail-fast，任何子步骤失败都会停止。最后一步只建 index，不自动改正式配置。
RVC 会保留 `G_2333333.pth` / `D_2333333.pth` checkpoint；长任务中断后，先重新检查 GPU
进程和峰值预算，再用同一个 `run-id` 加 `--resume` 恢复，不能同时使用
`--preprocess-only`。

## 4. 固定评测和版本迭代

在 `evaluation/audio/` 放入有合法使用权的短测试片段，并填写
`manifests/evaluation_cases.csv`。至少覆盖 `low`、`mid`、`high`，固定起止时间和音频
SHA-256；这些片段不得进入训练集。

```powershell
py -3.13 -m scripts.train.workspace --project songs freeze-evaluation
py -3.13 -m scripts.train.workspace --project songs check --stage evaluation
```

冻结后若测试集确实需要变化，应建立新的 evaluation revision 并保留旧锁，不要用新测试集
覆盖旧模型成绩。

每个 checkpoint 用同一推理网格生成渲染，在 `versions.csv` 记录数据集、测试集、模型、
index 和配置哈希。评审时先盲听，再填写 `ab_reviews.csv` 的音准、音色、咬字、高音稳定性、
杂音和总体胜负。统一规则见 [evaluation/protocol.md](evaluation/protocol.md)。

只有 RVC 基线稳定后才评估 Seed-VC、扩散、Flow 或其他 SVC。新方案必须使用同一
evaluation revision，平均总分至少提升 0.25，且不能出现单用例回退，才进入迁移讨论。

## 5. 精修制作

歌曲制作遵循 [production/README.md](production/README.md)：先分离人声与伴奏，在 Melodyne
修音准和节奏，再按短句转换；异常句单独重做，最后使用 RX 修复并在 DAW 混音、母带。
每句参数和问题写入 `production_jobs.csv`，禁止用整首反复试参覆盖可复现记录。

## 6. 晋级到 Animetta

候选模型通过统一评测后，先生成包含模型/index 哈希和正式配置片段的晋级候选，不直接
覆盖生产清单。真正晋级时必须同步 `config/host-rvc.yaml` 与 `config/singing.yaml`，通过
`runtime_lifecycle.py host-rvc-restart` 更新宿主服务，再用正式 `/live.html` 验证模型身份、
真实转换、音频响应和持久播放证据。
