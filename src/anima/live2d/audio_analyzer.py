"""
音频分析器
计算音频的音量包络用于口型同步
"""

import math
from typing import List, Optional
from pathlib import Path
from loguru import logger

try:
    from pydub import AudioSegment
    from pydub.utils import mediainfo
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    logger.warning("[AudioAnalyzer] pydub 不可用，请运行: pip install pydub")


class AudioAnalyzer:
    """
    音频分析器

    计算音频的 RMS 音量包络，用于 Live2D 口型同步

    采样率: 50 Hz (每 20ms 一个采样点)
    输出范围: [0.0, 1.0] (归一化音量)
    """

    # 默认采样率: 50 Hz = 每 20ms 一个采样点
    DEFAULT_SAMPLE_RATE = 50  # Hz
    SAMPLE_INTERVAL_MS = 1000 / DEFAULT_SAMPLE_RATE  # 20ms

    def __init__(self, sample_rate: int = DEFAULT_SAMPLE_RATE):
        """
        初始化音频分析器

        Args:
            sample_rate: 采样率（Hz），默认 50 Hz
        """
        if not PYDUB_AVAILABLE:
            raise RuntimeError("pydub 不可用，请运行: pip install pydub")

        self.sample_rate = sample_rate
        self.sample_interval_ms = 1000 / sample_rate

    def compute_volume_envelope(
        self,
        audio_path: str,
        normalize: bool = True
    ) -> List[float]:
        """
        计算音频的音量包络

        Args:
            audio_path: 音频文件路径
            normalize: 是否归一化到 [0.0, 1.0]

        Returns:
            音量数组，每个值代表一个采样点的 RMS 音量
        """
        try:
            # 加载音频文件
            audio = self._load_audio(audio_path)

            # 计算采样点数量
            duration_ms = len(audio)
            num_samples = int(duration_ms / self.sample_interval_ms)

            if num_samples == 0:
                logger.warning(f"[AudioAnalyzer] 音频太短: {audio_path}")
                return []

            # 计算每个采样点的 RMS 音量
            volumes = []
            for i in range(num_samples):
                start_ms = int(i * self.sample_interval_ms)
                end_ms = int((i + 1) * self.sample_interval_ms)

                # 提取片段
                segment = audio[start_ms:end_ms]

                # 计算 RMS 音量
                rms = segment.rms

                # 转换为分贝（避免零值）
                if rms > 0:
                    db = 20 * math.log10(rms)
                else:
                    db = -float('inf')

                volumes.append(rms)

            # 归一化
            if normalize and volumes:
                max_volume = max(volumes)
                if max_volume > 0:
                    volumes = [v / max_volume for v in volumes]
                else:
                    volumes = [0.0] * len(volumes)

            logger.debug(
                f"[AudioAnalyzer] 计算了 {len(volumes)} 个音量采样点 "
                f"({duration_ms/1000:.2f}s 音频, {self.sample_rate} Hz)"
            )

            return volumes

        except Exception as e:
            logger.error(f"[AudioAnalyzer] 分析音频失败: {e}")
            return []

    def _load_audio(self, audio_path: str) -> AudioSegment:
        """
        加载音频文件

        Args:
            audio_path: 音频文件路径

        Returns:
            AudioSegment 对象
        """
        path = Path(audio_path)
        if not path.exists():
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")

        # pydub 自动检测格式
        audio = AudioSegment.from_file(audio_path)

        # 转换为单声道（便于计算）
        audio = audio.set_channels(1)

        return audio

    def get_audio_duration(self, audio_path: str) -> float:
        """
        获取音频时长（秒）

        Args:
            audio_path: 音频文件路径

        Returns:
            时长（秒）
        """
        try:
            audio = self._load_audio(audio_path)
            return len(audio) / 1000.0  # ms → s
        except Exception as e:
            logger.error(f"[AudioAnalyzer] 获取音频时长失败: {e}")
            return 0.0


# 便捷函数
def compute_volume_envelope(audio_path: str, sample_rate: int = 50) -> List[float]:
    """
    便捷函数：计算音频音量包络

    Args:
        audio_path: 音频文件路径
        sample_rate: 采样率（Hz）

    Returns:
        音量数组 [0.0, 1.0]
    """
    analyzer = AudioAnalyzer(sample_rate=sample_rate)
    return analyzer.compute_volume_envelope(audio_path)
