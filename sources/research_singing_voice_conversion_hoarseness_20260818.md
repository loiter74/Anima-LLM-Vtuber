# 公开歌声转换方案与“发哑/电子音残留”诊断

检索日期：2026-08-18

## 当前样本与公开实践的差异

- 当前远坂凛 RVC 模型使用约 32 分钟 TTS 说话语料，只训练到 50 epoch。RVC 官方 FAQ 对高质量、低底噪、时长充分的数据允许增加到约 200 epoch，并明确说明：模型自身训练充分后，对源音色和底模的依赖会下降，索引的重要性也会降低。
- RVC 官方建议的数据时长为约 10–50 分钟；当前时长合格，但语料域是 TTS 说话，不包含真实歌声中的延音、换气、颤音、强弱变化和高音区。官方训练说明也指出歌唱必须使用带 F0 的模型。
- 当前推理源含有原唱的 Auto-Tune、混响和伴奏泄漏。RVC 保留源音频的内容、F0 和演唱风格，因此提高索引只能加强目标音色，不能删除已经烙在源人声里的效果器轨迹。
- 当前 50 epoch 模型在 `index_rate=0.30→0.55`、`protect=0.50→0.33` 的 A/B 中持续发哑，说明主要瓶颈不是推理旋钮，而是模型训练程度、说话/歌唱域差异和源人声前处理。

## 公开路线

### 1. 继续 RVC：低成本修正

1. 保留 F0/RMVPE。
2. 对现有干净语料继续训练，并至少比较 100、150、200 epoch 检查点；不直接把 200 视为必然最优。
3. 语料中补充目标音色的高音、延音、换气和强弱变化。若只有 TTS，可先生成“歌唱化练声”语料，但仍属于近似域适配。
4. 推理前使用更强的人声分离与 DeEcho/DeReverb；索引只用于控制音色泄漏，不作为音质修复器。

该路线改动最小，但无法保证消除 TTS 语料带来的哑音，也无法移除源轨中的硬 Auto-Tune。

### 2. Seed-VC F0-conditioned：最小可行替代实验

Seed-VC 的公开实现提供零样本语音/歌声转换；其界面明确要求歌声转换启用 F0-conditioned 模型，并允许自动 F0 匹配或半音偏移。公开实现建议参考音频不超过 25 秒，长源音频采用分块处理，并注明 50–100 diffusion steps 用于更高质量。

优点是无需重新训练远坂凛模型，只需一段干净的远坂凛 TTS 参考音频即可做 12 秒 A/B。缺点是原仓库在 2025-11-21 已归档，适合作为质量验证原型，不宜直接成为长期唯一运行时依赖。

### 3. Amphion Vevo2：当前长期方向

Vevo2 同时支持 style-preserved / style-converted VC/SVC、歌唱风格转换和文本转歌声。公开预训练组件包含基于约 7,000 小时歌声数据训练的 prosody/content-style tokenizer，并提供 FM-only 与 AR+FM 两种推理路径。

它更接近“重新生成目标角色的歌声”，而不只是给原唱换音色，因此最有希望弱化原唱电子音和风格残留；代价是模型链更重、Python 3.10 独立环境和宿主服务集成成本更高，必须先做显存与延迟探针。

### 4. 传统专用 SVC

- so-vits-svc 使用 ContentVec/F0、NSF-HiFiGAN，并可叠加 shallow diffusion，目标就是歌声音色转换；但官方仓库已归档。
- DDSP-SVC 仍提供较轻量的歌声转换、RMVPE 和歌声 vocoder/浅扩散路径，训练成本接近 RVC；它仍需要目标歌声域训练数据，不能由纯说话 TTS 直接等价替代。

## 前处理

`python-audio-separator` 公开支持 MDX、VR、Demucs、MDXC/RoFormer，并明确包含去噪、去 echo/reverb 等音频处理。推荐在 VC 前比较：

1. BS-RoFormer/MDXC 人声分离；
2. DeEcho/DeReverb；
3. 再进入 F0-conditioned SVC；
4. 转换后只做轻量去齿音、动态 EQ 和限幅，不用后期 EQ 掩盖模型哑音。

## 针对 Anima 的推荐顺序

1. **先做 12 秒 Seed-VC F0-conditioned 零样本 A/B**：用现有干净远坂凛 TTS 参考音频，源轨先做 DeEcho/DeReverb。它能最快判断“算法路线”是否是主因。
2. **并行准备 RVC e100/e150/e200 检查点**：只训练，不立刻替换生产模型；每档用同一测试段盲听。
3. Seed-VC 若明显优于 RVC，进入 Vevo2 FM-only 的显存/延迟探针，再决定是否新增 Anima 宿主 SVC provider。
4. 若 Vevo2 过重，则采用 DDSP-SVC 或保留 Seed-VC 原型；不再继续堆叠 RVC index/protect 参数。

## 一手资料

- RVC 官方 FAQ（数据时长、epoch、index/tone leakage）：https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/blob/main/docs/en/faq_en.md
- RVC 官方训练说明（F0、HuBERT、索引、预训练权重）：https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/blob/main/docs/en/training_tips_en.md
- Seed-VC 论文：https://arxiv.org/abs/2411.09943
- Seed-VC 公开歌声界面与参数：https://github.com/Plachtaa/seed-vc/blob/main/app.py
- Amphion SVC 官方 recipe：https://github.com/open-mmlab/Amphion/blob/main/egs/svc/README.md
- Vevo2 官方实现：https://github.com/open-mmlab/Amphion/blob/main/models/svc/vevo2/README.md
- so-vits-svc 官方仓库：https://github.com/svc-develop-team/so-vits-svc
- DDSP-SVC 官方仓库：https://github.com/yxlllc/DDSP-SVC
- Audio Separator 官方仓库：https://github.com/nomadkaraoke/python-audio-separator
