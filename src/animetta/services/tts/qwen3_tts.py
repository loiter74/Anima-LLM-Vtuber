from __future__ import annotations

"""
Qwen3-TTS implementation - 通义千问 open-source TTS (CustomVoice model)

Local inference mode: loads the configured model via the qwen-tts package.
Runs synchronous model, prompt, generation, and audio work on one serial worker.
Tracks the underlying worker Futures for cancellation-safe shutdown.

CustomVoice features: 9 preset voices, instruction-based emotion/style control,
10 languages, optional FlashAttention 2 acceleration.

For RTX 5090D: bfloat16 + FlashAttention 2 at ~4GB VRAM.
"""

# Status: active
# Last verified: 2026-05-23

import asyncio
import gc
import importlib
import os
import re
import sys
import threading
import wave
from collections.abc import AsyncGenerator, Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

from loguru import logger

from animetta.config.core.registry import ProviderRegistry

from .interface import TTSInterface

_HF_PATCH_LOCK = threading.Lock()


def _resolve_cached_model_source(model: str) -> str:
    """Resolve a Hub model id to its active local snapshot when available."""
    if "/" not in model:
        return model
    hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    model_root = hf_home / "hub" / f"models--{model.replace('/', '--')}"
    refs_main = model_root / "refs" / "main"
    snapshots_root = model_root / "snapshots"
    try:
        revision = refs_main.read_text(encoding="utf-8").strip()
        if not revision or not re.fullmatch(r"[A-Za-z0-9._-]+", revision):
            return model
        snapshots_root = snapshots_root.resolve()
        snapshot = (snapshots_root / revision).resolve()
        if snapshot.is_relative_to(snapshots_root) and (snapshot / "config.json").is_file():
            return str(snapshot)
    except (OSError, UnicodeError, ValueError):
        return model
    return model


class _LocalOnlyAutoProcessorFacade:
    """Delegate Qwen processor APIs while forcing its nested load offline."""

    def __init__(self, auto_processor: Any) -> None:
        self._auto_processor = auto_processor

    def from_pretrained(self, *args: Any, **kwargs: Any) -> Any:
        kwargs["fix_mistral_regex"] = False
        kwargs["local_files_only"] = True
        return self._auto_processor.from_pretrained(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._auto_processor, name)


@contextmanager
def _temporary_qwen_loader_patches(qwen_model_class: type[Any]) -> Iterator[None]:
    """Make only Qwen's module-local processor binding load offline.

    Qwen's loader reads ``AutoProcessor`` from the module that defines the
    model class. Rebinding that one name avoids changing Transformers classes
    observed by unrelated concurrent loaders. The exact module binding is
    restored on every exit.
    """
    with _HF_PATCH_LOCK:
        module_name = getattr(qwen_model_class, "__module__", None)
        if not isinstance(module_name, str) or not module_name:
            raise TypeError("Qwen model class must define a module name")
        qwen_module = sys.modules.get(module_name)
        if qwen_module is None:
            qwen_module = importlib.import_module(module_name)
        try:
            original_auto_processor = vars(qwen_module)["AutoProcessor"]
        except KeyError as exc:
            raise AttributeError(
                "Qwen model module does not define AutoProcessor"
            ) from exc

        facade = _LocalOnlyAutoProcessorFacade(original_auto_processor)
        restore_binding = False
        try:
            # Set first so a fault-injecting module that mutates then raises is
            # still repaired by the finally block.
            restore_binding = True
            setattr(qwen_module, "AutoProcessor", facade)
            yield
        finally:
            if restore_binding:
                setattr(qwen_module, "AutoProcessor", original_auto_processor)


@ProviderRegistry.register_service("tts", "qwen3")
class Qwen3TTSTTS(TTSInterface):
    """
    Qwen3-TTS implementation (local inference mode)

    Thread-safety guarantees:
    - one provider-owned worker serializes model load, prompt build, and generation
    - cancellation preserves running work and cancels work that is still queued
    - close() is queued behind submitted work and never force-unloads a busy model
    """

    def __init__(
        self,
        model: str = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
        speaker: str = "Vivian",
        device: str = "cuda:0",
        dtype: str = "bfloat16",
        default_instruct: str = "",
        language: str = "Chinese",
        max_new_tokens: int = 4096,
        top_p: float = 0.9,
        temperature: float = 0.9,
        repetition_penalty: float = 1.05,
        use_flash_attn: bool = True,
        ref_audio_path: str | None = None,
        ref_text: str | None = None,
        x_vector_only: bool = True,
    ) -> None:
        self.model = model
        self.speaker = speaker
        self.device = device
        self.dtype = dtype
        self.default_instruct = default_instruct
        self.language = language
        self.max_new_tokens = max_new_tokens
        self.top_p = top_p
        self.temperature = temperature
        self.repetition_penalty = repetition_penalty
        self.use_flash_attn = use_flash_attn
        self.ref_audio_path = ref_audio_path
        self.ref_text = ref_text
        self.x_vector_only = x_vector_only
        # Voice clone prompt cache (lazy, invalidated on close/model reload)
        self._voice_clone_prompt: list[Any] | None = None

        self._model = None
        self._loaded = False
        # Kept for compatibility with direct/internal model-load callers. Normal
        # lifecycle work is additionally serialized by the provider executor.
        self._load_lock = threading.Lock()
        # RLock also covers the rare case where a very short Future completes
        # before add_done_callback() returns on the submitting thread.
        self._lifecycle_lock = threading.RLock()
        self._state_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="animetta-qwen3-tts",
        )
        self._accepting_work = True
        self._close_future: Future[None] | None = None
        self._synthesis_futures: set[Future[Any]] = set()
        # threading.Event reflects the actual concurrent.futures jobs, not the
        # lifetime of possibly-cancelled asyncio wrappers.
        self._synth_done = threading.Event()
        self._synth_done.set()
        self._preload_state = "pending"
        self._preload_error: str | None = None

    @property
    def preload_status(self) -> dict[str, str | bool | None]:
        """Return content-free preload metadata for runtime readiness checks."""
        with self._state_lock:
            return {
                "state": self._preload_state,
                "ready": self._preload_state == "ready",
                "error": self._preload_error,
            }

    def _set_preload_state(self, state: str, error: Exception | None = None) -> None:
        with self._state_lock:
            # Shutdown is monotonic: work accepted before close() may finish,
            # but it must never make a closing/closed provider ready again.
            if self._preload_state == "closed":
                return
            if self._preload_state == "closing" and state != "closed":
                return
            self._preload_state = state
            self._preload_error = type(error).__name__ if error is not None else None

    def _validate_voice_clone_reference(self) -> None:
        """Validate Alice voice-clone inputs before allocating the model."""
        if not self.ref_audio_path:
            return

        reference = Path(self.ref_audio_path)
        if not reference.is_file():
            raise FileNotFoundError(f"Reference audio not found: {reference}")
        if reference.stat().st_size == 0:
            raise ValueError("Reference audio must be a non-empty valid WAV file")
        if not self.x_vector_only and not (self.ref_text or "").strip():
            raise ValueError("ref_text must be non-empty when x_vector_only is false")

        try:
            with wave.open(str(reference), "rb") as wav_file:
                if (
                    wav_file.getnchannels() <= 0
                    or wav_file.getsampwidth() <= 0
                    or wav_file.getframerate() <= 0
                    or wav_file.getnframes() <= 0
                ):
                    raise ValueError("Reference audio must contain valid WAV frames")
        except (EOFError, wave.Error) as exc:
            raise ValueError("Reference audio must be a non-empty valid WAV file") from exc

    def _submit_worker(
        self,
        function: Callable[[], Any],
        *,
        synthesis: bool = False,
    ) -> Future[Any]:
        """Submit work while atomically excluding a concurrent close()."""
        with self._lifecycle_lock:
            if not self._accepting_work:
                raise RuntimeError("Qwen3-TTS provider is closing or closed")
            future = self._executor.submit(function)
            if synthesis:
                self._synthesis_futures.add(future)
                self._synth_done.clear()
                future.add_done_callback(self._on_synthesis_done)
            return future

    def _on_synthesis_done(self, future: Future[Any]) -> None:
        with self._lifecycle_lock:
            self._synthesis_futures.discard(future)
            if not self._synthesis_futures:
                self._synth_done.set()

    @staticmethod
    def _drain_asyncio_future(future: asyncio.Future[Any]) -> None:
        """Retrieve late exceptions from detached shielded waiters."""
        if future.cancelled():
            return
        with suppress(asyncio.CancelledError):
            future.exception()

    async def _await_worker_future(
        self,
        future: Future[Any],
        *,
        cancel_if_queued: bool = False,
    ) -> Any:
        """Bridge a worker Future into asyncio with explicit cancellation rules."""
        wrapped = asyncio.wrap_future(future)
        wrapped.add_done_callback(self._drain_asyncio_future)
        try:
            if cancel_if_queued:
                return await wrapped
            return await asyncio.shield(wrapped)
        except asyncio.CancelledError:
            if cancel_if_queued:
                future.cancel()
            raise

    def _ensure_preloaded_worker(self) -> None:
        """Load the model and cache the clone prompt inside the serial worker."""
        if (
            self._loaded
            and self._model is not None
            and (not self.ref_audio_path or self._voice_clone_prompt is not None)
        ):
            self._set_preload_state("ready")
            return

        self._set_preload_state("loading")
        try:
            self._validate_voice_clone_reference()
            self._load_model()
            if self.ref_audio_path:
                self._build_voice_clone_prompt()
        except Exception as exc:
            self._set_preload_state("failed", exc)
            raise
        self._set_preload_state("ready")

    @staticmethod
    def _enable_cuda_optimizations(torch_module: Any) -> None:
        """Enable inference-safe CUDA backend flags."""
        torch_module.backends.cudnn.benchmark = True
        torch_module.backends.cuda.matmul.allow_tf32 = True
        if hasattr(torch_module.backends.cuda, "enable_flash_sdp"):
            torch_module.backends.cuda.enable_flash_sdp(True)
        if hasattr(torch_module.backends.cuda, "enable_mem_efficient_sdp"):
            torch_module.backends.cuda.enable_mem_efficient_sdp(True)

    @staticmethod
    def _is_flash_attention_error(error: Exception) -> bool:
        message = str(error).lower()
        return any(
            marker in message
            for marker in ("flash_attn", "flashattention", "attn_implementation")
        )

    def _get_torch_dtype(self) -> Any:
        """Convert dtype string to torch dtype, with Windows bf16 fallback"""
        import torch
        if self.dtype == "bfloat16":
            if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
                logger.warning("bfloat16 not supported on this GPU, falling back to float16")
                return torch.float16
            return torch.bfloat16
        elif self.dtype == "float16":
            return torch.float16
        return torch.float16

    def _load_model(self) -> None:
        """Lazy-load the Qwen3-TTS model on first use. Thread-safe via _load_lock.

        Called under lock — no concurrent loads possible.
        This is a BLOCKING call (~30-60s for model download+load).
        Always call from the provider worker, never from the event loop directly.
        """
        with self._load_lock:
            if self._loaded and self._model is not None:
                return

            logger.info("Qwen3-TTS model load started")
            try:
                import torch
                from qwen_tts import Qwen3TTSModel
            except ImportError as e:
                raise ImportError(
                    "qwen-tts not installed. Run: pip install -U qwen-tts"
                ) from e

            # Check CUDA availability
            if self.device.startswith("cuda") and not torch.cuda.is_available():
                logger.warning("CUDA requested but not available, falling back to CPU")
                self.device = "cpu"

            # GPU optimizations for inference speed
            if self.device.startswith("cuda"):
                self._enable_cuda_optimizations(torch)
                logger.debug("CUDA optimizations: cudnn.benchmark=ON, tf32=ON, flash_sdp=ON")

            # Check available VRAM
            if self.device.startswith("cuda"):
                free_vram = torch.cuda.get_device_properties(self.device).total_memory / (1024**3)
                if free_vram < 6.0:
                    logger.warning(
                        f"GPU has {free_vram:.1f}GB VRAM. 1.7B model needs ~4GB. "
                        "Consider using float16 dtype if bfloat16, or reducing max_new_tokens."
                    )

            base_kwargs = {
                "device_map": self.device,
                "dtype": self._get_torch_dtype(),
            }
            kwargs = {**base_kwargs, "local_files_only": True}
            if self.use_flash_attn:
                kwargs["attn_implementation"] = "flash_attention_2"
                logger.debug("Qwen3-TTS FlashAttention requested")

            try:
                model_source = _resolve_cached_model_source(self.model)
                if "Darwin-TTS" in self.model and model_source == self.model:
                    logger.info("Qwen3-TTS Darwin compatibility download started")
                    # Darwin intentionally keeps its legacy online first load,
                    # but must not cross another provider's temporary patch window.
                    with _HF_PATCH_LOCK:
                        self._model = Qwen3TTSModel.from_pretrained(
                            self.model,
                            **base_kwargs,
                        )
                else:
                    with _temporary_qwen_loader_patches(Qwen3TTSModel):
                        try:
                            self._model = Qwen3TTSModel.from_pretrained(
                                model_source,
                                **kwargs,
                            )
                        except Exception as exc:
                            if (
                                "attn_implementation" not in kwargs
                                or isinstance(exc, (torch.cuda.OutOfMemoryError, OSError))
                                or not self._is_flash_attention_error(exc)
                            ):
                                raise
                            logger.warning(
                                "Qwen3-TTS FlashAttention fallback: error_type={}",
                                type(exc).__name__,
                            )
                            kwargs.pop("attn_implementation")
                            self.use_flash_attn = False
                            self._model = Qwen3TTSModel.from_pretrained(
                                model_source,
                                **kwargs,
                            )
                self._loaded = True
                logger.info("Qwen3-TTS model loaded successfully")
            except torch.cuda.OutOfMemoryError:
                logger.error(
                    "CUDA OOM loading Qwen3-TTS model. "
                    "Try: device=cpu, or dtype=float16, or a smaller max_new_tokens."
                )
                raise RuntimeError(
                    "GPU out of memory loading Qwen3-TTS model. "
                    "Try device=cpu or reduce memory usage."
                )
            except OSError as e:
                if "disk" in str(e).lower() or "space" in str(e).lower():
                    raise RuntimeError(
                        "Not enough disk space to download Qwen3-TTS model (~3.5GB). "
                        "Free up disk space or set HF_HOME to a different location."
                    ) from e
                raise

    def _build_voice_clone_prompt(self) -> list[Any]:
        """Build and cache voice clone prompt from reference audio.

        Thread-safe: called from the provider's serial worker after model load.
        Returns cached prompt on subsequent calls.
        """
        if self._voice_clone_prompt is not None:
            return self._voice_clone_prompt

        if not self.ref_audio_path:
            raise ValueError("ref_audio_path must be set for voice clone mode")

        if not os.path.exists(self.ref_audio_path):
            raise FileNotFoundError(f"Reference audio not found: {self.ref_audio_path}")

        logger.info("Qwen3-TTS voice clone prompt build started")
        self._voice_clone_prompt = self._model.create_voice_clone_prompt(
            ref_audio=self.ref_audio_path,
            ref_text=self.ref_text,
            x_vector_only_mode=self.x_vector_only,
        )
        logger.debug(
            "Qwen3-TTS voice clone prompt cached: item_count={}",
            len(self._voice_clone_prompt),
        )
        return self._voice_clone_prompt

    @classmethod
    def from_config(cls, config: Qwen3TTSConfig, **kwargs) -> Qwen3TTSTTS:
        """Create instance from config object"""
        return cls(
            model=config.model,
            speaker=config.speaker,
            device=config.device,
            dtype=config.dtype,
            default_instruct=getattr(config, "default_instruct", ""),
            language=config.language,
            max_new_tokens=config.max_new_tokens,
            top_p=config.top_p,
            temperature=config.temperature,
            repetition_penalty=config.repetition_penalty,
            use_flash_attn=config.use_flash_attn,
            ref_audio_path=getattr(config, "ref_audio_path", None),
            ref_text=getattr(config, "ref_text", None),
            x_vector_only=getattr(config, "x_vector_only", True),
        )

    async def synthesize(
        self,
        text: str,
        output_path: str | Path | None = None,
        speaker: str | None = None,
        instruct: str | None = None,
        **kwargs,
    ) -> bytes | str:
        """
        Synthesize text to speech using Qwen3-TTS CustomVoice model

        Args:
            text: Text to synthesize
            output_path: Output file path (optional). If None, returns audio bytes.
            speaker: Voice name override (defaults to config speaker)
            instruct: Instruction override for emotion/style (defaults to config default_instruct)
            **kwargs: Additional overrides (language, max_new_tokens, top_p, temperature, repetition_penalty)

        Returns:
            Union[bytes, str]: Audio bytes or file path string
        """
        if not text or not text.strip():
            logger.warning("Qwen3-TTS received empty text, skipping synthesis")
            return b"" if output_path is None else str(output_path)

        try:
            effective_speaker = speaker or self.speaker
            effective_language = kwargs.get("language", self.language)
            effective_instruct = instruct or self.default_instruct

            logger.debug("Qwen3-TTS synthesis started: text_length={}", len(text))

            def generate_and_encode() -> bytes | str:
                self._ensure_preloaded_worker()
                if self.ref_audio_path:
                    wavs, sr = self._model.generate_voice_clone(
                        text=text,
                        language=effective_language,
                        voice_clone_prompt=self._voice_clone_prompt,
                        max_new_tokens=kwargs.get("max_new_tokens", self.max_new_tokens),
                        top_p=kwargs.get("top_p", self.top_p),
                        temperature=kwargs.get("temperature", self.temperature),
                        repetition_penalty=kwargs.get("repetition_penalty", self.repetition_penalty),
                    )
                else:
                    wavs, sr = self._model.generate_custom_voice(
                        text=text,
                        language=effective_language,
                        speaker=effective_speaker,
                        instruct=effective_instruct,
                        max_new_tokens=kwargs.get("max_new_tokens", self.max_new_tokens),
                        top_p=kwargs.get("top_p", self.top_p),
                        temperature=kwargs.get("temperature", self.temperature),
                        repetition_penalty=kwargs.get(
                            "repetition_penalty",
                            self.repetition_penalty,
                        ),
                    )

                if not wavs or len(wavs) == 0:
                    raise RuntimeError("Qwen3-TTS generated empty audio")

                from io import BytesIO

                import soundfile as sf

                audio_data = wavs[0] if isinstance(wavs, list) else wavs
                buffer = BytesIO()
                sf.write(buffer, audio_data, sr, format="wav")
                audio_bytes = buffer.getvalue()

                logger.debug(
                    "Qwen3-TTS synthesis completed: byte_count={}, sample_rate={}",
                    len(audio_bytes),
                    sr,
                )

                if output_path:
                    resolved_output = Path(output_path)
                    resolved_output.parent.mkdir(parents=True, exist_ok=True)
                    sf.write(str(resolved_output), audio_data, sr)
                    logger.info("Qwen3-TTS audio output saved")
                    return str(resolved_output)
                return audio_bytes

            work_future = self._submit_worker(generate_and_encode, synthesis=True)
            return await self._await_worker_future(
                work_future,
                cancel_if_queued=True,
            )

        except Exception as exc:
            logger.error(
                "Qwen3-TTS synthesis failed: error_type={}",
                type(exc).__name__,
            )
            raise

    async def synthesize_stream(
        self,
        text: str,
        speaker: str | None = None,
        instruct: str | None = None,
        **kwargs,
    ) -> AsyncGenerator[bytes]:
        """Streaming speech synthesis — NOT YET IMPLEMENTED.

        Qwen3-TTS supports streaming via its Dual-Track architecture (97ms first-packet),
        but the qwen-tts Python package does not yet expose a streaming generate() API.
        When available, this will yield per-token audio chunks.

        For now, use synthesize() for full audio generation.
        """
        raise NotImplementedError(
            "Qwen3-TTS streaming synthesis is not yet available. "
            "The qwen-tts package does not expose a streaming generation API. "
            "Use synthesize() for full audio generation instead."
        )

    async def preload(self) -> None:
        """Preload model at startup (called by ModelLoadingManager).

        Model loading and Alice prompt construction both run on the same
        provider-owned worker used by synthesis.
        """
        if self.preload_status["ready"]:
            logger.debug("Qwen3-TTS model and voice prompt already preloaded")
            return

        logger.info("Qwen3-TTS preload started")
        work_future = self._submit_worker(self._ensure_preloaded_worker)
        # Shield startup work so cancelling its asyncio waiter cannot leave a
        # half-loaded shared model or a permanently ambiguous readiness state.
        await self._await_worker_future(work_future)
        logger.info("Qwen3-TTS model preloaded successfully")

    def _close_worker(self) -> None:
        """Unload after all earlier jobs in the serial executor have finished."""
        logger.info("Unloading Qwen3-TTS model...")
        try:
            self._model = None
            self._loaded = False
            self._voice_clone_prompt = None
            gc.collect()
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    logger.debug("GPU cache cleared after Qwen3-TTS unload")
            except ImportError:
                pass
        finally:
            self._set_preload_state("closed")
        logger.info("Qwen3-TTS model unloaded")

    async def close(self) -> None:
        """Stop accepting work and queue safe, idempotent model cleanup.

        The cleanup Future remains alive if this asyncio caller is cancelled.
        Executor shutdown is non-blocking and preserves all already-submitted
        jobs, so a busy model is never force-unloaded.
        """
        with self._lifecycle_lock:
            if self._close_future is None:
                # Lock order is always lifecycle -> state. Setting the state
                # first is safe because submitters cannot pass lifecycle_lock
                # until accepting_work has been disabled below.
                self._set_preload_state("closing")
                self._accepting_work = False
                self._close_future = self._executor.submit(self._close_worker)
                self._executor.shutdown(wait=False, cancel_futures=False)
            close_future = self._close_future

        await self._await_worker_future(close_future)
