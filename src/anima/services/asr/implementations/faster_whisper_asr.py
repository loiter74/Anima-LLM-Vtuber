"""
Faster-Whisper ASR 实现 - 开源免费的语音识别
基于 faster-whisper 项目：https://github.com/guillaumekln/faster-whisper

支持多种模型：
- tiny: 最快，准确率较低
- base: 平衡速度和准确率
- small: 较快，准确率中等
- medium: 较慢，准确率高
- large-v2: 最慢，准确率最高（推荐中文）
- large-v3: 最新版本

支持中文模型：
- distil-large-v3: 推荐，速度快且准确
- distil-medium.en: 英文专用
"""

from typing import Union, Optional
from pathlib import Path
import numpy as np
from loguru import logger

from ..interface import ASRInterface
from ....config.core.registry import ProviderRegistry


@ProviderRegistry.register_service("asr", "faster_whisper")
class FasterWhisperASR(ASRInterface):
    """
    Faster-Whisper ASR 实现
    使用 OpenAI Whisper 模型的优化版本，速度快且完全离线运行
    """

    # 支持的模型列表
    MODELS = {
        "tiny": "tiny",
        "base": "base",
        "small": "small",
        "medium": "medium",
        "large-v2": "large-v2",
        "large-v3": "large-v3",
        "distil-small.en": "distil-small.en",
        "distil-medium.en": "distil-medium.en",
        "distil-large-v3": "distil-large-v3",  # 推荐：支持多语言，速度快
        "systran/faster-whisper-large-v3": "systran/faster-whisper-large-v3",
    }

    def __init__(
        self,
        model: str = "distil-large-v3",
        language: str = "zh",  # 默认中文
        device: str = "auto",  # auto, cpu, cuda
        compute_type: str = "default",  # default, int8, float16, float32
        download_root: Optional[str] = None,
        beam_size: int = 5,
        vad_filter: bool = True,
        vad_parameters: dict = None,
    ):
        """
        初始化 Faster-Whisper ASR

        Args:
            model: 模型名称或路径（默认 distil-large-v3）
            language: 语言代码（zh=中文, en=英文, ja=日语, etc.）
            device: 运行设备（auto=自动检测, cpu=CPU, cuda=CUDA）
            compute_type: 计算精度（default=自动, int8=量化, float16=半精度）
            download_root: 模型下载目录
            beam_size: 束搜索大小（1-10，越大越准确但越慢）
            vad_filter: 是否使用 VAD 过滤静音
            vad_parameters: VAD 参数
        """
        self.model_name = model
        self.language = language
        self.device = device
        self.compute_type = compute_type
        self.download_root = download_root
        self.beam_size = beam_size
        self.vad_filter = vad_filter
        self.vad_parameters = vad_parameters or {}
        self._model = None

        logger.info(f"Faster-Whisper ASR 初始化配置:")
        logger.info(f"  模型: {model}")
        logger.info(f"  语言: {language}")
        logger.info(f"  设备: {device}")
        logger.info(f"  计算精度: {compute_type}")
        logger.info(f"  Beam Size: {beam_size}")
        logger.info(f"  VAD 过滤: {vad_filter}")

    def _get_model(self):
        """懒加载模型"""
        if self._model is None:
            try:
                from faster_whisper import WhisperModel

                logger.info(f"正在加载 Faster-Whisper 模型: {self.model_name}...")
                self._model = WhisperModel(
                    self.model_name,
                    device=self.device,
                    compute_type=self.compute_type,
                    download_root=self.download_root,
                )
                logger.info(f"✅ Faster-Whisper 模型加载完成")

            except ImportError:
                logger.error("faster-whisper 未安装，请运行: pip install faster-whisper")
                raise ImportError(
                    "faster-whisper 未安装，请运行: pip install faster-whisper"
                )
            except Exception as e:
                logger.error(f"加载 Faster-Whisper 模型失败: {e}")
                raise

        return self._model

    async def transcribe(
        self,
        audio_data: Union[bytes, str, Path, list, np.ndarray],
        **kwargs
    ) -> str:
        """
        将音频数据转录为文本

        Args:
            audio_data: 音频数据，可以是:
                - bytes: WAV/MP3 等格式的字节数据
                - str/Path: 音频文件路径
                - list/numpy array: PCM 音频数据 (float32, range [-1.0, 1.0])

        Returns:
            str: 识别出的文本
        """
        import asyncio
        import wave
        import io
        import tempfile

        model = self._get_model()

        # 处理输入数据，转换为 numpy array
        if isinstance(audio_data, np.ndarray):
            audio_np = audio_data
        elif isinstance(audio_data, list):
            audio_np = np.array(audio_data, dtype=np.float32)
        elif isinstance(audio_data, (str, Path)):
            # 从文件读取并解码
            audio_np = await self._load_audio_file(str(audio_data))
        elif isinstance(audio_data, bytes):
            # 从 bytes 解码音频
            audio_np = await self._load_audio_bytes(audio_data)
        else:
            raise ValueError(f"不支持的音频数据类型: {type(audio_data)}")

        # 确保是 float32 格式
        if audio_np.dtype != np.float32:
            audio_np = audio_np.astype(np.float32)

        # 限制范围到 [-1.0, 1.0]
        audio_np = np.clip(audio_np, -1.0, 1.0)

        logger.debug(f"Faster-Whisper ASR 处理音频: {len(audio_np)} 采样点")

        # 在线程池中运行转录（CPU 密集型操作）
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            self._transcribe_sync,
            audio_np
        )

        logger.info(f"Faster-Whisper ASR 识别结果: {result}")
        return result

    def _transcribe_sync(self, audio_np: np.ndarray) -> str:
        """同步转录方法"""
        model = self._get_model()

        # 配置参数
        parameters = {
            "beam_size": self.beam_size,
            "language": self.language if self.language else None,
            "condition_on_previous_text": False,
            "vad_filter": self.vad_filter,
        }

        # 添加 VAD 参数
        if self.vad_filter:
            parameters.update({
                "vad_parameters": {
                    "min_silence_duration_ms": self.vad_parameters.get("min_silence_duration_ms", 500),
                    "speech_pad_ms": self.vad_parameters.get("speech_pad_ms", 30),
                }
            })

        # 记录语言配置
        logger.debug(f"Faster-Whisper 配置 - language={self.language}, 参数={parameters}")

        # 执行转录
        segments, info = model.transcribe(audio_np, **parameters)

        # 记录检测到的语言信息
        logger.info(f"Faster-Whisper 检测信息: language='{info.language}', language_probability={info.language_probability:.2f}")

        # 提取文本
        text_parts = [segment.text for segment in segments]

        if not text_parts:
            return ""
        else:
            return "".join(text_parts).strip()

    async def _load_audio_file(self, file_path: str) -> np.ndarray:
        """从文件加载音频"""
        # 使用 pydub 加载音频（支持多种格式）
        try:
            from pydub import AudioSegment

            audio_segment = AudioSegment.from_file(file_path)
            samples = np.array(audio_segment.get_array_of_samples(), dtype=np.float32)

            # 归一化到 [-1.0, 1.0]
            if audio_segment.sample_width == 2:  # 16-bit
                samples = samples / 32768.0
            elif audio_segment.sample_width == 4:  # 32-bit
                samples = samples / 2147483648.0

            # 转换为单声道
            if audio_segment.channels > 1:
                samples = samples.reshape((-1, audio_segment.channels)).mean(axis=1)

            # 重采样到 16kHz（如果需要）
            if audio_segment.frame_rate != 16000:
                from pydub.utils import make_chunks
                # 简单重采样方法（可以使用 librosa 或 resampy 获得更好效果）
                import fractions
                ratio = 16000 / audio_segment.frame_rate
                target_length = int(len(samples) * ratio)
                samples = np.interp(
                    np.linspace(0, len(samples), target_length),
                    np.arange(len(samples)),
                    samples
                )

            logger.debug(f"加载音频文件: {file_path}, 采样点: {len(samples)}")
            return samples

        except ImportError:
            logger.warning("pydub 未安装，使用 wave 模块（仅支持 WAV）")
            # 降级到 wave 模块
            import wave

            with wave.open(file_path, 'rb') as wf:
                sample_rate = wf.getframerate()
                frames = wf.readframes(wf.getnframes())
                audio_data = np.frombuffer(frames, dtype=np.int16)

                # 归一化并转 float32
                samples = audio_data.astype(np.float32) / 32768.0

                # 重采样到 16kHz
                if sample_rate != 16000:
                    ratio = 16000 / sample_rate
                    target_length = int(len(samples) * ratio)
                    samples = np.interp(
                        np.linspace(0, len(samples), target_length),
                        np.arange(len(samples)),
                        samples
                    )

                return samples

    async def _load_audio_bytes(self, audio_bytes: bytes) -> np.ndarray:
        """从 bytes 加载音频"""
        import tempfile

        # 写入临时文件
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_file:
            tmp_file.write(audio_bytes)
            tmp_file.flush()

            try:
                return await self._load_audio_file(tmp_file.name)
            finally:
                import os
                if os.path.exists(tmp_file.name):
                    os.unlink(tmp_file.name)

    async def transcribe_stream(
        self,
        audio_data: Union[bytes, str, Path, list, np.ndarray],
        **kwargs
    ):
        """
        流式识别音频，生成器返回文本块

        Args:
            audio_data: 音频数据

        Yields:
            str: 识别的文本块
        """
        # Faster-Whisper 不支持真正的流式，但我们可以模拟
        result = await self.transcribe(audio_data, **kwargs)

        # 按句子分割返回
        import re
        sentences = re.split(r'[。！？.!?]', result)

        for sentence in sentences:
            sentence = sentence.strip()
            if sentence:
                yield sentence

    async def close(self) -> None:
        """清理资源"""
        self._model = None
        logger.debug("Faster-Whisper ASR 资源已释放")

    @classmethod
    def from_config(cls, config, **kwargs):
        """从配置创建实例"""
        return cls(
            model=config.get("model", "distil-large-v3"),
            language=config.get("language", "zh"),
            device=config.get("device", "auto"),
            compute_type=config.get("compute_type", "default"),
            download_root=config.get("download_root"),
            beam_size=config.get("beam_size", 5),
            vad_filter=config.get("vad_filter", True),
            vad_parameters=config.get("vad_parameters", {}),
        )
