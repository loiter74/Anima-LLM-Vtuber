# 音乐模块 Bug 修复 — 设计文档

**日期**: 2026-05-19
**状态**: 设计中
**关联**: commit `852f093` (feat: singing module)

## 概述

E2E 管道已跑通（下载→分离→转录→RVC→混音），前端 `MusicPage.vue` 已就绪。本次修复三个 bug：

| # | Bug | 严重度 | 根因 |
|---|-----|--------|------|
| 1 | 播放混音时口型受 BGM 干扰 | 高 | WaveformDisplay 回退到混音分析器 |
| 2 | 歌词未使用 Live2D 字幕叠加层，无翻译 | 高 | 歌唱歌词未接入 SubtitleOverlay 管道 |
| 3 | RVC 音色替换产出哑音/静音段 | 高 | sanyueqi.pth 无索引文件，index_rate=0 |

---

## Bug 1: 口型驱动修复

### 根因分析

`WaveformDisplay.getMouthValue()` 在 `vocalsAnalyser` 为 null 时回退到 `analyser`（混音音频分析器）：

```typescript
// WaveformDisplay.vue:48 — 当前代码
function getMouthValue(): number {
  const a = vocalsAnalyser || analyser  // ← 回退到混音(BGM)!
}
```

触发条件：`vocals_url` 为空或未加载时，`loadVocalsForLipSync('')` 提前返回，`vocalsAnalyser` 保持 null。

混音音频含 BGM → 纯背景音乐段也有能量 → 口型持续张开。

### 修复方案

#### 1.1 WaveformDisplay.vue — 移除混音回退

```
修改: getMouthValue()
  旧: const a = vocalsAnalyser || analyser
  新: const a = vocalsAnalyser; if (!a) return 0
```

`analyser` 仅用于**波形可视化**（canvas 绘制），不再参与 mouth value 计算。

#### 1.2 WaveformDisplay.vue — 同步隐藏人声音频

```
新增: syncVocalsTime(time: number)
  → vocalsAudio.currentTime = time  // 跟随主播放位置
```

#### 1.3 MusicPage.vue — handleTimeupdate 同步

```
修改: handleTimeupdate(time)
  → 新增 waveformRef.value?.syncVocalsTime(time)
  → 确保隐藏人声音频与主播放器同步
```

#### 1.4 MusicPage.vue — 无 vocals_url 时禁用口型

```
修改: MusicPage 模板
  → <WaveformDisplay :vocals-url="store.result?.vocals_url || ''" />
  → 当 vocals_url 为空时 WaveformDisplay 不启动唇同步
```

### 影响范围

| 文件 | 改动 |
|------|------|
| `WaveformDisplay.vue` | 移除 analyser 回退 + 新增 syncVocalsTime |
| `MusicPage.vue` | handleTimeupdate 同步 + 条件渲染 |
| `MusicCard.vue` | 无改动（已用 startLipSync + volumes，正确路径） |

---

## Bug 2: 歌词字幕集成 + .ass 文件修复

### .ass 文件诊断（新增）

**文件格式正确** — 标准 ASS v4.00+，90行/77条对话，时间轴无重叠无负值。

**内容不可用的根因**：

| # | 问题 | 详情 |
|---|------|------|
| 1 | 🔴 **语言不匹配** | `language="zh"` 但测试歌曲 (BV1GJ411x7h7) 是英文。whisper 强制用中文音素解释英文 → 前3行乱码 ("音 飞逼 桶 汪娟") |
| 2 | 🟠 **模型太弱** | `model_size="base"` (74M) vs `large-v3` (1550M)。"You know the rules and so do I" → "You're the rules and so the few are" |
| 3 | 🟡 **whisper 根本限制** | whisper 为**语音识别**设计，非唱歌。歌声有音高变化+BGM干扰，精度天然低 |

**解决方案：混合获取（B站原生 API 优先 + whisper large-v3 回退）**：

```
B站 URL 输入
    ├── 是音频区 (au) → B站 API: GET /audio/music-service-c/web/song/lyric?sid={sid}
    │                    → LRC 歌词 100% 准确，含时间轴
    └── 是视频区 (BV) → whisper large-v3 + language="auto"
                         → 自动检测语言，准确度显著提升
```

### 根因分析

歌唱歌词由 `MusicPage.vue` 内联渲染（`v-for` 列表），未使用现有的 `SubtitleOverlay` 组件。`SubtitleOverlay` 通过 `useSubtitle` composable 监听 `sentence` Socket.IO 事件，支持双语显示、拖拽定位、自动隐藏。

`LyricLine.translation` 始终为空 — 无 LLM 翻译步骤。

#### .ass 格式修复（紧急）

| 问题 | 修复 | 位置 |
|------|------|------|
| 缺失末尾换行 → 播放器拒绝加载 | `"\n".join(...)` → `"\n".join(...) + "\n"` | `lyrics.py:42` |
| `int(float*100)` 截断 → 28/77时间戳差1cs | `int(...)` → `int(... + 0.5)` 四舍五入 | `lyrics.py:78` |
| `language="zh"` 强制中文 → 英文歌乱码 | `language: "zh"` → `language: null` (auto) | `singing.yaml` |
| `model_size="base"` 太弱 | `"base"` → `"large-v3"` | `singing.yaml` |
| whisper 路径硬编码 | 移到 singing.yaml 配置 | `lyrics.py:32` |

#### 2.1 后端 — B站原生歌词 API（优先）

`bilibili.py` 新增 `fetch_lyrics_lrc()`：

```python
async def fetch_lyrics_lrc(self, url: str) -> str | None:
    """从 B站 API 获取 LRC 歌词。音频区(au)直接获取，视频区(BV)需先查找关联音频"""
    # 音频区: GET /audio/music-service-c/web/song/lyric?sid={sid}
    # 返回 LRC 格式，100% 准确
    ...
```

在 `svc_pipeline.py` 中优先调用，失败时回退 whisper：

```python
# Stage 3.5: 歌词获取 (B站API → whisper回退)
lrc = await self._downloader.fetch_lyrics_lrc(url)
if lrc:
    lyric_lines = parse_lrc(lrc)  # 原生歌词
else:
    ass_content = await self._lyrics_gen.transcribe(vocals_path)
    lyric_lines = parse_ass(ass_content)
```

#### 2.2 后端 — LLM 歌词翻译

`lyrics.py` 新增 `translate_lyrics()` 方法：

```python
async def translate_lyrics(
    self, lines: list[LyricLine], 
    llm_engine, source_lang="zh", target_lang="en"
) -> list[LyricLine]:
    """为每行歌词调用 LLM 翻译"""
    for line in lines:
        if line.text.strip():
            translation = await llm_engine.chat(
                f"Translate: {line.text}"
            )
            line.translation = translation.strip()
    return lines
```

在 `svc_pipeline.py` 中调用（Stage 4.5，歌词确认后）：

```python
if self._llm:
    lyric_lines = await self._lyrics_gen.translate_lyrics(
        lyric_lines, self._llm
    )
```

#### 2.2 后端 — 逐行歌词事件

`singing_handlers.py` 新增 `sing:subtitle_line` 事件，格式复用 `SentenceEvent`：

```python
# 发送格式
{
    "text": "歌詞行文字",
    "translation": "Lyric translation",  
    "is_complete": True,     # 每行都是完整行
    "lang": "zh",
    "target_lang": "en"
}
```

前端播放时发送 `sing:subtitle_sync` 请求：

```python
# 前端 → 后端
socket.emit('sing:subtitle_sync', { index: currentLyricIndex })
# 后端 → 前端
socket.emit('sing:subtitle_line', { text, translation, ... })
```

#### 2.3 前端 — useSubtitle 扩展

`useSubtitle.ts` 新增 `sing:subtitle_line` 监听：

```typescript
socket.on('sing:subtitle_line', (data) => {
  showSubtitle(data.text, data.translation, data.lang, data.target_lang)
  // 歌唱模式：不自动隐藏，等待下一行替换
  cancelHide()
})
```

#### 2.4 前端 — MusicPage 移除内联歌词

```diff
- <!-- 内联歌词列表 (v-for) -->
+ <!-- 歌词由 SubtitleOverlay 在 Live2D 下方显示 -->
```

### 数据流

```
音乐播放 currentTime
    ↓ MusicPage.handleTimeupdate
匹配当前歌词行 index
    ↓ socket.emit('sing:subtitle_sync', { index })
后端 singing_handlers
    ↓ socket.emit('sing:subtitle_line', { text, translation })
useSubtitle composable
    ↓ showSubtitle(text, translation)
SubtitleOverlay.vue → Live2D 下方玻璃面板
```

### 影响范围

| 文件 | 改动 |
|------|------|
| `lyrics.py` | 新增 translate_lyrics() |
| `svc_pipeline.py` | Stage 4.5 调用翻译 |
| `singing_handlers.py` | 新增 sing:subtitle_sync 监听 + sing:subtitle_line 发送 |
| `useSubtitle.ts` | 新增 sing:subtitle_line 监听 |
| `MusicPage.vue` | 移除内联歌词 + 新增 sync 发送 |
| `SubtitleOverlay.vue` | 无改动（已有功能满足需求） |

---

## Bug 3: AI 歌声哑音

### 根因分析

RVC 推理管线 (`pipeline.py`) 在 `index_rate=0` 时跳过特征检索：

```python
# pipeline.py:224-245 — 被跳过的代码
if index_rate > 0:
    # FAISS 检索 → 注入目标音色特征
    ...
# index_rate=0 → feats 保持原始 HuBERT 特征（未映射）
```

`sanyueqi.pth` 无 `.index` 文件 → 即使设置 `index_rate > 0` 也无法检索。

后果：解码器收到训练分布外的特征 → 无法合成 → 输出静音。

### 修复方案

#### 3.1 生成索引文件

```bash
# 使用 RVC WebUI 的 "Train Index" 功能
# 输入: sanyueqi 训练特征文件 (.npy, 位于 logs/sanyueqi/)
# 输出: logs/sanyueqi.index

# 或通过命令行:
python tools/train_index.py \
  --root_path logs/sanyueqi \
  --index_path logs/sanyueqi.index
```

#### 3.2 更新 singing.yaml

```yaml
rvc:
  enabled: true
  model_name: "sanyueqi.pth"
  index_path: "logs/sanyueqi.index"     # 曾为空
  index_rate: 0.6                        # 曾为 0
  filter_radius: 5                       # 曾为 3 (F0 平滑)
  rms_mix_rate: 0.5                      # 曾为 0.25 (保留原音量包络)
  protect: 0.5                           # 曾为 0.33 (启用特征保护)
  f0_method: "rmvpe"                     # 不变
```

#### 3.3 可选优化

| 优化项 | 说明 |
|--------|------|
| Demucs GPU 模式 | 移除 `-d cpu`，提升分离质量 → 减少伪影 → RMVPE 更准确 |
| whisper `large-v3` | 提升歌词识别准确度（目前 `base` 模型质量差） |
| 备选 RVC 模型 | 如 sanyueqi 索引仍不理想，从 [HuggingFace](https://huggingface.co/lj1995/VoiceConversionWebUI) 下载 kikiV1 等已附带索引的 v2 模型 |

### 影响范围

| 文件 | 改动 |
|------|------|
| `singing.yaml` | 更新 RVC 参数 |
| RVC 数据目录 | 生成 `logs/sanyueqi.index` |
| `separator.py` | 可选: 移除 `-d cpu` (需 CUDA) |

---

## 实施计划

三个修复各自独立，可并行实施：

| 顺序 | Bug | 预估改动量 | 依赖 |
|------|-----|-----------|------|
| 1 | 口型驱动 | ~20 行 | 无 |
| 2 | 歌词字幕 | ~80 行 | 无（LLM 翻译可选） |
| 3 | 哑音修复 | 配置 + 索引生成 | RVC WebUI 环境 |
