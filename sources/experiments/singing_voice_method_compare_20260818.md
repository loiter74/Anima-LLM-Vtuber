# 歌唱声线公开方法对比实验（2026-08-18）

## 结论

在同一首歌、同一 12 秒片段和同一 `+4` 半音条件下，**C（Seed-VC + htdemucs）是当前首选**：其高频能量占比和频谱质心均明显高于现有 RVC 方案，同时中位 F0 与 A 基本一致，说明亮度差异不是由音高漂移造成的。D（Seed-VC + BS-RoFormer + DeReverb）可作为去串音、去混响的备选，但本片段的亮度代理略低于 C。

只替换人声分离链路并不能解决现有 RVC 的哑音。B 相比 A 的高频能量占比下降约 32%，频谱质心下降约 10%，因此不建议继续以“RVC + 更重的前处理”作为主路线。

这些指标只用于定位暗哑和频谱损失，不能替代对音色个性、咬字自然度和伪影的盲听判断。全曲转换前应优先盲听 C 与 D，并补测一个高音密集片段。

## 固定输入

- 歌曲：Bilibili `BV12L3x67ECs`
- 片段：`57.25s–69.25s`，12 秒
- 原始混音：`00-source-mix-57.25s.wav`
- 原始混音 SHA-256：`78EFBA8E8388108DC19A6540E0493E4DC4988B32ED489C22A9BF7EC327F575F8`
- 声线参考：`tosaka_rin_tts_0131.wav`，15.92 秒，24 kHz 单声道
- 声线参考 SHA-256：`9DCED6418E323C574D23426EEF5C245C9F21C38DD6D60A1808B8F6C05F1D7CA0`
- 声线来源：Qwen3-TTS `tosaka-rin-cn`
- 所有转换：串行执行，不并发 GPU 任务

## 方法矩阵

| 编号 | 人声分离 | 声线转换 | 关键参数 |
| --- | --- | --- | --- |
| A | htdemucs | 当前 RVC `tosaka_rin_tts_v1.pth` | RMVPE，index 0.30，filter 5，RMS 0.50，protect 0.50，`+4` 半音 |
| B | BS-RoFormer + DeReverb-Echo V2 | 当前 RVC `tosaka_rin_tts_v1.pth` | 与 A 相同 |
| C | htdemucs | Seed-VC（F0-conditioned） | diffusion 30，CFG 0.7，length 1.0，FP16，`+4` 半音 |
| D | BS-RoFormer + DeReverb-Echo V2 | Seed-VC（F0-conditioned） | 与 C 相同 |

公开实现与固定身份：

- Seed-VC：官方仓库提交 `51383efd921027683c89e5348211d93ff12ac2a8`
- BS-RoFormer 模型 SHA-256：`5B84F37E8D444C8CB30C79D77F613A41C05868FF9C9AC6C7049C00AEFAE115AA`
- DeReverb-Echo V2 模型 SHA-256：`396432F5AF25992FE82D0286634BD879027C073721DB6AB10199E75459708B9F`
- RVC 返回身份：`rvc-webui-host / tosaka_rin_tts_v1.pth / tosaka-rin-cn`

## 统一盲听文件

原始转换结果保留；下列盲听文件统一为 48 kHz、单声道、12 秒，目标响度约 `-18 LUFS`，避免音量差影响判断。

| 编号 | 文件 | 实测 LUFS | 真峰值 | SHA-256 |
| --- | --- | ---: | ---: | --- |
| A | `A-listen-rvc-htdemucs.wav` | -17.99 | -1.50 dBTP | `99D5E5F862F9DEE706FC2610B18BE82F679887E85168B6A32609F17B5AF495B4` |
| B | `B-listen-rvc-roformer-deecho.wav` | -18.02 | -2.31 dBTP | `0127F96284C9FBDC6EFFE287A531E6D281F356869BC1371FEE5CAA806D2CC518` |
| C | `C-listen-seedvc-htdemucs.wav` | -17.97 | -1.50 dBTP | `36AAE9582F052311F7D253F6DB1A00FB205AAB5F4D291333FB50C1E2596224DE` |
| D | `D-listen-seedvc-roformer-deecho.wav` | -17.91 | -1.50 dBTP | `CD328575D82F5E2FB9F82BC425691C2510CE4683F8B336ACFF7320E1C3E1437D` |

输出目录：`C:\Users\30262\Music\Animetta\BV12L3x67ECs-method-compare-20260818`

## 客观代理指标

| 编号 | 频谱质心 | 4 kHz 以上能量占比 | 中位 F0 |
| --- | ---: | ---: | ---: |
| A | 1872 Hz | 0.003996 | 206.46 Hz |
| B | 1676 Hz | 0.002714 | 201.74 Hz |
| C | 2164 Hz | 0.011498 | 206.46 Hz |
| D | 2123 Hz | 0.009640 | 200.58 Hz |

解释：C、D 的高频占比分别约为 A 的 2.9 倍和 2.4 倍；C 与 A 的中位 F0 相同。该结果支持 Seed-VC 能减少当前 RVC 的暗哑感，但不能单独证明角色个性更强或伪影更少。

## GPU 门禁与峰值

- GPU：NVIDIA GeForce RTX 5090 D v2，24,455 MiB
- 长任务准入下限：`max(25%, 6 GiB) = 6,114 MiB` 空闲显存
- Seed-VC C/D 任务前空闲：18,430 MiB
- 任务中最低空闲：14,965 MiB
- 任务中最高总显存占用：9,071 MiB
- 任务后空闲：18,430 MiB
- C/D 实时系数：0.242 / 0.238
- 最终无 Seed-VC、分离或转换客户端残留；现有宿主 TTS/RVC 服务未重启

全程保留至少 14,965 MiB 空闲显存，远高于门禁下限。

## 复现注意事项

1. Windows 上的当前 `torchaudio` 保存路径依赖 TorchCodec，但与共享 FFmpeg DLL 不兼容；兼容入口只把最终 WAV 保存替换为 SoundFile PCM16，不改模型和推理路径。
2. Hugging Face 大文件下载需设置 `HF_HUB_DISABLE_XET=1` 并显式预取模型，避免 Xet 长时间停留在部分文件。
3. 后续最短路径是：显存门禁 → 固定参考与片段 → 显式预取 → 串行 Seed-VC → 统一响度 → 指标与盲听；不再让推理过程逐个发现下载或保存后端依赖。
