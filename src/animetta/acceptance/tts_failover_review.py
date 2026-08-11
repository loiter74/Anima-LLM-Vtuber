"""Safe, fixed-text acceptance harness for the OBS TTS failover review."""

from __future__ import annotations

import asyncio
import io
import json
import secrets
import time
import wave
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from animetta.avatar.analyzers.audio import AudioAnalyzer
from animetta.host_tts_contract import HOST_TTS_CONTRACT
from animetta.services.tts.dashscope_tts import DashScopeRealtimeTTS
from animetta.services.tts.emotion_instructions import build_emotion_instruction
from animetta.services.tts.failover_tts import FailoverTTS, FailoverTTSUnavailableError
from animetta.services.tts.remote_tts import RemoteTTS

FIXED_REVIEW_TEXT = "晚上好，欢迎来到直播间。云端语音暂时不可用，现在由本小姐继续为你播报。"
REVIEW_SCENE_ID = "billing-to-local"
SAMPLE_RATE = HOST_TTS_CONTRACT.sample_rate
CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2
FALLBACK_IDENTITY = HOST_TTS_CONTRACT.identity()


@dataclass(frozen=True, slots=True)
class ReviewSpeech:
    text: str
    emotion: str
    enforce_performance: bool = True


REVIEW_SPEECHES = {
    REVIEW_SCENE_ID: ReviewSpeech(FIXED_REVIEW_TEXT, "neutral"),
    "live2d-calm": ReviewSpeech(
        "晚上好，今天也一起轻松聊聊天吧。",
        "neutral",
    ),
    "live2d-annoyed": ReviewSpeech(
        "哼，这种事情居然还要本小姐提醒你吗？",
        "angry",
    ),
    "live2d-surprised": ReviewSpeech(
        "诶？这是真的吗？完全没想到会变成这样！",
        "surprised",
    ),
    "minecraft-survival-iron": ReviewSpeech(
        "铁装流程开始，本小姐要认真起来了。先观察周围，再一步一步把装备做齐。",
        "neutral",
        enforce_performance=False,
    ),
}


class TTSFailoverReviewError(RuntimeError):
    """Base class for bounded, sanitized review failures."""

    category = "review_error"


class ReviewAuthorizationError(TTSFailoverReviewError):
    category = "authentication"


class ReviewSceneError(TTSFailoverReviewError):
    category = "invalid_scene"


class ReviewAudioError(TTSFailoverReviewError):
    category = "invalid_audio"


class ReviewBusyError(TTSFailoverReviewError):
    category = "busy"


class ReviewTimeoutError(TTSFailoverReviewError):
    category = "timeout"


class ReviewPerformanceError(TTSFailoverReviewError):
    category = "performance"

    def __init__(self, reason: str) -> None:
        super().__init__("Review synthesis exceeded its performance budget")
        self.reason = reason


class ReviewIdentityError(TTSFailoverReviewError):
    category = "identity_mismatch"


@dataclass(frozen=True, slots=True)
class ReviewResult:
    """One complete, safe review artifact pair."""

    report: dict[str, Any]
    wav_bytes: bytes
    report_name: str
    wav_name: str
    mouth_timeline: tuple[float, ...]


class TTSFailoverReviewHarness:
    """Run one authenticated fixed-text failover attempt at a time."""

    def __init__(
        self,
        *,
        engine: FailoverTTS,
        token: str,
        artifact_dir: Path,
        clock: Callable[[], float] | None = None,
        timeout_seconds: float = 20.0,
        max_first_audio_seconds: float = 0.75,
        max_rtf: float = 0.35,
        warmup: bool = False,
        cleanup_artifacts: bool = False,
    ) -> None:
        if not token:
            raise ValueError("Review harness token must not be empty")
        self.engine = engine
        self._token = token
        self.artifact_dir = artifact_dir
        self._clock = clock or time.perf_counter
        self.timeout_seconds = timeout_seconds
        self.max_first_audio_seconds = max_first_audio_seconds
        self.max_rtf = max_rtf
        self.warmup = warmup
        self.cleanup_artifacts = cleanup_artifacts
        self._attempt_lock = asyncio.Lock()
        self._closed = False
        self._prepared = False
        self._artifacts: set[str] = set()

    async def prepare(self) -> None:
        """Preload both routes; FailoverTTS accepts either route as ready."""

        await self.engine.preload()
        resolved_identity = getattr(self.engine.fallback, "resolved_identity", None)
        if (
            isinstance(resolved_identity, dict)
            and resolved_identity.get("sample_rate") != SAMPLE_RATE
        ):
            raise ReviewIdentityError("Review fallback sample-rate identity mismatch")
        if self.warmup:
            pcm = b"".join(
                [
                    chunk
                    async for chunk in self.engine.fallback.synthesize_stream(
                        FIXED_REVIEW_TEXT,
                    )
                ]
            )
            if not pcm or len(pcm) % SAMPLE_WIDTH_BYTES:
                raise ReviewAudioError("Review warmup returned invalid PCM audio")
        self._prepared = True

    async def run(self, *, scene_id: str, authorization: str) -> ReviewResult:
        """Synthesize the immutable scene and persist WAV plus sanitized JSON."""

        self._authorize(authorization)
        if not self._prepared:
            raise TTSFailoverReviewError("Review harness is not prepared")
        speech = REVIEW_SPEECHES.get(scene_id)
        if speech is None:
            raise ReviewSceneError("Unsupported review scene")
        if self._attempt_lock.locked():
            raise ReviewBusyError("Review attempt is already running")

        async with self._attempt_lock:
            try:
                async with asyncio.timeout(self.timeout_seconds):
                    return await self._run_attempt(scene_id, speech)
            except TimeoutError as exc:
                raise ReviewTimeoutError("Review synthesis timed out") from exc

    async def _run_attempt(self, scene_id: str, speech: ReviewSpeech) -> ReviewResult:
        started = self._clock()
        first_audio_seconds: float | None = None
        chunks: list[bytes] = []
        stream = self.engine.synthesize_stream(
            speech.text,
            instruction=build_emotion_instruction(speech.emotion),
            emotion=speech.emotion,
        )
        try:
            async for chunk in stream:
                if not chunk or len(chunk) % SAMPLE_WIDTH_BYTES:
                    raise ReviewAudioError("Review stream contains invalid PCM audio")
                if first_audio_seconds is None:
                    first_audio_seconds = max(0.0, self._clock() - started)
                chunks.append(chunk)
        except FailoverTTSUnavailableError as exc:
            raise ReviewAudioError("Review stream contains no PCM audio") from exc
        completed_at = self._clock()

        pcm = b"".join(chunks)
        if not pcm or first_audio_seconds is None:
            raise ReviewAudioError("Review stream contains no PCM audio")
        audio_seconds = len(pcm) / (SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH_BYTES)
        rtf = max(0.0, completed_at - started) / audio_seconds
        first_audio_passed = first_audio_seconds <= self.max_first_audio_seconds
        rtf_passed = rtf <= self.max_rtf
        if speech.enforce_performance and not first_audio_passed:
            raise ReviewPerformanceError("first_audio")
        if speech.enforce_performance and not rtf_passed:
            raise ReviewPerformanceError("rtf")

        wav_bytes = self._wav_bytes(pcm)
        readiness = self.engine.readiness_snapshot()
        artifact_id = uuid4().hex
        wav_name = f"tts-failover-{artifact_id}.wav"
        report_name = f"tts-failover-{artifact_id}.json"
        report = {
            "schema_version": 1,
            "feature": "tts-failover",
            "scene_id": scene_id,
            "actual_backend": self.engine.actual_backend,
            "actual_provider": self.engine.actual_provider,
            "primary_error_category": readiness["primary"]["error_category"],
            "fallback_error_category": readiness["fallback"]["error_category"],
            "readiness": readiness,
            "first_audio_seconds": first_audio_seconds,
            "rtf": rtf,
            "sample_rate": SAMPLE_RATE,
            "channels": CHANNELS,
            "sample_width_bytes": SAMPLE_WIDTH_BYTES,
            "pcm_bytes": len(pcm),
            "complete": True,
            "performance": {
                "first_audio_budget_seconds": self.max_first_audio_seconds,
                "rtf_budget": self.max_rtf,
                "passed": first_audio_passed and rtf_passed,
                "enforced": speech.enforce_performance,
            },
        }
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        wav_path = self.artifact_dir / wav_name
        wav_path.write_bytes(wav_bytes)
        (self.artifact_dir / report_name).write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        mouth_timeline = tuple(
            AudioAnalyzer().compute_volume_envelope(
                str(wav_path),
                normalize=False,
                gain=3.5,
                use_peak=True,
            )
        )
        if not mouth_timeline:
            raise ReviewAudioError("Review audio produced no mouth timeline")
        self._artifacts.update((wav_name, report_name))
        return ReviewResult(
            report=report,
            wav_bytes=wav_bytes,
            report_name=report_name,
            wav_name=wav_name,
            mouth_timeline=mouth_timeline,
        )

    def _authorize(self, authorization: str) -> None:
        expected = f"Bearer {self._token}"
        if not secrets.compare_digest(authorization, expected):
            raise ReviewAuthorizationError("Review harness authentication failed")

    @staticmethod
    def _wav_bytes(pcm: bytes) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(CHANNELS)
            wav_file.setsampwidth(SAMPLE_WIDTH_BYTES)
            wav_file.setframerate(SAMPLE_RATE)
            wav_file.writeframes(pcm)
        return buffer.getvalue()

    async def close(self) -> None:
        """Release engines once even when cleanup hooks are repeated."""

        if self._closed:
            return
        self._closed = True
        await self.engine.close()
        if self.cleanup_artifacts:
            for name in self._artifacts:
                (self.artifact_dir / name).unlink(missing_ok=True)
            with suppress(OSError):
                self.artifact_dir.rmdir()

    def artifact_path(self, name: str) -> Path | None:
        """Resolve only artifacts created by this process."""

        if name not in self._artifacts:
            return None
        return self.artifact_dir / name


def create_real_harness(
    *,
    port: int,
    token: str,
    fallback_token: str,
    artifact_dir: Path,
    fallback_url: str = "http://127.0.0.1:8767",
) -> TTSFailoverReviewHarness:
    """Compose production providers around a loopback-only billing stub."""

    primary = DashScopeRealtimeTTS(
        api_key="review-dashscope-protocol-token",
        base_url=f"ws://127.0.0.1:{port}/dashscope",
    )
    fallback = RemoteTTS(
        api_key=fallback_token,
        base_url=fallback_url,
        provider=str(FALLBACK_IDENTITY["provider"]),
        model=str(FALLBACK_IDENTITY["model"]),
        voice=str(FALLBACK_IDENTITY["voice"]),
        response_format="wav",
        language="Chinese",
        timeout_seconds=20.0,
        revision=str(FALLBACK_IDENTITY["revision"]),
        quantization=str(FALLBACK_IDENTITY["quantization"]),
        runtime_commit=str(FALLBACK_IDENTITY["runtime_commit"]),
    )
    return TTSFailoverReviewHarness(
        engine=FailoverTTS(primary=primary, fallback=fallback),
        token=token,
        artifact_dir=artifact_dir,
        warmup=True,
        cleanup_artifacts=True,
    )


def create_review_app(harness: TTSFailoverReviewHarness) -> Starlette:
    """Expose the bounded review contract on a loopback ASGI server."""

    prepare_lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app: Starlette):
        del app
        try:
            yield
        finally:
            await harness.close()

    async def health(request: Request) -> JSONResponse:
        del request
        return JSONResponse({"status": "ok", "service": "tts-failover-review"})

    async def prepare(request: Request) -> JSONResponse:
        try:
            harness._authorize(request.headers.get("authorization", ""))
            async with prepare_lock:
                if not harness._prepared:
                    await harness.prepare()
            return JSONResponse(
                {
                    "ready": True,
                    "readiness": harness.engine.readiness_snapshot(),
                    "identity": FALLBACK_IDENTITY,
                }
            )
        except ReviewAuthorizationError:
            return JSONResponse({"category": "authentication"}, status_code=401)
        except BaseException as exc:
            return _safe_error_response(exc)

    async def identity(request: Request) -> JSONResponse:
        try:
            harness._authorize(request.headers.get("authorization", ""))
        except ReviewAuthorizationError:
            return JSONResponse({"category": "authentication"}, status_code=401)
        return JSONResponse(FALLBACK_IDENTITY)

    async def synthesize(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
            scene_id = payload.get("scene_id") if isinstance(payload, dict) else None
            result = await harness.run(
                scene_id=str(scene_id or ""),
                authorization=request.headers.get("authorization", ""),
            )
            return JSONResponse(
                {
                    "report": result.report,
                    "audio_wav": f"/artifacts/{result.wav_name}",
                    "backend_report": f"/artifacts/{result.report_name}",
                    "mouth_timeline": result.mouth_timeline,
                }
            )
        except ReviewAuthorizationError:
            return JSONResponse({"category": "authentication"}, status_code=401)
        except BaseException as exc:
            return _safe_error_response(exc)

    async def artifact(request: Request):
        path = harness.artifact_path(str(request.path_params["name"]))
        if path is None or not path.is_file():
            return JSONResponse({"category": "not_found"}, status_code=404)
        media_type = "audio/wav" if path.suffix == ".wav" else "application/json"
        return FileResponse(path, media_type=media_type)

    async def dashscope_billing_stub(websocket: WebSocket) -> None:
        if websocket.client is not None and websocket.client.host not in {"127.0.0.1", "::1"}:
            await websocket.close(code=1008)
            return
        if websocket.headers.get("authorization") != "Bearer review-dashscope-protocol-token":
            await websocket.close(code=1008)
            return
        await websocket.accept()
        await websocket.send_json({"type": "session.created", "session": {"id": "review"}})
        try:
            await websocket.receive_json()
            await websocket.send_json(
                {
                    "type": "error",
                    "error": {
                        "code": "AccountNotInGoodStanding",
                        "message": "Account balance is not in good standing",
                    },
                }
            )
        except WebSocketDisconnect:
            return
        finally:
            await websocket.close()

    return Starlette(
        routes=[
            Route("/health", health),
            Route("/ready", prepare, methods=["POST"]),
            Route("/v1/identity", identity),
            Route("/v1/review/synthesize", synthesize, methods=["POST"]),
            Route("/artifacts/{name:str}", artifact),
            WebSocketRoute("/dashscope", dashscope_billing_stub),
        ],
        lifespan=lifespan,
    )


def _safe_error_response(exc: BaseException) -> JSONResponse:
    category = getattr(exc, "category", "review_error")
    reason = getattr(exc, "reason", None)
    safe_reason = reason if reason in {"first_audio", "rtf"} else None
    statuses = {
        "authentication": 401,
        "busy": 429,
        "invalid_scene": 400,
        "invalid_audio": 502,
        "timeout": 504,
        "performance": 422,
        "identity_mismatch": 503,
    }
    payload = {"ok": False, "category": str(category)}
    if safe_reason is not None:
        payload["reason"] = safe_reason
    return JSONResponse(payload, status_code=statuses.get(str(category), 503))
