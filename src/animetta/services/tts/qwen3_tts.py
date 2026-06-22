from __future__ import annotations

"""
Qwen3-TTS implementation - 通义千问 open-source TTS (CustomVoice model)

Local inference mode: loads 1.7B model via qwen-tts package.
Wraps synchronous HuggingFace generation in run_in_executor.
Thread-safe lazy loading with asyncio guard for clean shutdown.

CustomVoice features: 9 preset voices, instruction-based emotion/style control,
10 languages, optional FlashAttention 2 acceleration.

For RTX 5090D: bfloat16 + FlashAttention 2 at ~4GB VRAM.
"""

# Status: active
# Last verified: 2026-05-23

import asyncio
import gc
import os
import threading
from collections.abc import AsyncGenerator
from pathlib import Path

from loguru import logger

from animetta.core.config.core.registry import ProviderRegistry

from .interface import TTSInterface


@ProviderRegistry.register_service("tts", "qwen3")
class Qwen3TTSTTS(TTSInterface):
    """
    Qwen3-TTS implementation (local inference mode)

    Thread-safety guarantees:
    - _load_model() guarded by threading.Lock (prevents double-load OOM)
    - close() waits for in-flight synthesis via _synth_done event
    - preload() uses run_in_executor (does not block event loop)
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
    ):
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
        self._voice_clone_prompt: list | None = None

        self._model = None
        self._loaded = False
        # Oracle fix #2: threading lock for concurrent model load guard
        self._load_lock = threading.Lock()
        # Oracle fix #4: asyncio event for close() to wait for in-flight synthesis
        self._synth_done = asyncio.Event()
        self._synth_done.set()  # Initially not synthesizing

    def _get_torch_dtype(self):
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

    def _load_model(self):
        """Lazy-load the Qwen3-TTS model on first use. Thread-safe via _load_lock.

        Called under lock — no concurrent loads possible.
        This is a BLOCKING call (~30-60s for model download+load).
        Always call from run_in_executor, never from the event loop directly.
        """
        with self._load_lock:
            if self._loaded and self._model is not None:
                return

            logger.info(f"Loading Qwen3-TTS model: {self.model} (device={self.device}, dtype={self.dtype})")
            logger.info("First load downloads ~4GB model + tokenizer, may take 2-5 minutes depending on network...")
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
                torch.backends.cudnn.benchmark.main = True
                torch.backends.cuda.matmul.allow_tf32 = True
                if hasattr(torch.backends.cuda, 'enable_flash_sdp'):
                    torch.backends.cuda.enable_flash_sdp(True)
                if hasattr(torch.backends.cuda, 'enable_mem_efficient_sdp'):
                    torch.backends.cuda.enable_mem_efficient_sdp(True)
                logger.debug("CUDA optimizations: cudnn.benchmark.main=ON, tf32=ON, flash_sdp=ON")

            # Check available VRAM
            if self.device.startswith("cuda"):
                free_vram = torch.cuda.get_device_properties(self.device).total_memory / (1024**3)
                if free_vram < 6.0:
                    logger.warning(
                        f"GPU has {free_vram:.1f}GB VRAM. 1.7B model needs ~4GB. "
                        "Consider using float16 dtype if bfloat16, or reducing max_new_tokens."
                    )

            kwargs = {
                "device_map": self.device,
                "dtype": self._get_torch_dtype(),
            }
            if self.use_flash_attn:
                try:
                    kwargs["attn_implementation"] = "flash_attention_2"
                    logger.debug("FlashAttention 2 enabled")
                except Exception:
                    logger.warning("FlashAttention 2 not available, using default attention (higher VRAM usage)")

            try:
                # Force offline mode — must patch BEFORE from_pretrained calls.
                # transformers.utils.hub._is_offline_mode is cached at import time,
                # so setting env vars later has no effect. Patch the cached value directly.
                import os

                # Check if model is already cached
                from pathlib import Path
                cache_dir = Path.home() / ".cache" / "huggingface" / "hub"
                model_cache_path = cache_dir / f"models--{self.model.replace('/', '--')}"
                is_cached = model_cache_path.exists()

                # For Darwin-TTS model, download first if not cached
                if "Darwin-TTS" in self.model and not is_cached:
                    logger.info(f"Downloading Darwin-TTS model: {self.model}")
                    self._model = Qwen3TTSModel.from_pretrained(
                        self.model,
                        device_map=self.device,
                        dtype=self._get_torch_dtype(),
                    )
                    self._loaded = True
                    logger.info("Darwin-TTS model downloaded and loaded successfully")
                    return

                # For other models, use offline mode
                os.environ["HF_HUB_OFFLINE"] = "1"
                os.environ["TRANSFORMERS_OFFLINE"] = "1"
                import huggingface_hub.constants as hf_constants
                hf_constants.HF_HUB_OFFLINE = True
                import transformers.utils.hub as tf_hub
                tf_hub._is_offline_mode = True

                # Monkey-patch Qwen3TTSModel.from_pretrained to pass local_files_only
                # to AutoProcessor.from_pretrained (upstream bug: kwargs not forwarded).
                # Also strip fix_mistral_regex=True which triggers is_base_mistral() →
                # model_info() network call that fails in offline mode.
                import functools

                from transformers import AutoProcessor as _AutoProcessor
                _original_ap_fp = _AutoProcessor.from_pretrained
                @functools.wraps(_original_ap_fp)
                def _patched_ap_fp(*args, **ap_kwargs):
                    ap_kwargs.setdefault("local_files_only", True)
                    ap_kwargs.pop("fix_mistral_regex", None)  # triggers network in offline mode
                    return _original_ap_fp(*args, **ap_kwargs)
                _AutoProcessor.from_pretrained = _patched_ap_fp

                # Patch _patch_mistral_regex to skip is_base_mistral() network call.
                # is_base_mistral() calls model_info() which hits huggingface.co API.
                from transformers.tokenization_utils_base import PreTrainedTokenizerBase
                _original_pmr = PreTrainedTokenizerBase._patch_mistral_regex
                @classmethod
                def _offline_pmr(cls, *args, **_pmr_kwargs):
                    return args[0] if args else None  # return tokenizer unchanged
                PreTrainedTokenizerBase._patch_mistral_regex = _offline_pmr

                try:
                    self._model = Qwen3TTSModel.from_pretrained(
                        self.model,
                        local_files_only=True,
                        **kwargs,
                    )
                finally:
                    # Restore original methods
                    _AutoProcessor.from_pretrained = _original_ap_fp
                    PreTrainedTokenizerBase._patch_mistral_regex = _original_pmr
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
            except Exception as e:
                if "flash_attn" in str(e).lower() and "attn_implementation" in kwargs:
                    logger.warning("FlashAttention not installed, retrying with default attention...")
                    del kwargs["attn_implementation"]
                    self.use_flash_attn = False
                    self._model = Qwen3TTSModel.from_pretrained(self.model, **kwargs)
                    self._loaded = True
                    logger.info("Qwen3-TTS model loaded successfully (without FlashAttention)")
                else:
                    raise

    def _build_voice_clone_prompt(self):
        """Build and cache voice clone prompt from reference audio.

        Thread-safe: called under _load_lock after model is loaded.
        Returns cached prompt on subsequent calls.
        """
        if self._voice_clone_prompt is not None:
            return self._voice_clone_prompt

        if not self.ref_audio_path:
            raise ValueError("ref_audio_path must be set for voice clone mode")

        if not os.path.exists(self.ref_audio_path):
            raise FileNotFoundError(f"Reference audio not found: {self.ref_audio_path}")

        logger.info(f"Building voice clone prompt from: {self.ref_audio_path}")
        self._voice_clone_prompt = self._model.create_voice_clone_prompt(
            ref_audio=self.ref_audio_path,
            ref_text=self.ref_text,
            x_vector_only_mode=self.x_vector_only,
        )
        logger.debug(f"Voice clone prompt cached ({len(self._voice_clone_prompt)} items)")
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

        self._synth_done.clear()

        try:
            # Thread-safe model loading (blocking — must run in executor)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._load_model)

            effective_speaker = speaker or self.speaker
            effective_language = kwargs.get("language", self.language)
            effective_instruct = instruct or self.default_instruct

            logger.debug(
                f"Qwen3-TTS synthesis: text_len={len(text)}, "
                f"speaker={effective_speaker}, language={effective_language}"
            )

            if self.ref_audio_path:
                # Voice clone mode
                prompt = self._build_voice_clone_prompt()
                wavs, sr = await loop.run_in_executor(
                    None,
                    lambda: self._model.generate_voice_clone(
                        text=text,
                        language=effective_language,
                        voice_clone_prompt=prompt,
                        max_new_tokens=kwargs.get("max_new_tokens", self.max_new_tokens),
                        top_p=kwargs.get("top_p", self.top_p),
                        temperature=kwargs.get("temperature", self.temperature),
                        repetition_penalty=kwargs.get("repetition_penalty", self.repetition_penalty),
                    ),
                )
            else:
                # Custom voice mode (existing behavior)
                wavs, sr = await loop.run_in_executor(
                    None,
                    lambda: self._model.generate_custom_voice(
                        text=text,
                        language=effective_language,
                        speaker=effective_speaker,
                        instruct=effective_instruct,
                        max_new_tokens=kwargs.get("max_new_tokens", self.max_new_tokens),
                        top_p=kwargs.get("top_p", self.top_p),
                        temperature=kwargs.get("temperature", self.temperature),
                        repetition_penalty=kwargs.get("repetition_penalty", self.repetition_penalty),
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

            logger.debug(f"Qwen3-TTS synthesis successful: {len(audio_bytes)} bytes, sr={sr}")

            if output_path:
                output_path = Path(output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                sf.write(str(output_path), audio_data, sr)
                logger.info(f"Qwen3-TTS audio saved to: {output_path}")
                return str(output_path)
            return audio_bytes

        except Exception as e:
            logger.error(f"Qwen3-TTS synthesis failed: {e}")
            raise
        finally:
            self._synth_done.set()

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

        IMPORTANT: _load_model() is BLOCKING (~30s). Must run in executor
        to avoid freezing the event loop during server startup.
        Pattern matches ChatTTS preload (chattts_tts.py:103-105).
        """
        if self._loaded:
            logger.debug("Qwen3-TTS model already loaded, skipping preload")
            return

        logger.info(f"Preloading Qwen3-TTS model: {self.model}...")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._load_model)
        logger.info("Qwen3-TTS model preloaded successfully")

    async def close(self) -> None:
        """Clean up model and GPU memory.

        Waits for in-flight synthesis to complete (with 10s timeout)
        before unloading the model, preventing use-after-free in executor threads.
        """
        if self._model is None:
            return

        # Oracle fix #4: wait for in-flight synthesis before unloading
        if not self._synth_done.is_set():
            logger.debug("Waiting for in-flight synthesis to complete before closing...")
            try:
                await asyncio.wait_for(self._synth_done.wait(), timeout=10.0)
            except TimeoutError:
                logger.warning("Timed out waiting for synthesis to complete. Force unloading.")

        logger.info("Unloading Qwen3-TTS model...")
        self._model = None
        self._loaded = False
        self._voice_clone_prompt = None  # Invalidate cached prompt
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                logger.debug("GPU cache cleared after Qwen3-TTS unload")
        except ImportError:
            pass
        logger.info("Qwen3-TTS model unloaded")
