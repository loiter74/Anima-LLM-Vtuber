# Singing Module Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build AI cover song generation module — Bilibili download → UVR source separation → ASR lyrics → GPT-SoVITS SVC → mix → frontend playback with Live2D lip sync.

**Architecture:** New `services/singing/` backend package as standalone pipeline, not a graph node. Socket.IO events for progress/control. New frontend tab in InteractivePanel sidebar with music card UI.

**Tech Stack:** Python (FastAPI/Socket.IO), Vue 3 + Pinia + UnoCSS, GPT-SoVITS api_v2, UVR, jjdown/yt-dlp, faster-whisper, pydub

---

## Backend Tasks

### Task 1: Create singing config

**Files:**
- Create: `config/singing.yaml`
- Create: `src/animetta/config/singing_config.py`

**Step 1: Create YAML config**

Write `config/singing.yaml`:

```yaml
# Anima 唱歌模块配置
singing:
  gpt_sovits:
    base_url: "http://127.0.0.1:9880"
    svc_endpoint: "/svc"
    ref_audio_path: ""
    prompt_text: ""
    text_lang: "zh"
    top_k: 15
    top_p: 1.0
    temperature: 1.0
    speed: 1.0
  bilibili:
    downloader: "jjdown"
    output_dir: "./data/singing/downloads"
  uvr:
    model: "UVR-MDX-NET-Inst_HQ_3"
    output_dir: "./data/singing/separated"
  asr:
    model_size: "base"
    language: "zh"
    output_dir: "./data/singing/lyrics"
  svc:
    output_dir: "./data/singing/converted"
  output_dir: "./data/singing/outputs"
  max_file_age_days: 7
```

**Step 2: Create Pydantic config class**

Create `src/animetta/config/singing_config.py`:

```python
"""Singing module Pydantic configuration."""

from pydantic import BaseModel, Field
from typing import Optional


class GPTSoVITSConfig(BaseModel):
    base_url: str = "http://127.0.0.1:9880"
    svc_endpoint: str = "/svc"
    ref_audio_path: str = ""
    prompt_text: str = ""
    text_lang: str = "zh"
    top_k: int = 15
    top_p: float = 1.0
    temperature: float = 1.0
    speed: float = 1.0


class BilibiliConfig(BaseModel):
    downloader: str = "jjdown"
    output_dir: str = "./data/singing/downloads"


class UVRConfig(BaseModel):
    model: str = "UVR-MDX-NET-Inst_HQ_3"
    output_dir: str = "./data/singing/separated"


class ASRConfig(BaseModel):
    model_size: str = "base"
    language: str = "zh"
    output_dir: str = "./data/singing/lyrics"


class SVCConfig(BaseModel):
    output_dir: str = "./data/singing/converted"


class SingingConfig(BaseModel):
    gpt_sovits: GPTSoVITSConfig = Field(default_factory=GPTSoVITSConfig)
    bilibili: BilibiliConfig = Field(default_factory=BilibiliConfig)
    uvr: UVRConfig = Field(default_factory=UVRConfig)
    asr: ASRConfig = Field(default_factory=ASRConfig)
    svc: SVCConfig = Field(default_factory=SVCConfig)
    output_dir: str = "./data/singing/outputs"
    max_file_age_days: int = 7
```

**Step 3: Verify syntax**

Run: `python -c "from anima.config.singing_config import SingingConfig; print(SingingConfig())"`
Expected: prints default config

**Step 4: Commit**

```bash
git add config/singing.yaml src/animetta/config/singing_config.py
git commit -m "feat(singing): add config and Pydantic model"
```

---

### Task 2: Create singing service package skeleton

**Files:**
- Create: `src/animetta/services/singing/__init__.py`
- Create: `src/animetta/services/singing/interface.py`

**Step 1: Create package `__init__.py`**

```python
"""Singing module — AI Cover via GPT-SoVITS SVC pipeline."""

from .interface import SingingService, PipelineStage, LyricLine, SongResult
from .svc_pipeline import SVC Pipeline

__all__ = [
    "SingingService",
    "SVC Pipeline",
    "PipelineStage",
    "LyricLine",
    "SongResult",
]
```

**Step 2: Create `interface.py`**

```python
"""Singing service interface and type definitions."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PipelineStage(str, Enum):
    IDLE = "idle"
    DOWNLOADING = "downloading"
    SEPARATING = "separating"
    TRANSCRIBING = "transcribing"
    WAITING_LYRICS = "waiting_lyrics"
    CONVERTING = "converting"
    MIXING = "mixing"
    DONE = "done"


@dataclass
class LyricLine:
    text: str
    translation: str = ""
    start_ms: int = 0
    end_ms: int = 0


@dataclass
class SongResult:
    audio_path: str
    duration_sec: float
    lyrics: list[LyricLine] = field(default_factory=list)


@dataclass
class PipelineProgress:
    stage: PipelineStage
    progress: float  # 0-100
    message: str = ""


class SingingService(ABC):
    """Abstract base for singing pipeline service."""

    @abstractmethod
    async def process(self, url: str) -> SongResult:
        """Execute full pipeline: download → separate → transcribe → SVC → mix."""
        ...

    @abstractmethod
    async def cancel(self) -> None:
        """Cancel current processing."""
        ...

    @abstractmethod
    async def confirm_lyrics(self, ass_content: str) -> None:
        """Resume pipeline with user-confirmed lyrics."""
        ...

    @abstractmethod
    async def get_progress(self) -> PipelineProgress:
        """Get current pipeline progress."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources."""
        ...
```

**Step 3: Register in `services/__init__.py`**

Add to `src/animetta/services/__init__.py`:
```python
from .singing import SingingService

__all__.append("SingingService")
```

**Step 4: Commit**

```bash
git add src/animetta/services/singing/__init__.py src/animetta/services/singing/interface.py \
       src/animetta/services/__init__.py
git commit -m "feat(singing): add service package skeleton and interface"
```

---

### Task 3: Implement Bilibili downloader

**Files:**
- Create: `src/animetta/services/singing/bilibili.py`

**Step 1: Create downloader module**

```python
"""Bilibili audio downloader — jjdown wrapper."""

import asyncio
import os
from pathlib import Path
from typing import Optional

from loguru import logger


class BilibiliDownloader:
    """Download audio from Bilibili video URL using jjdown."""

    def __init__(self, output_dir: str = "./data/singing/downloads"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def download(self, url: str) -> str:
        """Download audio track from Bilibili URL.
        
        Returns:
            Path to downloaded audio file (WAV).
        
        Raises:
            RuntimeError: If download fails.
        """
        logger.info(f"Downloading Bilibili audio: {url}")
        
        # Generate unique filename from URL hash
        import hashlib
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        output_path = self.output_dir / f"{url_hash}.wav"
        
        if output_path.exists():
            logger.info(f"Using cached download: {output_path}")
            return str(output_path)
        
        # Run jjdown in a subprocess
        cmd = [
            "jjdown",
            "--url", url,
            "--format", "wav",
            "--output", str(output_path),
            "--audio-only", "true",
        ]
        
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode != 0:
                raise RuntimeError(
                    f"jjdown failed (code {proc.returncode}): {stderr.decode()[:500]}"
                )
            
            if not output_path.exists():
                raise RuntimeError(f"Downloaded file not found: {output_path}")
            
            logger.info(f"Download complete: {output_path}")
            return str(output_path)
            
        except FileNotFoundError:
            raise RuntimeError(
                "jjdown not found. Install with: pip install jjdown"
            ) from None

    async def close(self) -> None:
        """Clean up."""
        pass
```

**Step 2: Commit**

```bash
git add src/animetta/services/singing/bilibili.py
git commit -m "feat(singing): add Bilibili downloader (jjdown wrapper)"
```

---

### Task 4: Implement UVR source separator

**Files:**
- Create: `src/animetta/services/singing/separator.py`

**Step 1: Create separator module**

```python
"""Source separation using UVR (Ultimate Vocal Remover)."""

import asyncio
import os
from pathlib import Path
from typing import Tuple

from loguru import logger


class SourceSeparator:
    """Separate vocals from backing track using UVR."""

    def __init__(
        self,
        model: str = "UVR-MDX-NET-Inst_HQ_3",
        output_dir: str = "./data/singing/separated",
    ):
        self.model = model
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def separate(self, audio_path: str) -> Tuple[str, str]:
        """Separate audio into vocals and backing track.
        
        Returns:
            Tuple of (vocals_path, backing_path).
        """
        logger.info(f"Separating audio: {audio_path} (model={self.model})")
        
        session_dir = self.output_dir / Path(audio_path).stem
        session_dir.mkdir(parents=True, exist_ok=True)
        
        vocals_path = session_dir / "vocals.wav"
        backing_path = session_dir / "backing.wav"
        
        if vocals_path.exists() and backing_path.exists():
            logger.info(f"Using cached separation: {session_dir}")
            return str(vocals_path), str(backing_path)
        
        # Run UVR via Python (assumes uvr module is installed)
        cmd = [
            "python", "-m", "uvr",
            "--model", self.model,
            "--input", audio_path,
            "--output", str(session_dir),
            "--vocals-only", "false",  # output both stems
        ]
        
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate(timeout=600)  # 10min timeout
            
            if proc.returncode != 0:
                raise RuntimeError(
                    f"UVR failed (code {proc.returncode}): {stderr.decode()[:500]}"
                )
            
            # Verify outputs exist
            if not vocals_path.exists():
                raise RuntimeError(f"Vocals file not found: {vocals_path}")
            if not backing_path.exists():
                raise RuntimeError(f"Backing file not found: {backing_path}")
            
            logger.info(f"Separation complete: vocals={vocals_path}, backing={backing_path}")
            return str(vocals_path), str(backing_path)
            
        except asyncio.TimeoutError:
            raise RuntimeError("UVR processing timed out (>10 min)")

    async def close(self) -> None:
        pass
```

**Step 2: Commit**

```bash
git add src/animetta/services/singing/separator.py
git commit -m "feat(singing): add UVR source separator"
```

---

### Task 5: Implement ASR lyrics module

**Files:**
- Create: `src/animetta/services/singing/lyrics.py`

**Step 1: Create lyrics module**

```python
"""Lyrics recognition — ASR + .ass generation."""

import asyncio
import os
from pathlib import Path

from loguru import logger


class LyricsGenerator:
    """Generate .ass subtitle from vocals audio using Whisper."""

    def __init__(
        self,
        model_size: str = "base",
        language: str = "zh",
        output_dir: str = "./data/singing/lyrics",
    ):
        self.model_size = model_size
        self.language = language
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def transcribe(self, audio_path: str) -> str:
        """Transcribe vocals audio and generate .ass subtitle content.
        
        Returns:
            .ass subtitle file content as string.
        """
        logger.info(f"Transcribing vocals: {audio_path}")
        
        import faster_whisper
        
        model = faster_whisper.WhisperModel(self.model_size)
        segments, info = await asyncio.to_thread(
            lambda: list(model.transcribe(audio_path, language=self.language))
        )
        
        ass_lines = self._segments_to_ass(segments)
        ass_content = self._build_ass_header() + "\n".join(ass_lines)
        
        logger.info(f"Transcription complete: {len(segments)} segments")
        return ass_content

    def _build_ass_header(self) -> str:
        return """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
Title: Singing Lyrics
Language: zh

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,48,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,2,2,30,2,20,20,134

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def _segments_to_ass(self, segments) -> list:
        lines = []
        for seg in segments:
            start = self._sec_to_ass_time(seg.start)
            end = self._sec_to_ass_time(seg.end)
            text = seg.text.strip()
            if text:
                lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
        return lines

    def _sec_to_ass_time(self, seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        cs = int((seconds - int(seconds)) * 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    def parse_lyric_lines(self, ass_content: str) -> list:
        """Parse .ass content into LyricLine list."""
        from .interface import LyricLine
        
        lines = []
        for line in ass_content.split("\n"):
            if line.startswith("Dialogue:"):
                parts = line.split(",", 9)
                if len(parts) >= 10:
                    start_str = parts[1].strip()
                    end_str = parts[2].strip()
                    text = parts[9].strip()
                    lines.append(LyricLine(
                        text=text,
                        start_ms=self._ass_time_to_ms(start_str),
                        end_ms=self._ass_time_to_ms(end_str),
                    ))
        return lines

    def _ass_time_to_ms(self, time_str: str) -> int:
        h, m, s = time_str.split(":")
        s, cs = s.split(".")
        return (int(h) * 3600 + int(m) * 60 + int(s)) * 1000 + int(cs) * 10

    async def close(self) -> None:
        pass
```

**Step 2: Commit**

```bash
git add src/animetta/services/singing/lyrics.py
git commit -m "feat(singing): add ASR lyrics generator (.ass format)"
```

---

### Task 6: Implement GPT-SoVITS SVC bridge

**Files:**
- Create: `src/animetta/services/singing/svc_bridge.py`

**Step 1: Create SVC bridge module**

```python
"""GPT-SoVITS SVC API bridge — converts vocals to target voice."""

import asyncio
from pathlib import Path
from typing import Optional

import httpx
from loguru import logger

from anima.config.singing_config import GPTSoVITSConfig


class SVCBridge:
    """Bridge to GPT-SoVITS api_v2.py SVC endpoint."""

    def __init__(self, config: GPTSoVITSConfig):
        self.config = config
        self._client: Optional[httpx.AsyncClient] = None

    def _ensure_client(self):
        if self._client is not None:
            return
        timeout = httpx.Timeout(300.0, connect=10.0)  # 5min for SVC
        self._client = httpx.AsyncClient(
            base_url=self.config.base_url.rstrip("/"),
            timeout=timeout,
        )

    async def convert(
        self,
        source_audio_path: str,
        output_path: str,
        pitch_adjust: int = 0,
    ) -> str:
        """Convert source vocals to target voice via SVC.
        
        Args:
            source_audio_path: Path to source vocals WAV.
            output_path: Path for converted output WAV.
            pitch_adjust: Semitone adjustment (0 = no change).
        
        Returns:
            Path to converted audio file.
        """
        self._ensure_client()
        logger.info(f"SVC converting: {source_audio_path}")

        output_path_obj = Path(output_path)
        output_path_obj.parent.mkdir(parents=True, exist_ok=True)

        # Try SVC endpoint first
        try:
            with open(source_audio_path, "rb") as f:
                files = {"audio": f}
                data = {
                    "pitch_adjust": pitch_adjust,
                    "ref_audio_path": self.config.ref_audio_path,
                    "prompt_text": self.config.prompt_text,
                }
                response = await self._client.post(
                    self.config.svc_endpoint,
                    files=files,
                    data=data,
                )
        except httpx.ConnectError as e:
            raise ConnectionError(
                f"GPT-SoVITS server at {self.config.base_url} not reachable. "
                f"Ensure api_v2.py is running. Error: {e}"
            ) from e

        if response.status_code == 200:
            output_path_obj.write_bytes(response.content)
            logger.info(f"SVC complete: {output_path_obj}")
            return str(output_path_obj)
        else:
            error_msg = response.text[:500]
            raise RuntimeError(
                f"SVC failed (HTTP {response.status_code}): {error_msg}"
            )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
```

**Step 2: Commit**

```bash
git add src/animetta/services/singing/svc_bridge.py
git commit -m "feat(singing): add GPT-SoVITS SVC bridge"
```

---

### Task 7: Implement audio mixer

**Files:**
- Create: `src/animetta/services/singing/mixer.py`

**Step 1: Create mixer module**

```python
"""Audio mixer — blend converted vocals with backing track."""

import subprocess
from pathlib import Path

from loguru import logger


class AudioMixer:
    """Mix vocals and backing track into final output."""

    def __init__(self, output_dir: str = "./data/singing/outputs"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def mix(self, vocals_path: str, backing_path: str, output_name: str = "final.wav") -> str:
        """Mix vocals and backing track using ffmpeg.
        
        Args:
            vocals_path: Path to converted vocals WAV.
            backing_path: Path to backing track WAV.
            output_name: Output filename.
        
        Returns:
            Path to mixed output file.
        """
        output_path = self.output_dir / output_name
        logger.info(f"Mixing vocals + backing → {output_path}")

        # Use ffmpeg to mix two audio streams
        cmd = [
            "ffmpeg",
            "-i", vocals_path,
            "-i", backing_path,
            "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=2",
            "-ac", "2",  # stereo
            "-y",  # overwrite
            str(output_path),
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg mix failed: {result.stderr[:500]}")
            
            # Get duration
            duration = await self._get_duration(str(output_path))
            logger.info(f"Mix complete: {output_path} ({duration:.1f}s)")
            return str(output_path)
            
        except FileNotFoundError:
            raise RuntimeError("ffmpeg not found. Install ffmpeg first.") from None

    async def _get_duration(self, audio_path: str) -> float:
        """Get audio duration in seconds using ffprobe."""
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return float(result.stdout.strip())
        except (ValueError, subprocess.TimeoutExpired):
            return 0.0

    async def close(self) -> None:
        pass
```

**Step 2: Commit**

```bash
git add src/animetta/services/singing/mixer.py
git commit -m "feat(singing): add audio mixer (ffmpeg)"
```

---

### Task 8: Implement pipeline orchestrator

**Files:**
- Create: `src/animetta/services/singing/svc_pipeline.py`

**Step 1: Create pipeline orchestrator**

```python
"""SVC pipeline orchestrator — coordinates all stages."""

import asyncio
import os
import shutil
from pathlib import Path
from typing import Optional, Callable

from loguru import logger

from .interface import (
    SingingService, PipelineStage, PipelineProgress,
    LyricLine, SongResult,
)
from .bilibili import BilibiliDownloader
from .separator import SourceSeparator
from .lyrics import LyricsGenerator
from .svc_bridge import SVCBridge
from .mixer import AudioMixer
from anima.config.singing_config import SingingConfig


class SVCPipeline(SingingService):
    """Full SVC pipeline: download → separate → transcribe → SVC → mix."""

    def __init__(self, config: SingingConfig):
        self.config = config
        self._stage = PipelineStage.IDLE
        self._progress = 0.0
        self._message = ""
        self._cancelled = False
        self._lyrics_ready: Optional[asyncio.Event] = None
        self._confirmed_ass: Optional[str] = None
        self._on_progress: Optional[Callable[[PipelineProgress], None]] = None
        self._session_dir: Optional[Path] = None
        
        # Sub-modules
        self._downloader = BilibiliDownloader(config.bilibili.output_dir)
        self._separator = SourceSeparator(
            model=config.uvr.model,
            output_dir=config.uvr.output_dir,
        )
        self._lyrics_gen = LyricsGenerator(
            model_size=config.asr.model_size,
            language=config.asr.language,
            output_dir=config.asr.output_dir,
        )
        self._svc = SVCBridge(config.gpt_sovits)
        self._mixer = AudioMixer(config.output_dir)

    def set_progress_callback(self, callback: Callable[[PipelineProgress], None]) -> None:
        self._on_progress = callback

    def _update_progress(self, stage: PipelineStage, progress: float, message: str = "") -> None:
        self._stage = stage
        self._progress = progress
        self._message = message
        if self._on_progress:
            self._on_progress(PipelineProgress(stage=stage, progress=progress, message=message))

    async def process(self, url: str) -> SongResult:
        """Execute full pipeline."""
        self._cancelled = False
        
        # Create session dir
        import hashlib
        from datetime import datetime
        session_id = hashlib.md5(f"{url}{datetime.now().isoformat()}".encode()).hexdigest()[:12]
        session_output_dir = Path(self.config.output_dir) / session_id
        session_output_dir.mkdir(parents=True, exist_ok=True)
        self._session_dir = session_output_dir

        try:
            # Stage 1: Download
            self._update_progress(PipelineStage.DOWNLOADING, 0, "Starting download...")
            audio_path = await self._downloader.download(url)
            self._check_cancelled()
            self._update_progress(PipelineStage.DOWNLOADING, 100, "Download complete")

            # Stage 2: Separate
            self._update_progress(PipelineStage.SEPARATING, 0, "Separating vocals...")
            vocals_path, backing_path = await self._separator.separate(audio_path)
            self._check_cancelled()
            self._update_progress(PipelineStage.SEPARATING, 100, "Separation complete")

            # Stage 3: Transcribe
            self._update_progress(PipelineStage.TRANSCRIBING, 0, "Transcribing lyrics...")
            ass_content = await self._lyrics_gen.transcribe(vocals_path)
            self._check_cancelled()
            
            # Save .ass for user review
            ass_path = session_output_dir / "lyrics.ass"
            ass_path.write_text(ass_content, encoding="utf-8")
            
            self._update_progress(PipelineStage.TRANSCRIBING, 100, "Lyrics ready")
            self._message = f"Lyrics saved to {ass_path}"

            # Stage 4: Wait for user confirmation
            self._update_progress(PipelineStage.WAITING_LYRICS, 0, "Awaiting lyrics confirmation...")
            self._lyrics_ready = asyncio.Event()
            self._confirmed_ass = None
            await self._lyrics_ready.wait()  # Blocks until confirm_lyrics() called
            self._check_cancelled()
            self._update_progress(PipelineStage.WAITING_LYRICS, 100, "Lyrics confirmed")

            # Parse confirmed lyrics
            lyric_lines = self._lyrics_gen.parse_lyric_lines(self._confirmed_ass)

            # Stage 5: SVC Convert
            self._update_progress(PipelineStage.CONVERTING, 0, "Converting vocals...")
            converted_path = session_output_dir / "converted.wav"
            await self._svc.convert(vocals_path, str(converted_path))
            self._check_cancelled()
            self._update_progress(PipelineStage.CONVERTING, 100, "Conversion complete")

            # Stage 6: Mix
            self._update_progress(PipelineStage.MIXING, 0, "Mixing audio...")
            final_path = await self._mixer.mix(str(converted_path), backing_path, f"{session_id}_final.wav")
            self._check_cancelled()
            self._update_progress(PipelineStage.MIXING, 100, "Mix complete")

            # Stage 7: Done
            duration = await self._mixer._get_duration(final_path)
            self._update_progress(PipelineStage.DONE, 100, "Complete!")
            
            return SongResult(
                audio_path=final_path,
                duration_sec=duration,
                lyrics=lyric_lines,
            )

        except asyncio.CancelledError:
            logger.info("Pipeline cancelled")
            self._stage = PipelineStage.IDLE
            raise

    def _check_cancelled(self) -> None:
        if self._cancelled:
            raise asyncio.CancelledError("Pipeline cancelled by user")

    async def cancel(self) -> None:
        self._cancelled = True
        if self._lyrics_ready and not self._lyrics_ready.is_set():
            self._lyrics_ready.set()  # Unblock waiting for lyrics

    async def confirm_lyrics(self, ass_content: str) -> None:
        self._confirmed_ass = ass_content
        if self._lyrics_ready and not self._lyrics_ready.is_set():
            self._lyrics_ready.set()

    async def get_progress(self) -> PipelineProgress:
        return PipelineProgress(
            stage=self._stage,
            progress=self._progress,
            message=self._message,
        )

    async def close(self) -> None:
        await self._downloader.close()
        await self._separator.close()
        await self._lyrics_gen.close()
        await self._svc.close()
        await self._mixer.close()
```

**Step 2: Commit**

```bash
git add src/animetta/services/singing/svc_pipeline.py
git commit -m "feat(singing): add pipeline orchestrator"
```

---

### Task 9: Add Socket.IO singing handlers

**Files:**
- Create: `src/animetta/orchestration/server/handlers/singing_handlers.py`
- Modify: `src/animetta/orchestration/server/routes.py`

**Step 1: Create singing handler**

```python
"""Singing module Socket.IO event handlers."""

import asyncio
import os
from typing import Optional, TYPE_CHECKING

from loguru import logger

from .base_handler import BaseSocketHandler

if TYPE_CHECKING:
    from socketio import AsyncServer
    from ..session import SessionManager
    from ..desktop import DesktopClientManager
    from ..live2d import Live2DManager


class SingingHandlers(BaseSocketHandler):
    """Singing pipeline event handlers."""

    def __init__(
        self,
        sio: "AsyncServer",
        session_manager: "SessionManager",
        desktop_manager: "DesktopClientManager",
        live2d_manager: "Live2DManager",
    ):
        super().__init__(sio, session_manager, desktop_manager, live2d_manager)
        self._pipeline: Optional["SVCPipeline"] = None

    async def on_sing_process(self, sid: str, data: dict) -> None:
        """Start singing pipeline: sing:process { url: string }"""
        url = data.get("url", "")
        if not url:
            await self.sio.emit("sing:error", {"error": "URL is required"}, to=sid)
            return

        try:
            from anima.services.singing.svc_pipeline import SVCPipeline
            from anima.config.singing_config import SingingConfig

            # Load config
            import yaml
            config_path = os.path.join(os.path.dirname(__file__), "../../../../config/singing.yaml")
            with open(config_path, "r") as f:
                raw = yaml.safe_load(f)
            config = SingingConfig(**raw.get("singing", {}))

            # Create pipeline
            self._pipeline = SVCPipeline(config)

            # Wire progress callback
            async def on_progress(progress):
                await self.sio.emit("sing:progress", {
                    "stage": progress.stage.value,
                    "progress": progress.progress,
                    "message": progress.message,
                }, to=sid)
                # If waiting for lyrics, notify frontend
                if progress.stage.value == "waiting_lyrics":
                    await self.sio.emit("sing:lyrics_ready", {
                        "message": progress.message,
                    }, to=sid)

            self._pipeline.set_progress_callback(
                lambda p: asyncio.ensure_future(on_progress(p))
            )

            # Run in background
            asyncio.ensure_future(self._run_pipeline(sid))

        except Exception as e:
            logger.error(f"sing:process error: {e}", exc_info=True)
            await self.sio.emit("sing:error", {"error": str(e)}, to=sid)

    async def _run_pipeline(self, sid: str) -> None:
        try:
            if self._pipeline is None:
                return
            result = await self._pipeline.process("")  # URL already captured
            await self.sio.emit("sing:complete", {
                "audio_url": f"/api/singing/audio/{os.path.basename(result.audio_path)}",
                "duration": result.duration_sec,
                "lyrics": [
                    {"text": l.text, "translation": l.translation,
                     "start_ms": l.start_ms, "end_ms": l.end_ms}
                    for l in result.lyrics
                ],
            }, to=sid)
        except asyncio.CancelledError:
            await self.sio.emit("sing:error", {"error": "Cancelled"}, to=sid)
        except Exception as e:
            logger.error(f"Pipeline failed: {e}", exc_info=True)
            await self.sio.emit("sing:error", {"error": str(e)}, to=sid)
        finally:
            self._pipeline = None

    async def on_sing_confirm_lyrics(self, sid: str, data: dict) -> None:
        """Confirm lyrics: sing:confirm_lyrics { ass_content: string }"""
        ass_content = data.get("ass_content", "")
        if self._pipeline and ass_content:
            await self._pipeline.confirm_lyrics(ass_content)

    async def on_sing_cancel(self, sid: str, data: dict) -> None:
        """Cancel pipeline: sing:cancel"""
        if self._pipeline:
            await self._pipeline.cancel()
```

**Step 2: Register in routes.py**

Add import to top of `routes.py`:
```python
from .handlers.singing_handlers import SingingHandlers
```

Add in `__init__` after existing handler inits:
```python
self.singing = SingingHandlers(
    sio, session_manager, self.desktop_manager, self.live2d_manager
)
```

Add event methods:
```python
async def on_sing_process(self, sid: str, data: dict) -> None:
    return await self.singing.on_sing_process(sid, data)

async def on_sing_confirm_lyrics(self, sid: str, data: dict) -> None:
    return await self.singing.on_sing_confirm_lyrics(sid, data)

async def on_sing_cancel(self, sid: str, data: dict) -> None:
    return await self.singing.on_sing_cancel(sid, data)
```

**Step 3: Commit**

```bash
git add src/animetta/orchestration/server/handlers/singing_handlers.py \
       src/animetta/orchestration/server/routes.py
git commit -m "feat(singing): add Socket.IO event handlers"
```

---

## Frontend Tasks

### Task 10: Create singing types and store

**Files:**
- Create: `frontend/src/types/singing.ts`
- Create: `frontend/src/stores/singing.ts`

**Step 1: Create TypeScript types**

`frontend/src/types/singing.ts`:
```typescript
export type PipelineStage =
  | 'idle'
  | 'downloading'
  | 'separating'
  | 'transcribing'
  | 'waiting_lyrics'
  | 'converting'
  | 'mixing'
  | 'done'
  | 'error'

export interface PipelineProgress {
  stage: PipelineStage
  progress: number
  message: string
}

export interface LyricLine {
  text: string
  translation: string
  start_ms: number
  end_ms: number
}

export interface SongResult {
  audio_url: string
  duration: number
  lyrics: LyricLine[]
}

export interface SongState {
  url: string
  status: PipelineStage
  progress: number
  message: string
  result: SongResult | null
  error: string
}
```

**Step 2: Create Pinia store**

`frontend/src/stores/singing.ts`:
```typescript
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { SongState, PipelineStage, SongResult } from '@/types/singing'

export const useSingingStore = defineStore('singing', () => {
  const url = ref('')
  const status = ref<PipelineStage>('idle')
  const progress = ref(0)
  const message = ref('')
  const result = ref<SongResult | null>(null)
  const error = ref('')

  const isProcessing = computed(() =>
    ['downloading', 'separating', 'transcribing',
     'waiting_lyrics', 'converting', 'mixing'].includes(status.value)
  )

  const isPlaying = ref(false)
  const currentTime = ref(0)
  const currentLyricIndex = ref(-1)

  function setProgress(stage: PipelineStage, pct: number, msg: string) {
    status.value = stage
    progress.value = pct
    message.value = msg
  }

  function setResult(res: SongResult) {
    result.value = res
    status.value = 'done'
    progress.value = 100
    message.value = ''
  }

  function setError(err: string) {
    error.value = err
    status.value = 'error'
  }

  function reset() {
    url.value = ''
    status.value = 'idle'
    progress.value = 0
    message.value = ''
    result.value = null
    error.value = ''
    isPlaying.value = false
    currentTime.value = 0
    currentLyricIndex.value = -1
  }

  return {
    url, status, progress, message, result, error,
    isProcessing, isPlaying, currentTime, currentLyricIndex,
    setProgress, setResult, setError, reset,
  }
})
```

**Step 3: Commit**

```bash
git add frontend/src/types/singing.ts frontend/src/stores/singing.ts
git commit -m "feat(singing): add frontend types and Pinia store"
```

---

### Task 11: Create useSinging composable

**Files:**
- Create: `frontend/src/composables/useSinging.ts`

**Step 1: Create composable**

```typescript
import { onMounted, onUnmounted } from 'vue'
import { getSocket } from './useSocket'
import { useSingingStore } from '@/stores/singing'
import type { PipelineStage, SongResult } from '@/types/singing'

export function useSinging() {
  const store = useSingingStore()

  function process(url: string) {
    store.url = url
    store.setProgress('downloading', 0, 'Starting...')
    const socket = getSocket()
    if (socket?.connected) {
      socket.emit('sing:process', { url })
    }
  }

  function confirmLyrics(assContent: string) {
    const socket = getSocket()
    if (socket?.connected) {
      socket.emit('sing:confirm_lyrics', { ass_content: assContent })
    }
  }

  function cancel() {
    const socket = getSocket()
    if (socket?.connected) {
      socket.emit('sing:cancel', {})
    }
  }

  // Callbacks set up in onMounted/onUnmounted
  let _onProgress: ((data: any) => void) | null = null
  let _onComplete: ((data: any) => void) | null = null
  let _onError: ((data: any) => void) | null = null
  let _onLyricsReady: ((data: any) => void) | null = null

  onMounted(() => {
    const socket = getSocket()
    if (!socket) return

    _onProgress = (data: any) => {
      store.setProgress(data.stage, data.progress, data.message || '')
    }

    _onComplete = (data: any) => {
      store.setResult({
        audio_url: data.audio_url,
        duration: data.duration,
        lyrics: data.lyrics || [],
      })
    }

    _onError = (data: any) => {
      store.setError(data.error)
    }

    _onLyricsReady = (data: any) => {
      store.setProgress('waiting_lyrics', 0, data.message || 'Lyrics ready for review')
    }

    socket.on('sing:progress', _onProgress)
    socket.on('sing:complete', _onComplete)
    socket.on('sing:error', _onError)
    socket.on('sing:lyrics_ready', _onLyricsReady)
  })

  onUnmounted(() => {
    const socket = getSocket()
    if (!socket) return
    if (_onProgress) socket.off('sing:progress', _onProgress)
    if (_onComplete) socket.off('sing:complete', _onComplete)
    if (_onError) socket.off('sing:error', _onError)
    if (_onLyricsReady) socket.off('sing:lyrics_ready', _onLyricsReady)
  })

  return { process, confirmLyrics, cancel }
}
```

**Step 2: Commit**

```bash
git add frontend/src/composables/useSinging.ts
git commit -m "feat(singing): add useSinging composable"
```

---

### Task 12: Create music card components

**Files:**
- Create: `frontend/src/components/singing/WaveformDisplay.vue`
- Create: `frontend/src/components/singing/PlaybackControls.vue`
- Create: `frontend/src/components/singing/ProcessTimeline.vue`
- Create: `frontend/src/components/singing/MusicCard.vue`

**Step 1: WaveformDisplay**

`frontend/src/components/singing/WaveformDisplay.vue`:
```vue
<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted } from 'vue'

const props = defineProps<{
  isPlaying: boolean
}>()

const canvasRef = ref<HTMLCanvasElement | null>(null)
let analyser: AnalyserNode | null = null
let source: MediaElementAudioSourceNode | null = null
let audioCtx: AudioContext | null = null
let rafId: number | null = null

function startDrawing() {
  if (!canvasRef.value) return
  const canvas = canvasRef.value
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const draw = () => {
    if (!analyser || !ctx) return
    const bufferLength = analyser.frequencyBinCount
    const dataArray = new Uint8Array(bufferLength)
    analyser.getByteTimeDomainData(dataArray)

    ctx.fillStyle = 'rgba(26, 16, 40, 0.2)'
    ctx.fillRect(0, 0, canvas.width, canvas.height)

    ctx.lineWidth = 2
    ctx.strokeStyle = '#e879a8'
    ctx.beginPath()

    const sliceWidth = canvas.width / bufferLength
    let x = 0
    for (let i = 0; i < bufferLength; i++) {
      const v = dataArray[i] / 128.0
      const y = v * canvas.height / 2
      if (i === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
      x += sliceWidth
    }
    ctx.lineTo(canvas.width, canvas.height / 2)
    ctx.stroke()

    rafId = requestAnimationFrame(draw)
  }
  draw()
}

function stopDrawing() {
  if (rafId) {
    cancelAnimationFrame(rafId)
    rafId = null
  }
}

function connectAudio(audioEl: HTMLAudioElement) {
  if (!audioCtx) {
    audioCtx = new AudioContext()
  }
  source = audioCtx.createMediaElementSource(audioEl)
  analyser = audioCtx.createAnalyser()
  analyser.fftSize = 256
  source.connect(analyser)
  analyser.connect(audioCtx.destination)
}

watch(() => props.isPlaying, (playing) => {
  if (playing) startDrawing()
  else stopDrawing()
})

onUnmounted(() => {
  stopDrawing()
  source?.disconnect()
  audioCtx?.close()
})
</script>

<template>
  <canvas
    ref="canvasRef"
    class="w-full h-16 rounded-lg"
    width="340"
    height="64"
  />
</template>
```

**Step 2: PlaybackControls**

`frontend/src/components/singing/PlaybackControls.vue`:
```vue
<script setup lang="ts">
import { ref, computed } from 'vue'

const props = defineProps<{
  duration: number
  audioUrl: string
}>()

const emit = defineEmits<{
  play: []
  pause: []
  timeupdate: [time: number]
}>()

const audioRef = ref<HTMLAudioElement | null>(null)
const isPlaying = ref(false)
const currentTime = ref(0)

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function togglePlay() {
  const audio = audioRef.value
  if (!audio) return
  if (isPlaying.value) {
    audio.pause()
    isPlaying.value = false
    emit('pause')
  } else {
    audio.play()
    isPlaying.value = true
    emit('play')
  }
}

function onTimeUpdate() {
  if (audioRef.value) {
    currentTime.value = audioRef.value.currentTime
    emit('timeupdate', currentTime.value)
  }
}

function onEnded() {
  isPlaying.value = false
  currentTime.value = 0
}

function seek(e: MouseEvent) {
  const audio = audioRef.value
  if (!audio) return
  const bar = e.currentTarget as HTMLElement
  const rect = bar.getBoundingClientRect()
  const ratio = (e.clientX - rect.left) / rect.width
  audio.currentTime = ratio * props.duration
}

const progressPercent = computed(() =>
  props.duration > 0 ? (currentTime.value / props.duration) * 100 : 0
)
</script>

<template>
  <div class="flex flex-col gap-2">
    <audio ref="audioRef" :src="audioUrl" @timeupdate="onTimeUpdate" @ended="onEnded" />

    <!-- Progress bar -->
    <div
      class="relative h-2 bg-c-bg/40 rounded-full cursor-pointer overflow-hidden"
      @click="seek"
    >
      <div
        class="absolute inset-y-0 left-0 bg-c-accent rounded-full transition-all"
        :style="{ width: `${progressPercent}%` }"
      />
    </div>

    <!-- Controls -->
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-3">
        <button
          class="w-10 h-10 flex items-center justify-center rounded-full
                 bg-c-accent/20 text-c-accent hover:bg-c-accent/30 transition-all"
          @click="togglePlay"
        >
          <svg v-if="isPlaying" width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
            <rect x="6" y="4" width="4" height="16" />
            <rect x="14" y="4" width="4" height="16" />
          </svg>
          <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
            <polygon points="5,3 19,12 5,21" />
          </svg>
        </button>

        <span class="text-xs text-c-text-dim font-mono">
          {{ formatTime(currentTime) }} / {{ formatTime(duration) }}
        </span>
      </div>
    </div>
  </div>
</template>
```

**Step 3: ProcessTimeline**

`frontend/src/components/singing/ProcessTimeline.vue`:
```vue
<script setup lang="ts">
import type { PipelineStage } from '@/types/singing'

const props = defineProps<{
  currentStage: PipelineStage
  progress: number
}>()

interface TimelineStep {
  stage: PipelineStage
  label: string
  icon: string
}

const steps: TimelineStep[] = [
  { stage: 'downloading', label: '下载音频', icon: '⬇️' },
  { stage: 'separating', label: '人声分离', icon: '🔊' },
  { stage: 'transcribing', label: '歌词识别', icon: '📝' },
  { stage: 'waiting_lyrics', label: '歌词待确认', icon: '⏸' },
  { stage: 'converting', label: '歌声转换', icon: '🎤' },
  { stage: 'mixing', label: '混合输出', icon: '🎛️' },
]

const stageOrder: PipelineStage[] = [
  'downloading', 'separating', 'transcribing',
  'waiting_lyrics', 'converting', 'mixing',
]

function stepStatus(step: TimelineStep): 'done' | 'active' | 'pending' {
  const currentIdx = stageOrder.indexOf(props.currentStage)
  const stepIdx = stageOrder.indexOf(step.stage)
  if (stepIdx < currentIdx) return 'done'
  if (step.stage === props.currentStage) return 'active'
  return 'pending'
}
</script>

<template>
  <div class="flex flex-col gap-2 py-2">
    <div
      v-for="step in steps"
      :key="step.stage"
      class="flex items-center gap-3 px-2 py-1.5 rounded-lg text-xs transition-all"
      :class="{
        'opacity-40': stepStatus(step) === 'pending',
        'bg-c-accent/10': stepStatus(step) === 'active',
      }"
    >
      <span class="w-5 text-center">
        <span v-if="stepStatus(step) === 'done'">✅</span>
        <span v-else-if="stepStatus(step) === 'active' && progress > 0">⏳</span>
        <span v-else>{{ step.icon }}</span>
      </span>

      <span class="flex-1" :class="{
        'text-c-accent font-medium': stepStatus(step) === 'active',
        'text-c-text': stepStatus(step) === 'done',
        'text-c-text-dim': stepStatus(step) === 'pending',
      }">{{ step.label }}</span>

      <span v-if="stepStatus(step) === 'active' && progress > 0" class="text-c-text-dim">
        {{ Math.round(progress) }}%
      </span>
    </div>
  </div>
</template>
```

**Step 4: MusicCard (main card)**

`frontend/src/components/singing/MusicCard.vue`:
```vue
<script setup lang="ts">
import { ref } from 'vue'
import { useSingingStore } from '@/stores/singing'
import { useSinging } from '@/composables/useSinging'
import WaveformDisplay from './WaveformDisplay.vue'
import PlaybackControls from './PlaybackControls.vue'
import ProcessTimeline from './ProcessTimeline.vue'

const store = useSingingStore()
const { process, cancel } = useSinging()
const inputUrl = ref('')

function startProcess() {
  if (!inputUrl.value.trim()) return
  process(inputUrl.value.trim())
}

function handleTimeupdate(time: number) {
  store.currentTime = time
  // Update current lyric index based on time
  if (store.result?.lyrics) {
    const idx = store.result.lyrics.findIndex(
      l => time * 1000 >= l.start_ms && time * 1000 <= l.end_ms
    )
    store.currentLyricIndex = idx
  }
}
</script>

<template>
  <div class="flex flex-col h-full p-4 gap-4 overflow-y-auto">
    <div class="text-sm font-medium text-c-text">🎵 音乐制作</div>

    <!-- URL Input (shown when idle/error) -->
    <div v-if="store.status === 'idle' || store.status === 'error'" class="flex gap-2">
      <input
        v-model="inputUrl"
        placeholder="📎 贴上 B站 视频链接..."
        class="flex-1 px-3 py-2 rounded-lg bg-c-bg/40 border border-c-border/30
               text-sm text-c-text placeholder-c-text-dim/50 outline-none
               focus:border-c-accent/50 transition-all"
        @keyup.enter="startProcess"
      />
      <button
        class="px-4 py-2 rounded-lg bg-c-accent/20 text-c-accent text-sm
               font-medium hover:bg-c-accent/30 transition-all whitespace-nowrap"
        @click="startProcess"
      >
        开始制作
      </button>
    </div>

    <!-- Processing timeline -->
    <ProcessTimeline
      v-if="store.isProcessing || store.status === 'waiting_lyrics'"
      :current-stage="store.status"
      :progress="store.progress"
    />

    <!-- Lyrics confirmation hint -->
    <div
      v-if="store.status === 'waiting_lyrics'"
      class="px-3 py-2 rounded-lg bg-c-gold/10 border border-c-gold/30 text-xs text-c-gold"
    >
      歌词已生成，请在 <strong>Aegisub</strong> 中审核时间轴后确认。
    </div>

    <!-- Cancel button during processing -->
    <button
      v-if="store.isProcessing"
      class="self-start px-3 py-1.5 rounded-lg bg-c-error/10 text-c-error
             text-xs hover:bg-c-error/20 transition-all"
      @click="cancel"
    >
      取消
    </button>

    <!-- Result: playback -->
    <div v-if="store.result" class="flex flex-col gap-3">
      <PlaybackControls
        :duration="store.result.duration"
        :audio-url="store.result.audio_url"
        @timeupdate="handleTimeupdate"
      />
      <WaveformDisplay :is-playing="store.isPlaying" />
    </div>

    <!-- Error -->
    <div
      v-if="store.error"
      class="px-3 py-2 rounded-lg bg-c-error/10 border border-c-error/30 text-xs text-c-error"
    >
      {{ store.error }}
    </div>
  </div>
</template>
```

**Step 5: Commit**

```bash
git add frontend/src/components/singing/
git commit -m "feat(singing): add music card UI components"
```

---

### Task 13: Add "音乐" tab to InteractivePanel

**Files:**
- Modify: `frontend/src/components/layout/InteractivePanel.vue`

**Step 1: Add tab button and panel**

In `InteractivePanel.vue`:

Update `activeTab` type to include `'singing'`:
```typescript
const activeTab = ref<'chat' | 'live' | 'memory' | 'personality' | 'singing' | 'settings'>('chat')
```

Add tab button between "人格" and "设置":
```vue
<button
  class="px-3 py-1.5 rounded-lg text-xs font-medium transition-all"
  :class="activeTab === 'singing'
    ? 'bg-c-accent/20 text-c-accent'
    : 'bg-c-bg/40 text-c-text-dim hover:text-c-text hover:bg-c-panel/50'"
  @click="activeTab = 'singing'"
>
  🎵 音乐
</button>
```

Add import and panel content:
```vue
<script setup lang="ts">
import MusicCard from '@/components/singing/MusicCard.vue'
</script>

<!-- In template tab content section: -->
<MusicCard v-else-if="activeTab === 'singing'" key="singing" />
```

**Step 2: Commit**

```bash
git add frontend/src/components/layout/InteractivePanel.vue
git commit -m "feat(singing): add music tab to InteractivePanel"
```

---

## Execution Handoff

**Plan complete and saved to `docs/plans/archive/2026-05/2026-05-17-singing-module-plan.md`.**

Two execution options:

1. **Subagent-Driven (this session)** — I dispatch fresh subagent per task, review between tasks, fast iteration

2. **Parallel Session (separate)** — Open new session with executing-plans, batch execution with checkpoints

Which approach?
