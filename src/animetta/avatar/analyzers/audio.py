"""
Audio Analyzer
Calculates audio volume envelope for lip sync
"""

from pathlib import Path

from loguru import logger

try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    logger.warning("[AudioAnalyzer] pydub not available, please run: pip install pydub")


class AudioAnalyzer:
    """
    Audio Analyzer

    Calculates RMS volume envelope of audio for Live2D lip sync

    Sample rate: 50 Hz (one sample every 20ms)
    Output range: [0.0, 1.0] (normalized volume)
    """

    # Default sample rate: 50 Hz = one sample every 20ms
    DEFAULT_SAMPLE_RATE = 50  # Hz
    SAMPLE_INTERVAL_MS = 1000 / DEFAULT_SAMPLE_RATE  # 20ms

    def __init__(self, sample_rate: int = DEFAULT_SAMPLE_RATE):
        """
        Initialize the audio analyzer

        Args:
            sample_rate: Sample rate (Hz), default 50 Hz
        """
        if not PYDUB_AVAILABLE:
            raise RuntimeError("pydub not available, please run: pip install pydub")

        self.sample_rate = sample_rate
        self.sample_interval_ms = 1000 / sample_rate

    def compute_volume_envelope(
        self,
        audio_path: str,
        normalize: bool = True,
        gain: float = 1.8,
        use_peak: bool = False,
    ) -> list[float]:
        """
        Calculate the volume envelope of audio

        Args:
            audio_path: Audio file path
            normalize: Whether to normalize to [0.0, 1.0]
            gain: Gain factor to boost lip-sync amplitude (default 1.8)
            use_peak: Use peak amplitude instead of RMS (more responsive)

        Returns:
            Volume array, each value represents volume of one sample
        """
        try:
            # Load audio file
            audio = self._load_audio(audio_path)

            # Calculate number of samples
            duration_ms = len(audio)
            num_samples = int(duration_ms / self.sample_interval_ms)

            if num_samples == 0:
                logger.warning(f"[AudioAnalyzer] Audio too short: {audio_path}")
                return []

            # Calculate volume for each sample
            volumes = []
            for i in range(num_samples):
                start_ms = int(i * self.sample_interval_ms)
                end_ms = int((i + 1) * self.sample_interval_ms)

                # Extract segment
                segment = audio[start_ms:end_ms]

                # Use peak amplitude (more responsive) or RMS (smoother)
                if use_peak:
                    volumes.append(float(segment.max) / 32768.0)
                else:
                    volumes.append(segment.rms)

            # Normalize
            if normalize and volumes:
                max_volume = max(volumes)
                if max_volume > 0:
                    volumes = [v / max_volume for v in volumes]
                else:
                    volumes = [0.0] * len(volumes)

            # Apply gain and clamp to [0, 1] range (always, even without normalize)
            if volumes and gain != 1.0:
                volumes = [min(1.0, v * gain) for v in volumes]

            logger.debug(
                f"[AudioAnalyzer] Calculated {len(volumes)} volume samples "
                f"({duration_ms/1000:.2f}s audio, {self.sample_rate} Hz, gain={gain})"
            )

            return volumes

        except Exception as e:
            logger.warning(f"[AudioAnalyzer] Failed to analyze audio: {e}")
            return []

    def _load_audio(self, audio_path: str) -> "AudioSegment":
        """
        Load an audio file

        Args:
            audio_path: Audio file path

        Returns:
            AudioSegment object
        """
        path = Path(audio_path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        # pydub auto-detects format
        audio = AudioSegment.from_file(audio_path)

        # Convert to mono (easier to compute)
        audio = audio.set_channels(1)

        return audio

    def get_audio_duration(self, audio_path: str) -> float:
        """
        Get audio duration (seconds)

        Args:
            audio_path: Audio file path

        Returns:
            Duration in seconds
        """
        try:
            audio = self._load_audio(audio_path)
            return len(audio) / 1000.0  # ms → s
        except Exception as e:
            logger.error(f"[AudioAnalyzer] Failed to get audio duration: {e}")
            return 0.0


# Convenience function
def compute_volume_envelope(audio_path: str, sample_rate: int = 50, gain: float = 1.8) -> list[float]:
    """
    Convenience function: calculate audio volume envelope

    Args:
        audio_path: Audio file path
        sample_rate: Sample rate (Hz)
        gain: Gain factor

    Returns:
        Volume array [0.0, 1.0]
    """
    analyzer = AudioAnalyzer(sample_rate=sample_rate)
    return analyzer.compute_volume_envelope(audio_path, gain=gain)
