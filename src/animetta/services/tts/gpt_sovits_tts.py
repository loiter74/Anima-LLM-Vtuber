from __future__ import annotations

"""
GPT-SoVITS TTS implementation - few-shot voice cloning via REST API

Connects to a locally running GPT-SoVITS api_v2.py server.
Supports reference audio based voice cloning with configurable inference parameters.
"""

from pathlib import Path

# Status: active
# Last verified: 2026-05-23
from loguru import logger

from animetta.config.core.registry import ProviderRegistry

from .interface import TTSInterface


@ProviderRegistry.register_service("tts", "gpt_sovits")
class GPTSoVITSTTS(TTSInterface):
    """
    GPT-SoVITS TTS implementation.

    Connects to a locally running GPT-SoVITS api_v2.py server via HTTP REST API.
    The server must be started separately by the user.

    Supports few-shot voice cloning: provide a reference audio file and its
    transcript, and the model will synthesize speech in the reference speaker's voice.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:9880",
        ref_audio_path: str = "",
        prompt_text: str = "",
        prompt_lang: str = "zh",
        text_lang: str = "zh",
        top_k: int = 15,
        top_p: float = 1.0,
        temperature: float = 1.0,
        speed: float = 1.0,
        media_type: str = "wav",
        streaming_mode: bool = False,
        text_split_method: str = "cut5",
        sample_steps: int = 32,
        seed: int = -1,
        aux_ref_audio_paths: list = None,
    ):
        """
        Initialize GPT-SoVITS TTS client.

        Args:
            base_url: GPT-SoVITS api_v2.py server URL
            ref_audio_path: Path to reference audio file on the server
            prompt_text: Transcript of the reference audio
            prompt_lang: Language of the prompt text
            text_lang: Language of the text to synthesize
            top_k: Top-k sampling parameter
            top_p: Top-p sampling parameter
            temperature: Sampling temperature
            speed: Speed factor
            media_type: Audio output format (wav/ogg/aac/raw)
            streaming_mode: Enable streaming mode
            text_split_method: Text segmentation method
            sample_steps: Sampling steps for V3/V4 models
            seed: Random seed (-1 for random)
            aux_ref_audio_paths: Auxiliary reference audio paths for multi-speaker tone fusion
        """
        self.base_url = base_url.rstrip("/")
        self.ref_audio_path = ref_audio_path
        self.prompt_text = prompt_text
        self.prompt_lang = prompt_lang
        self.text_lang = text_lang
        self.top_k = top_k
        self.top_p = top_p
        self.temperature = temperature
        self.speed = speed
        self.media_type = media_type
        self.streaming_mode = streaming_mode
        self.text_split_method = text_split_method
        self.sample_steps = sample_steps
        self.seed = seed
        self.aux_ref_audio_paths = aux_ref_audio_paths

        self._client = None

    def _ensure_client(self):
        """Lazy-create httpx AsyncClient."""
        if self._client is not None:
            return

        try:
            import httpx
        except ImportError as e:
            logger.error("httpx not installed, please run: pip install httpx")
            raise ImportError(
                "httpx is not installed, please run: pip install httpx"
            ) from e

        timeout = httpx.Timeout(30.0, connect=10.0)
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)
        logger.info(f"GPT-SoVITS HTTP client initialized (base_url={self.base_url})")

    async def _call_api(
        self,
        text: str,
        ref_audio_path: str | None = None,
        prompt_text: str | None = None,
        prompt_lang: str | None = None,
        text_lang: str | None = None,
        **kwargs
    ) -> bytes:
        """
        Send TTS request to GPT-SoVITS API.

        Args:
            text: Text to synthesize
            ref_audio_path: Override reference audio path
            prompt_text: Override prompt text
            prompt_lang: Override prompt language
            text_lang: Override text language
            **kwargs: Additional parameters to override defaults

        Returns:
            Audio bytes (WAV format)

        Raises:
            ConnectionError: If the server is unreachable
            RuntimeError: If the API returns an error
        """
        self._ensure_client()

        payload = {
            "text": text,
            "text_lang": text_lang or self.text_lang,
            "ref_audio_path": ref_audio_path or self.ref_audio_path,
            "prompt_text": prompt_text or self.prompt_text,
            "prompt_lang": prompt_lang or self.prompt_lang,
            "top_k": kwargs.get("top_k", self.top_k),
            "top_p": kwargs.get("top_p", self.top_p),
            "temperature": kwargs.get("temperature", self.temperature),
            "speed_factor": kwargs.get("speed", self.speed),
            "media_type": kwargs.get("media_type", self.media_type),
            "streaming_mode": kwargs.get("streaming_mode", self.streaming_mode),
            "text_split_method": kwargs.get("text_split_method", self.text_split_method),
            "sample_steps": kwargs.get("sample_steps", self.sample_steps),
            "seed": kwargs.get("seed", self.seed),
        }
        # Add auxiliary reference audio for multi-speaker tone fusion if configured
        aux_refs = kwargs.get("aux_ref_audio_paths", self.aux_ref_audio_paths)
        if aux_refs:
            payload["aux_ref_audio_paths"] = aux_refs

        logger.debug(f"GPT-SoVITS payload: text_len={len(payload.get('text',''))}, ref_audio={payload.get('ref_audio_path','')[:60]}, lang={payload.get('text_lang')}")

        try:
            response = await self._client.post("/tts", json=payload)
        except Exception as e:
            logger.error(f"GPT-SoVITS server not reachable at {self.base_url}: {e}")
            raise ConnectionError(
                f"GPT-SoVITS server at {self.base_url} is not reachable. "
                f"Please ensure api_v2.py is running. Error: {e}"
            ) from e

        if response.status_code == 200:
            return response.content
        else:
            try:
                error_body = response.json()
                error_msg = error_body.get("message", str(error_body))
                error_detail = error_body.get("Exception", "")
                if error_detail:
                    error_msg += f" | Detail: {error_detail[:500]}"
            except Exception:
                error_msg = response.text

            logger.error(f"GPT-SoVITS API error ({response.status_code}): {error_msg}")
            raise RuntimeError(
                f"GPT-SoVITS synthesis failed (HTTP {response.status_code}): {error_msg}"
            )

    async def preload(self) -> None:
        """Warm up GPT-SoVITS by sending a short dummy request.

        Called during server startup via ModelLoadingManager to ensure
        the first real user request doesn't pay cold-start cost.
        """
        try:
            await self._call_api("Hello.", text_lang="en")
            logger.info("[GPT-SoVITS] Warmup request succeeded")
        except Exception as e:
            logger.info(f"[GPT-SoVITS] Warmup failed (non-fatal): {e}")

    async def synthesize(
        self,
        text: str,
        output_path: str | Path | None = None,
        **kwargs
    ) -> bytes | str:
        """
        Synthesize text to speech using GPT-SoVITS.

        Args:
            text: Text to synthesize
            output_path: Output file path (optional)
            **kwargs: May include ref_audio_path, prompt_text, prompt_lang,
                     text_lang, top_k, top_p, temperature, speed, etc.
                     to override configured defaults.

        Returns:
            Union[bytes, str]: If output_path is specified, returns the file path string.
                               Otherwise returns WAV audio byte data.
        """
        if not text:
            logger.warning("GPT-SoVITS: empty text, returning silence")
            import struct

            import numpy as np
            silence = np.zeros(24000, dtype=np.int16)
            header = struct.pack(
                '<4sI4s4sIHHIIHH4sI',
                b'RIFF', 36 + len(silence) * 2, b'WAVE', b'fmt ',
                16, 1, 1, 24000, 48000, 2, 16, b'data', len(silence) * 2,
            )
            audio_bytes = header + silence.tobytes()
            if output_path:
                output_path = Path(output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "wb") as f:
                    f.write(audio_bytes)
                return str(output_path)
            return audio_bytes

        logger.debug(f"GPT-SoVITS synthesizing: {len(text)} chars")

        audio_bytes = await self._call_api(text, **kwargs)

        if output_path is not None:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(audio_bytes)
            logger.debug(f"GPT-SoVITS synthesis complete: {len(text)} chars -> {output_path}")
            return str(output_path)
        else:
            logger.debug(f"GPT-SoVITS synthesis complete: {len(text)} chars -> {len(audio_bytes)} bytes")
            return audio_bytes

    async def close(self) -> None:
        """Close the HTTP client and release connections."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.debug("GPT-SoVITS HTTP client closed")

    @classmethod
    def from_config(cls, config: GPTSoVITSConfig) -> GPTSoVITSTTS:
        """Create instance from configuration."""
        return cls(
            base_url=config.base_url,
            ref_audio_path=config.ref_audio_path,
            prompt_text=config.prompt_text,
            prompt_lang=config.prompt_lang,
            text_lang=config.text_lang,
            top_k=config.top_k,
            top_p=config.top_p,
            temperature=config.temperature,
            speed=config.speed,
            media_type=config.media_type,
            streaming_mode=config.streaming_mode,
            text_split_method=config.text_split_method,
            sample_steps=config.sample_steps,
            seed=config.seed,
            aux_ref_audio_paths=config.aux_ref_audio_paths,
        )
