# Singing Module Design — AI Cover via GPT-SoVITS SVC

**Date:** 2026-05-17
**Status:** approved

## Overview

Add a singing module that enables AI cover song generation: download Bilibili audio → separate vocals → ASR lyrics → human-confirmed subtitles → GPT-SoVITS SVC voice conversion → mix → playback with Live2D lip sync.

## Pipeline

```
Bilibili URL → ① Download (jjdown)
                  ↓
               ② Source Separation (UVR)
                  → backing_track.wav
                  → vocals.wav
                  ↓
               ③ ASR Lyrics Recognition (Whisper/FasterWhisper)
                  → .ass subtitle file
                  ↓
               ④ ⏸ Human Review (Aegisub)
                  → User downloads .ass, edits timing, re-uploads
                  ↓
               ⑤ SVC Voice Conversion (GPT-SoVITS)
                  → converted_vocals.wav
                  ↓
               ⑥ Mix (backing + converted vocals)
                  → final_song.wav
                  ↓
               ⑦ Frontend Playback + Live2D Lip Sync
```

## Backend Architecture

### Service Package

```
src/animetta/services/singing/
├── __init__.py          # Re-exports
├── interface.py         # SingingService ABC
├── svc_pipeline.py      # Pipeline orchestrator
├── bilibili.py          # jjdown wrapper
├── separator.py         # UVR bridge
├── lyrics.py            # ASR → .ass generation
├── svc_bridge.py        # GPT-SoVITS SVC API bridge
├── mixer.py             # pydub/ffmpeg mixing
└── factory.py           # Service factory
```

### Socket.IO Events

| Direction | Event | Payload |
|-----------|-------|---------|
| Client → Server | `sing:process` | `{ url: string }` |
| Server → Client | `sing:progress` | `{ stage: string, progress: number, message?: string }` |
| Server → Client | `sing:lyrics_ready` | `{ ass_content: string }` — notify user to review |
| Client → Server | `sing:confirm_lyrics` | `{ ass_content: string }` — user-approved lyrics |
| Server → Client | `sing:complete` | `{ audio_url: string, duration: number, lyrics: LyricLine[] }` |
| Server → Client | `sing:error` | `{ error: string, stage?: string }` |
| Client → Server | `sing:cancel` | — cancel current processing |

### Pipeline States

```
idle → downloading → separating → transcribing
  → waiting_lyrics (human-in-the-loop)
  → converting → mixing → done
```

Each state pushes `sing:progress` events. On `waiting_lyrics`, the pipeline pauses until `sing:confirm_lyrics` is received.

### GPT-SoVITS SVC Integration

- Calls GPT-SoVITS api_v2.py SVC endpoint (`/svc` if available) or TTS reference mode
- Input: separated vocals WAV + reference audio for voice cloning
- Output: converted vocals WAV
- Configurable: top_k, top_p, temperature, speed

### Audio Output

- Final output directory: `data/singing/outputs/{session_id}/`
- Files: `backing.wav`, `vocals.wav`, `converted.wav`, `final.wav`
- Cleanup handled by pipeline lifecycle

## Frontend Architecture

### New Files

```
frontend/src/
├── components/singing/
│   ├── MusicCard.vue           # Main card component
│   ├── ProcessTimeline.vue     # 5-step progress indicator
│   ├── WaveformDisplay.vue     # Audio amplitude visualization
│   └── PlaybackControls.vue    # Play/pause/seek/volume
├── composables/useSinging.ts   # Socket.IO event handlers
├── stores/singing.ts           # Pinia store (song state, progress, playback)
└── types/singing.ts            # TypeScript interfaces
```

### UI Integration

- **New tab** "🎵 音乐" in `InteractivePanel.vue` (between "人格" and "设置")
- **Lyrics displayed** via existing `SubtitleOverlay.vue` — new `sing:lyric` events feed into subtitle display
- **Audio playback** via existing `useAudioPlayback.ts` + `useLipSync.ts` for Live2D mouth animation

### MusicCard Component Layout

```
┌─ 🎵 音乐 ───────────────────────────┐
│                                      │
│  [📎 B站链接...]  [开始制作]         │
│                                      │
│  ── 处理进度 ──                      │
│  ✅ 下载音频                         │
│  ⏳ 人声分离 ████████░░ 80%          │
│  ⏸ 歌词识别 → 待确认                │
│  ☐ 歌声转换                         │
│  ☐ 混合输出                         │
│                                      │
│  ── 聆听成品 ──                      │
│  ◀⏸▶  ████████████░░ 01:23/03:45   │
│  ╱~~~~╲   ← 波形                    │
│  ╲____╱                             │
│                                      │
└──────────────────────────────────────┘
```

### Lyric → Subtitle Flow

```
sing:lyric { text, translation?, start_ms, end_ms }
  → useSinging.ts timer-driven scheduling
  → calls useSubtitle.showSubtitle() at each lyric line
  → SubtitleOverlay.vue renders glassmorphism overlay
```

### Live2D Lip Sync

- During playback: real-time `AnalyserNode` volume extraction → `useLipSync`
- Reuses existing `useAudioPlayback.ts` infrastructure
- (Future) Trigger preset dance motions based on BPM/beat detection

## Configuration

```yaml
# config/singing.yaml
singing:
  demucs_model: "htdemucs"
  uvr_model: "UVR-MDX-NET-Inst_HQ_3"
  gpt_sovits:
    base_url: "http://127.0.0.1:9880"
    svc_endpoint: "/svc"
    ref_audio_path: ""
    prompt_text: ""
  bilibili:
    downloader: "jjdown"
    output_dir: "./data/singing/downloads"
  output_dir: "./data/singing/outputs"
  asr:
    model: "base"  # Whisper model size
    language: "zh"
```

## Out of Scope (v1)

- LLM-triggered singing ("唱一首...")
- Dance/action generation for Live2D
- Real-time streaming singing
- Multiple song queue / playlist
- Song library management
- Pitch correction / autotune
- Multi-track mixing (volume balance, EQ)

## Future Iterations

1. **Live2D actions** — BPM detection → trigger dance motion presets
2. **LLM integration** — "唱一首 X" via tool calling + graph node
3. **Real-time preview** — stream converted audio chunks during SVC
4. **Multi-model SVC** — support RVC/SoVITS as alternative backends
