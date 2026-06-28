from __future__ import annotations

"""GPT-SoVITS SVC API bridge — converts vocals to target voice.

Supports two backends:
1. True SVC endpoint (/svc) - for GPT-SoVITS forks with SVC support
2. TTS endpoint (/tts) - standard GPT-SoVITS api_v2.py (TTS output, not melodic)
3. Health check: auto-detects available endpoints
"""

from pathlib import Path

import httpx
from loguru import logger


class SVCBridge:
    """Bridge to GPT-SoVITS api_v2.py for voice conversion."""

    def __init__(self, config: GPTSoVITSConfig):
        self.config = config
        self._client: httpx.AsyncClient | None = None
        self._has_svc = False
        self._has_tts = False

    def _ensure_client(self) -> None:
        if self._client is not None:
            return
        timeout = httpx.Timeout(300.0, connect=10.0)
        self._client = httpx.AsyncClient(
            base_url=self.config.base_url.rstrip("/"),
            timeout=timeout,
        )

    async def _check_endpoints(self) -> dict[str, bool]:
        """Probe available endpoints on the GPT-SoVITS server."""
        self._ensure_client()
        assert self._client is not None
        result = {}
        for endpoint in [self.config.svc_endpoint, "/tts"]:
            try:
                resp = await self._client.get(endpoint)
                result[endpoint] = resp.status_code not in (404, 405)
            except httpx.HTTPError:
                result[endpoint] = False
        self._has_svc = result.get(self.config.svc_endpoint, False)
        self._has_tts = result.get("/tts", False)
        return result

    async def convert(
        self,
        source_audio_path: str,
        output_path: str,
        pitch_adjust: int = 0,
    ) -> str:
        """Convert source vocals to target voice.

        Tries these strategies in order:
        1. Configured SVC endpoint (e.g. /svc) with audio upload
        2. GPT-SoVITS /tts endpoint (TTS-based, loses original melody)

        Returns:
            Path to converted audio file.

        Raises:
            ConnectionError: If no endpoint is reachable.
            RuntimeError: If all conversion attempts fail.
        """
        self._ensure_client()
        output_path_obj = Path(output_path)
        output_path_obj.parent.mkdir(parents=True, exist_ok=True)

        # Probe available endpoints
        endpoints = await self._check_endpoints()
        logger.info(f"SVC converting: {source_audio_path} | available endpoints: {endpoints}")

        # Strategy 1: True SVC endpoint (audio upload)
        if endpoints.get(self.config.svc_endpoint, False):
            logger.info(f"Attempting SVC via {self.config.svc_endpoint}")
            try:
                with open(source_audio_path, "rb") as f:
                    files = {"audio": f}
                    data = {
                        "pitch_adjust": pitch_adjust,
                        "ref_audio_path": self.config.ref_audio_path,
                        "prompt_text": self.config.prompt_text,
                    }
                    resp = await self._client.post(
                        self.config.svc_endpoint, files=files, data=data,
                    )
                if resp.status_code == 200:
                    output_path_obj.write_bytes(resp.content)
                    logger.info(f"SVC complete: {output_path_obj}")
                    return str(output_path_obj)
                else:
                    logger.warning(f"SVC endpoint returned HTTP {resp.status_code}, trying fallback")
            except httpx.HTTPError as e:
                logger.warning(f"SVC endpoint failed: {e}, trying fallback")

        # Strategy 2: GPT-SoVITS TTS endpoint
        if endpoints.get("/tts", False) and self.config.ref_audio_path:
            logger.info("Attempting voice conversion via /tts (TTS-based)")
            try:
                resp = await self._client.post(
                    "/tts",
                    json={
                        "text": self.config.prompt_text or " ",
                        "text_lang": self.config.text_lang,
                        "ref_audio_path": self.config.ref_audio_path,
                        "prompt_text": self.config.prompt_text or "",
                        "prompt_lang": self.config.text_lang,
                        "top_k": self.config.top_k,
                        "top_p": self.config.top_p,
                        "temperature": self.config.temperature,
                        "media_type": "wav",
                    },
                )
                if resp.status_code == 200:
                    output_path_obj.write_bytes(resp.content)
                    logger.info(f"TTS conversion complete (note: not true SVC): {output_path_obj}")
                    return str(output_path_obj)
                else:
                    logger.warning(f"TTS endpoint returned HTTP {resp.status_code}")
            except httpx.HTTPError as e:
                logger.warning(f"TTS endpoint failed: {e}")

        raise RuntimeError(
            f"No working voice conversion endpoint found on {self.config.base_url}. "
            f"Available: {endpoints}. "
            "Configure a valid SVC endpoint or skip voice conversion."
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
