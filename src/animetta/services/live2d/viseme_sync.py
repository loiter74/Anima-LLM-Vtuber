from __future__ import annotations

"""
Viseme Lip Sync Engine
Viseme-based lip sync engine, ported from open-yachiyo

Uses spectral analysis to infer viseme weights for more natural lip sync
"""

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class VisemeConfig:
    """Viseme configuration"""
    # Band configuration (Hz)
    bands: dict[str, tuple[int, int]] = None

    # Viseme weight configuration
    weights: dict[str, list[float]] = None

    # Smoothing configuration
    attack: float = 0.02  # Attack time (seconds)
    release: float = 0.1  # Release time (seconds)
    smoothing: float = 0.3  # Smoothing coefficient

    def __post_init__(self):
        if self.bands is None:
            self.bands = {
                'low': (120, 360),      # Low frequency
                'lowMid': (360, 900),   # Low-mid frequency
                'mid': (900, 1800),     # Mid frequency
                'highMid': (1800, 3200), # High-mid frequency
                'high': (3200, 5200)    # High frequency
            }

        if self.weights is None:
            # 5 visemes: a, i, u, e, o
            # Each weight corresponds to a frequency band
            self.weights = {
                'a': [0.5, 0.3, 0.1, 0.0, 0.0],
                'i': [0.1, 0.3, 0.4, 0.2, 0.0],
                'u': [0.2, 0.1, 0.3, 0.3, 0.1],
                'e': [0.1, 0.2, 0.4, 0.2, 0.1],
                'o': [0.3, 0.1, 0.2, 0.2, 0.2]
            }


class VisemeLipSync:
    """
    Viseme Lip Sync Engine

    Features:
    1. Audio spectrum analysis
    2. Viseme weight inference
    3. Smooth transition handling
    4. Output Live2D mouth parameters
    """

    def __init__(self, config: VisemeConfig = None, sample_rate: int = 24000):
        self.config = config or VisemeConfig()
        self.sample_rate = sample_rate

        # 状态
        self._current_weights: np.ndarray = np.zeros(5)
        self._target_weights: np.ndarray = np.zeros(5)

        # 窗口大小
        self.window_size = 1024

    def extract_band_energy(
        self,
        frequency_buffer: np.ndarray,
        sample_rate: int,
        min_freq: int,
        max_freq: int
    ) -> float:
        """
        Extract energy of a specified frequency band

        Args:
            frequency_buffer: Frequency data
            sample_rate: Sample rate
            min_freq: Minimum frequency
            max_freq: Maximum frequency

        Returns:
            Band energy
        """
        # Calculate frequency index
        min_idx = int(min_freq * len(frequency_buffer) / (sample_rate / 2))
        max_idx = int(max_freq * len(frequency_buffer) / (sample_rate / 2))

        # Boundary check
        min_idx = max(0, min_idx)
        max_idx = min(len(frequency_buffer), max_idx)

        # Calculate energy
        if max_idx > min_idx:
            band_energy = np.mean(np.abs(frequency_buffer[min_idx:max_idx]))
        else:
            band_energy = 0.0

        return float(band_energy)

    def extract_viseme_features(
        self,
        audio_data: np.ndarray,
        voice_energy: float
    ) -> list[float]:
        """
        Extract viseme features

        Args:
            audio_data: Audio data
            voice_energy: Voice energy

        Returns:
            Band energy list [low, lowMid, mid, highMid, high]
        """
        # FFT
        if len(audio_data) < self.window_size:
            # Pad to window size
            padded = np.zeros(self.window_size)
            padded[:len(audio_data)] = audio_data
            audio_data = padded

        # Apply window function
        window = np.hanning(len(audio_data))
        windowed = audio_data * window

        # FFT
        fft_result = np.fft.rfft(windowed)
        magnitude = np.abs(fft_result)

        # Extract band energies
        features = []
        for band_name in ['low', 'lowMid', 'mid', 'highMid', 'high']:
            min_freq, max_freq = self.config.bands[band_name]
            energy = self.extract_band_energy(
                magnitude,
                self.sample_rate,
                min_freq,
                max_freq
            )
            features.append(energy)

        return features

    def infer_viseme_weights(self, features: list[float]) -> np.ndarray:
        """
        Infer viseme weights

        Args:
            features: Band features

        Returns:
            Viseme weights [a, i, u, e, o]
        """
        features_array = np.array(features)

        # Normalize
        total = np.sum(features_array)
        normalized = features_array / total if total > 0 else np.zeros_like(features_array)

        # Calculate weight for each viseme
        weights = []
        for viseme in ['a', 'i', 'u', 'e', 'o']:
            viseme_weight = np.dot(normalized, self.config.weights[viseme])
            weights.append(viseme_weight)

        return np.array(weights)

    def apply_smoothing(self, target_weights: np.ndarray) -> np.ndarray:
        """
        Apply smooth transition

        Args:
            target_weights: Target weights

        Returns:
            Smoothed weights
        """
        # Calculate smoothing coefficient
        alpha = self.config.smoothing

        # Apply exponential smoothing
        smoothed = alpha * target_weights + (1 - alpha) * self._current_weights

        self._current_weights = smoothed
        return smoothed

    def process_audio(
        self,
        audio_data: np.ndarray,
        voice_energy: float = 1.0
    ) -> dict[str, float]:
        """
        Process audio and return mouth parameters

        Args:
            audio_data: Audio data
            voice_energy: Voice energy (0-1)

        Returns:
            Mouth parameter dictionary
        """
        # Extract features
        features = self.extract_viseme_features(audio_data, voice_energy)

        # Infer viseme weights
        target_weights = self.infer_viseme_weights(features)

        # Apply smoothing
        smoothed_weights = self.apply_smoothing(target_weights)

        # Convert to Live2D parameters
        return self._weights_to_params(smoothed_weights, voice_energy)

    def _weights_to_params(
        self,
        weights: np.ndarray,
        voice_energy: float
    ) -> dict[str, float]:
        """
        Convert viseme weights to Live2D parameters

        Args:
            weights: Viseme weights [a, i, u, e, o]
            voice_energy: Voice energy

        Returns:
            Live2D parameters
        """
        # Calculate mouth openness
        # a: wide open, i: horizontal spread, u: rounded, e: flat, o: protruded

        a, i, u, e, o = weights

        # Main parameters
        mouth_open = (a * 0.8 + o * 0.4 + u * 0.2) * voice_energy
        mouth_form = (i * 0.5 + e * 0.3) * voice_energy

        return {
            'ParamMouthOpen': mouth_open,
            'ParamMouthForm': mouth_form
        }

    def reset(self):
        """Reset state"""
        self._current_weights = np.zeros(5)
        self._target_weights = np.zeros(5)


class SimpleLipSync:
    """
    Simple lip sync (RMS-based)

    Fallback for Viseme mode
    """

    def __init__(self, sensitivity: float = 2.5, smoothing: float = 0.3):
        self.sensitivity = sensitivity
        self.smoothing = smoothing
        self._current_value = 0.0

    def process_audio(self, audio_data: np.ndarray) -> float:
        """
        Process audio and return mouth openness

        Args:
            audio_data: Audio data

        Returns:
            Mouth openness (0-1)
        """
        # Calculate RMS
        rms = np.sqrt(np.mean(audio_data ** 2))

        # Apply sensitivity
        target_value = min(1.0, rms * self.sensitivity)

        # Smooth
        self._current_value = (
            self.smoothing * target_value +
            (1 - self.smoothing) * self._current_value
        )

        return self._current_value

    def reset(self):
        """Reset state"""
        self._current_value = 0.0


# ==================== Factory function ====================

def create_lip_sync_engine(
    mode: str = "viseme",
    sample_rate: int = 24000,
    **kwargs
) -> Any:
    """
    Create a lip sync engine

    Args:
        mode: Mode ("viseme" or "simple")
        sample_rate: Sample rate
        **kwargs: Other configuration

    Returns:
        Lip sync engine instance
    """
    if mode == "viseme":
        config = VisemeConfig(**kwargs)
        return VisemeLipSync(config, sample_rate)
    elif mode == "simple":
        return SimpleLipSync(**kwargs)
    else:
        raise ValueError(f"Unknown lip sync mode: {mode}")
