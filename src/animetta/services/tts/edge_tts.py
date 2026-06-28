"""
Edge TTS implementation - uses Microsoft Edge browser's free speech synthesis

Supports voice effects via SSML prosody adjustments:
- rate: speech rate ("+15%", "-10%", etc.)
- pitch: voice pitch ("+60Hz", "+30%", etc.)
- preset: "neurosama" for Neuro-sama style electronic cute voice
"""

from __future__ import annotations

import tempfile
from pathlib import Path

# Status: active
# Last verified: 2026-05-23
from loguru import logger

from animetta.config.core.registry import ProviderRegistry

from .interface import TTSInterface


def _wrap_ssml(text: str, voice: str, rate: str | None = None, pitch: str | None = None) -> str:
    """
    Wrap text in SSML with optional prosody adjustments.

    Used for voice effects like Neuro-sama's electronic cute voice.
    """
    # If already SSML, don't double-wrap
    if text.strip().startswith("<speak"):
        return text

    # Escape XML special characters
    text = (text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;"))

    prosody_open = ""
    prosody_close = ""
    if rate or pitch:
        attrs = []
        if rate:
            attrs.append(f'rate="{rate}"')
        if pitch:
            attrs.append(f'pitch="{pitch}"')
        prosody_open = f'<prosody {" ".join(attrs)}>'
        prosody_close = "</prosody>"

    return (
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-CN">\n'
        f'  <voice name="{voice}">\n'
        f'    {prosody_open}{text}{prosody_close}\n'
        f'  </voice>\n'
        f'</speak>'
    )


# Neuro-sama style voice preset
NEUROSAMA_PRESET = {
    "voice": "zh-CN-XiaoxiaoNeural",
    "rate": "+25%",
    "pitch": "+120Hz",
}


@ProviderRegistry.register_service("tts", "edge")
class EdgeTTS(TTSInterface):
    """
    Edge TTS implementation.
    Uses Microsoft Edge browser's free speech synthesis service.
    No API Key required, completely free.

    Supports SSML prosody for voice effects:
    - rate: Adjust speech speed ("+15%", "-10%")
    - pitch: Adjust voice pitch ("+60Hz", "+30%")
    - preset: "neurosama" for an electronic cute voice
    """

    def __init__(
        self,
        voice: str = "zh-CN-XiaoxiaoNeural",
        rate: str | None = None,
        pitch: str | None = None,
    ):
        """
        Initialize Edge TTS.

        Args:
            voice: Voice name, e.g. zh-CN-XiaoxiaoNeural
            rate: Speech rate adjustment (e.g. "+15%"). None = normal.
            pitch: Voice pitch adjustment (e.g. "+60Hz"). None = normal.
        """
        self.voice = voice
        self.rate = rate
        self.pitch = pitch
        self._communicate = None

    @classmethod
    def from_config(cls, config, **kwargs):
        """Create instance from config, supporting presets like 'neurosama'."""
        voice = getattr(config, 'voice', 'zh-CN-XiaoxiaoNeural')
        rate = getattr(config, 'rate', None)
        pitch = getattr(config, 'pitch', None)

        preset_name = getattr(config, 'preset', None)
        if preset_name == "neurosama":
            voice = NEUROSAMA_PRESET["voice"]
            rate = NEUROSAMA_PRESET["rate"]
            pitch = NEUROSAMA_PRESET["pitch"]
            logger.info(f"[EdgeTTS] Using Neuro-sama preset: rate={rate}, pitch={pitch}")

        if rate or pitch:
            logger.info(f"[EdgeTTS] Voice effects enabled: rate={rate}, pitch={pitch}")

        return cls(voice=voice, rate=rate, pitch=pitch)

    def _get_communicate(self):
        """Lazy-load edge-tts communicate method."""
        if self._communicate is None:
            try:
                import edge_tts
                self._communicate = edge_tts.Communicate
                logger.info("Edge TTS client initialized successfully")
            except ImportError as e:
                logger.error("edge-tts not installed, please run: pip install edge-tts")
                raise ImportError("edge-tts is not installed, please run: pip install edge-tts") from e
        return self._communicate

    async def synthesize(
        self,
        text: str,
        output_path: str | Path | None = None,
        voice: str | None = None,
        **kwargs
    ) -> bytes | str:
        """
        Synthesize text to speech.

        Uses SSML with prosody adjustments when rate/pitch are configured.

        Args:
            text: Text to synthesize
            output_path: Output file path (optional)
            voice: Voice name (optional, overrides default)

        Returns:
            Audio bytes or file path string
        """
        import edge_tts

        actual_voice = voice or self.voice

        # Wrap in SSML if effects are enabled
        if self.rate or self.pitch:
            ssml_text = _wrap_ssml(text, actual_voice, rate=self.rate, pitch=self.pitch)
            communicate_instance = edge_tts.Communicate(ssml_text, actual_voice)
        else:
            communicate_instance = edge_tts.Communicate(text, actual_voice)

        if output_path is None:
            import io
            output_buffer = io.BytesIO()
            output_path_is_temp = True
        else:
            output_path = Path(output_path)
            output_path_is_temp = False

        try:
            if output_path_is_temp:
                async for chunk in communicate_instance.stream():
                    if chunk["type"] == "audio":
                        output_buffer.write(chunk["data"])

                audio_data = output_buffer.getvalue()
                logger.debug(f"Edge TTS synthesis complete: {len(text)} chars -> {len(audio_data)} bytes")

                if not kwargs.get('return_bytes', False):
                    temp_file = tempfile.mktemp(suffix=".mp3")
                    with open(temp_file, "wb") as f:
                        f.write(audio_data)
                    return temp_file
                return audio_data
            else:
                with open(output_path, "wb") as f:
                    async for chunk in communicate_instance.stream():
                        if chunk["type"] == "audio":
                            f.write(chunk["data"])

                logger.debug(f"Edge TTS synthesis complete: {len(text)} chars -> {output_path}")
                return str(output_path)

        except Exception as e:
            logger.error(f"Edge TTS synthesis failed: {e}")
            raise
        finally:
            if output_path_is_temp and 'output_buffer' in locals():
                output_buffer.close()

    async def close(self) -> None:
        """Clean up resources."""
        self._communicate = None
        logger.debug("Edge TTS resources released")
