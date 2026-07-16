from __future__ import annotations

"""
RVC (Retrieval-based Voice Conversion) service implementation.

Provides zero-shot voice timbre conversion using a local RVC model checkpoint.
Wraps blocking RVC inference in asyncio.to_thread() for async compatibility.

Key design decisions:
- n_cpu=1 to avoid multiprocessing queue requirement (critical for async)
- f0method="rmvpe" which doesn't need multiprocessing
- Lazy model loading on first convert() call
- Duck-typed config to bypass RVC's @singleton_variable pattern
"""

import asyncio
import io
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import soundfile as sf
from loguru import logger

from animetta.config.providers.vc.rvc import RVCConfig

from .interface import VCInterface

RVC_PROJECT_ROOT = "C:/Users/30262/RVC20240604Nvidia"


from animetta.config.core.registry import ProviderRegistry


@ProviderRegistry.register_service("vc", "rvc")
class RVCVC(VCInterface):
    """
    RVC voice conversion implementation.

    Loads a local RVC model checkpoint (.pth) and optional feature index (.index)
    for zero-shot voice timbre conversion. Input audio is processed through the
    RVC pipeline and returned with the target voice timbre applied.

    The RVC inference is blocking (CPU/GPU-bound), so it's wrapped in
    asyncio.to_thread() to avoid blocking the event loop.
    """

    def __init__(
        self,
        model_path: str,
        index_path: str = "",
        index_rate: float = 0.0,
        f0_method: str = "rmvpe",
        key: int = 0,
        formant: int = 0,
        device: str = "cuda:0",
        is_half: bool = True,
        rms_mix_rate: float = 1.0,
        protect: float = 0.33,
        hop_length: int = 128,
        f0_min: int = 50,
        f0_max: int = 1100,
        sample_rate: int = 40000,
    ):
        self.model_path = model_path
        self.index_path = index_path
        self.index_rate = index_rate
        self.f0_method = f0_method
        self.key = key
        self.formant = formant
        self.device = device
        self.is_half = is_half
        self.rms_mix_rate = rms_mix_rate
        self.protect = protect
        self.hop_length = hop_length
        self.f0_min = f0_min
        self.f0_max = f0_max
        self.sample_rate = sample_rate

        self._rvc: Any | None = None
        self._model_loaded: bool = False

    # ------------------------------------------------------------------
    #  Lazy model loading
    # ------------------------------------------------------------------

    def _ensure_model(self) -> None:
        """Load the RVC model on first use (lazy initialization).

        Imports RVC modules with isolated sys.path management to avoid
        polluting the global import space. Handles the Config singleton
        issue by creating a duck-typed config namespace instead of
        instantiating RVC's global singleton Config.
        """
        if self._model_loaded:
            return

        if not self.model_path:
            raise ValueError("RVC model_path is required for voice conversion")

        # ── sys.path isolation ──────────────────────────────────────
        sys.path.insert(0, RVC_PROJECT_ROOT)
        try:
            from infer.lib.rtrvc import RVC
        except ImportError as e:
            if RVC_PROJECT_ROOT in sys.path:
                sys.path.remove(RVC_PROJECT_ROOT)
            logger.error(f"Failed to import RVC modules from {RVC_PROJECT_ROOT}: {e}")
            raise ImportError(
                f"RVC project not found at {RVC_PROJECT_ROOT}. "
                f"Please ensure the RVC project is installed at the expected location."
            ) from e
        finally:
            # Keep RVC_PROJECT_ROOT in sys.path — RVC performs lazy
            # imports during inference (e.g., from infer.lib.rmvpe import RMVPE)
            # that require this path to be present.
            pass

        # ── Pre-load lazy RVC dependencies ──────────────────────────
        # Trigger module-level lazy imports now while sys.path is safe.
        if self.f0_method == "rmvpe":
            try:
                from infer.lib.rmvpe import RMVPE  # noqa: F401
            except ImportError:
                logger.warning("Could not pre-load RMVPE module; will be loaded on inference")

        # ── Duck-typed config (bypass @singleton_variable) ───────────
        # RVC's Config class uses @singleton_variable which caches the
        # instance globally. We create a lightweight namespace with the
        # exact attributes that RVC's internal code accesses:
        #   config.dml, config.device, config.is_half, config.use_jit
        rvc_config = SimpleNamespace()
        rvc_config.device = self.device
        rvc_config.is_half = self.is_half
        rvc_config.use_jit = False
        rvc_config.dml = False

        # Fall back to CPU if CUDA is requested but unavailable
        try:
            import torch

            if self.device.startswith("cuda") and not torch.cuda.is_available():
                logger.warning("CUDA not available, falling back to CPU for RVC")
                rvc_config.device = "cpu"
                rvc_config.is_half = False
        except ImportError:
            rvc_config.device = "cpu"
            rvc_config.is_half = False

        # ── Build the RVC model ─────────────────────────────────────
        # n_cpu=1 is critical: prevents multiprocessing queue usage
        # and makes the blocking call safely wrappable in asyncio.to_thread()
        try:
            self._rvc = RVC(
                key=self.key,
                formant=self.formant,
                pth_path=self.model_path,
                index_path=self.index_path,
                index_rate=self.index_rate,
                n_cpu=1,
                inp_q=None,  # n_cpu=1 → queues are unused
                opt_q=None,  # n_cpu=1 → queues are unused
                config=rvc_config,
            )
        except Exception as e:
            logger.error(f"Failed to construct RVC model: {e}")
            raise RuntimeError(f"RVC model construction failed: {e}") from e

        logger.info(
            f"RVC model loaded: {self.model_path} "
            f"(device={rvc_config.device}, is_half={rvc_config.is_half})"
        )
        self._model_loaded = True

    # ------------------------------------------------------------------
    #  Core interface — VCInterface
    # ------------------------------------------------------------------

    async def convert(
        self,
        audio: bytes,
        output_path: str | Path | None = None,
        **kwargs,
    ) -> bytes | str:
        """
        Convert voice timbre of input audio using RVC.

        Args:
            audio: Input audio bytes (WAV format)
            output_path: Optional output file path. If provided, writes
                         the result to disk and returns the path string.
            **kwargs: Additional conversion parameters (reserved for future use).

        Returns:
            Union[bytes, str]: WAV audio bytes, or file path if output_path is set.

        Raises:
            ValueError: If model not configured.
            RuntimeError: If RVC inference fails.
        """
        self._ensure_model()

        # ── Decode input WAV → numpy ────────────────────────────────
        audio_io = io.BytesIO(audio)
        audio_np, sr = sf.read(audio_io, dtype="float32")
        if audio_np.ndim > 1:
            audio_np = audio_np.mean(axis=1)  # stereo → mono

        logger.debug(
            f"RVC converting: {audio_np.shape[0]} samples, sr={sr}, "
            f"f0method={self.f0_method}, key={self.key}"
        )

        # ── numpy → torch.Tensor (1D float32) ───────────────────────
        import torch

        audio_tensor = torch.from_numpy(audio_np.copy()).float()

        # ── Blocking RVC inference → asyncio.to_thread() ────────────
        try:
            rvc = self._rvc
            if rvc is None:
                raise RuntimeError("RVC model is not loaded")
            result_np = await asyncio.to_thread(
                rvc.infer,
                input_wav=audio_tensor,
                block_frame_16k=400,
                skip_head=0,
                return_length=0,
                f0method=self.f0_method,
            )
        except Exception as e:
            logger.error(f"RVC inference failed: {e}")
            raise RuntimeError(f"RVC voice conversion failed: {e}") from e

        # ── numpy → WAV bytes ───────────────────────────────────────
        output_io = io.BytesIO()
        sf.write(output_io, result_np, self.sample_rate, format="WAV")
        wav_bytes = output_io.getvalue()

        if output_path is not None:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(wav_bytes)
            logger.debug(f"RVC conversion saved to: {output_path}")
            return str(output_path)

        logger.debug(
            f"RVC conversion complete: {audio_np.shape[0]} -> {result_np.shape[0]} samples"
        )
        return wav_bytes

    # ------------------------------------------------------------------
    #  Lifecycle
    # ------------------------------------------------------------------

    async def preload(self) -> None:
        """
        Warm up the RVC model by running a silent dummy conversion.

        Called during server startup via ModelLoadingManager to ensure
        the first real user request doesn't pay cold-start cost (model
        loading + GPU warm-up).
        """
        try:
            self._ensure_model()

            import torch

            # 1 second of silence at 16 kHz
            silence = np.zeros(16000, dtype=np.float32)
            silence_tensor = torch.from_numpy(silence).float()
            rvc = self._rvc
            if rvc is None:
                raise RuntimeError("RVC model is not loaded")

            await asyncio.to_thread(
                rvc.infer,
                input_wav=silence_tensor,
                block_frame_16k=400,
                skip_head=0,
                return_length=0,
                f0method=self.f0_method,
            )
            logger.info("RVC preload (warmup) completed successfully")
        except Exception as e:
            logger.warning(f"RVC preload (warmup) failed — non-fatal: {e}")

    async def close(self) -> None:
        """Release RVC resources and free GPU memory."""
        self._rvc = None
        self._model_loaded = False

        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                logger.debug("RVC GPU cache cleared")
        except ImportError:
            pass

    # ------------------------------------------------------------------
    #  Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, config: RVCConfig) -> RVCVC:
        """Create an RVCVC instance from an RVCConfig object.

        Used by ProviderRegistry.create_service("vc", config) for
        automatic plugin-based instantiation.
        """
        return cls(
            model_path=config.model_path,
            index_path=config.index_path,
            index_rate=config.index_rate,
            f0_method=config.f0_method,
            key=config.key,
            formant=config.formant,
            device=config.device,
            is_half=config.is_half,
            rms_mix_rate=config.rms_mix_rate,
            protect=config.protect,
            hop_length=config.hop_length,
            f0_min=config.f0_min,
            f0_max=config.f0_max,
            sample_rate=config.sample_rate,
        )
