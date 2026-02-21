"""
GLM ASR 实现 - 使用智谱 AI GLM ASR API
"""

from typing import Union, Optional
from pathlib import Path
import wave
import io

from loguru import logger

from ..interface import ASRInterface
from ....config.core.registry import ProviderRegistry
from ....config.providers.asr.glm import GLMASRConfig


@ProviderRegistry.register_service("asr", "glm")
class GLMASR(ASRInterface):
    """
    GLM ASR 实现
    使用智谱 AI 的 GLM ASR API 进行语音识别
    """

    @staticmethod
    def _convert_to_supported_audio_bytes(audio_data, sample_rate: int = 16000) -> tuple[bytes, str]:
        """
        将音频数据转换为 GLM ASR 支持的格式

        GLM ASR 支持的格式: MP3, WAV (需要特定编码), FLAC, M4A, OGG

        Args:
            audio_data: 可以是以下类型之一:
                - numpy array (float32, range [-1.0, 1.0])
                - list of floats
                - bytes (已经是音频格式)
            sample_rate: 采样率，默认 16000

        Returns:
            tuple[bytes, str]: (音频数据, 文件扩展名)
        """
        # 如果已经是 bytes，假设是支持的格式
        if isinstance(audio_data, bytes):
            return audio_data, "mp3"

        # 转换为 numpy array
        try:
            import numpy as np
            if isinstance(audio_data, list):
                audio_np = np.array(audio_data, dtype=np.float32)
            else:
                audio_np = audio_data
        except ImportError:
            logger.error("需要安装 numpy: pip install numpy")
            raise

        # 尝试使用 pydub 转换为 MP3 (更可靠)
        try:
            from pydub import AudioSegment
            import io

            # 将 numpy array 转换为 AudioSegment
            if audio_np.dtype == np.float32 or audio_np.dtype == np.float64:
                audio_np = np.clip(audio_np, -1.0, 1.0)
                int16_data = (audio_np * 32767).astype(np.int16)
            else:
                int16_data = audio_np.astype(np.int16)

            # 创建 AudioSegment
            audio_segment = AudioSegment(
                data=int16_data.tobytes(),
                sample_width=2,  # 16-bit
                frame_rate=sample_rate,
                channels=1  # 单声道
            )

            # 导出为 MP3
            mp3_buffer = io.BytesIO()
            audio_segment.export(mp3_buffer, format="mp3", bitrate="64k")
            mp3_buffer.seek(0)

            logger.debug(f"音频转换为 MP3: {len(mp3_buffer.getvalue())} 字节")
            return mp3_buffer.getvalue(), "mp3"

        except ImportError:
            logger.warning("pydub 未安装，使用 WAV 格式 (pip install pydub)")
            # 降级到 WAV 格式
            import wave

            if audio_np.dtype == np.float32 or audio_np.dtype == np.float64:
                audio_np = np.clip(audio_np, -1.0, 1.0)
                int16_data = (audio_np * 32767).astype(np.int16)
            else:
                int16_data = audio_np.astype(np.int16)

            wav_buffer = io.BytesIO()

            with wave.open(wav_buffer, 'wb') as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(int16_data.tobytes())

            wav_buffer.seek(0)
            return wav_buffer.read(), "wav"

    def __init__(
        self,
        api_key: str,
        model: str = "glm-asr-2512",
        stream: bool = False,
    ):
        """
        初始化 GLM ASR 客户端

        Args:
            api_key: 智谱 AI API Key
            model: ASR 模型，默认为 glm-asr-2512
            stream: 是否使用流式调用
        """
        self.api_key = api_key
        self.model = model
        self.stream = stream
        self._client = None

    def _get_client(self):
        """懒加载客户端"""
        if self._client is None:
            try:
                from zai import ZhipuAiClient
                self._client = ZhipuAiClient(api_key=self.api_key)
                logger.info("GLM ASR 客户端初始化成功")
            except ImportError as e:
                logger.error("未安装 zai-sdk，请运行: pip install zai-sdk")
                raise ImportError(
                    "zai-sdk 未安装，请运行: pip install zai-sdk"
                ) from e
        return self._client

    async def transcribe(
        self,
        audio_data: Union[bytes, str, Path, list],
        stream: Optional[bool] = None,
        **kwargs
    ) -> str:
        """
        将音频数据转录为文本

        Args:
            audio_data: 音频数据，可以是:
                - bytes: 原始音频字节 (支持格式)
                - str/Path: 音频文件路径
                - list/numpy array: PCM 音频数据 (float32, range [-1.0, 1.0])
            stream: 是否使用流式调用（可选，覆盖默认值）
            **kwargs: 额外参数

        Returns:
            str: 识别出的文本
        """
        client = self._get_client()

        # 使用传入参数或默认值
        use_stream = stream if stream is not None else self.stream

        # 处理输入数据，获取音频 bytes 和扩展名
        if isinstance(audio_data, bytes):
            audio_bytes, ext = audio_data, "mp3"
        elif isinstance(audio_data, (str, Path)):
            # 从文件读取
            with open(str(audio_data), 'rb') as f:
                audio_bytes = f.read()
            ext = Path(audio_data).suffix.lstrip('.')
        else:
            # 转换为支持的音频格式
            audio_bytes, ext = self._convert_to_supported_audio_bytes(audio_data)

        logger.debug(f"GLM ASR 处理音频数据: {len(audio_bytes)} 字节, 格式: {ext} (stream={use_stream})")

        try:
            if use_stream:
                result = await self._transcribe_stream(client, audio_bytes, ext)
            else:
                result = await self._transcribe_sync(client, audio_bytes, ext)

            logger.info(f"GLM ASR 识别结果: {result}")
            return result

        finally:
            pass  # bytes 不需要清理

    async def _transcribe_sync(self, client, audio_bytes: bytes, ext: str = "mp3") -> str:
        """非流式识别"""
        import asyncio
        import io

        loop = asyncio.get_event_loop()

        def _call_api():
            # 创建命名 BytesIO，添加 name 属性
            class NamedBytesIO(io.BytesIO):
                def __init__(self, data, name):
                    super().__init__(data)
                    self.name = name

            audio_file = NamedBytesIO(audio_bytes, f"audio.{ext}")

            response = client.audio.transcriptions.create(
                model=self.model,
                file=audio_file
            )
            return response

        response = await loop.run_in_executor(None, _call_api)

        # 提取文本结果
        if hasattr(response, 'text'):
            return response.text
        elif isinstance(response, dict):
            return response.get('text', '')
        else:
            return str(response)

    async def _transcribe_stream(self, client, audio_bytes: bytes, ext: str = "mp3") -> str:
        """流式识别"""
        import asyncio
        import io

        loop = asyncio.get_event_loop()

        def _call_api():
            # 创建命名 BytesIO，添加 name 属性
            class NamedBytesIO(io.BytesIO):
                def __init__(self, data, name):
                    super().__init__(data)
                    self.name = name

            audio_file = NamedBytesIO(audio_bytes, f"audio.{ext}")

            response = client.audio.transcriptions.create(
                model=self.model,
                file=audio_file
            )
            return response

        response = await loop.run_in_executor(None, _call_api)

        # 收集所有文本（如果是流式响应）
        full_text = []

        # 检查是否是可迭代的流式响应
        if hasattr(response, '__iter__') and not isinstance(response, (str, bytes, dict)):
            for chunk in response:
                if hasattr(chunk, 'text'):
                    full_text.append(chunk.text)
                elif isinstance(chunk, dict):
                    text = chunk.get('text', '')
                    if text:
                        full_text.append(text)
                elif hasattr(chunk, 'choices'):
                    for choice in chunk.choices:
                        if hasattr(choice, 'delta') and hasattr(choice.delta, 'content'):
                            content = choice.delta.content
                            if content:
                                full_text.append(content)
        else:
            # 非流式响应，直接提取文本
            if hasattr(response, 'text'):
                return response.text
            elif isinstance(response, dict):
                return response.get('text', '')
            else:
                return str(response)

        return ''.join(full_text)

    async def transcribe_stream(
        self,
        audio_data: Union[bytes, str, Path, list],
        **kwargs
    ):
        """
        流式识别音频，生成器返回文本块

        Args:
            audio_data: 音频数据

        Yields:
            str: 识别的文本块
        """
        import asyncio
        import io

        client = self._get_client()

        # 处理输入数据，获取音频 bytes 和扩展名
        if isinstance(audio_data, bytes):
            audio_bytes, ext = audio_data, "mp3"
        elif isinstance(audio_data, (str, Path)):
            with open(str(audio_data), 'rb') as f:
                audio_bytes = f.read()
            ext = Path(audio_data).suffix.lstrip('.')
        else:
            audio_bytes, ext = self._convert_to_supported_audio_bytes(audio_data)

        loop = asyncio.get_event_loop()

        def _call_api():
            # 创建命名 BytesIO，添加 name 属性
            class NamedBytesIO(io.BytesIO):
                def __init__(self, data, name):
                    super().__init__(data)
                    self.name = name

            audio_file = NamedBytesIO(audio_bytes, f"audio.{ext}")

            response = client.audio.transcriptions.create(
                model=self.model,
                file=audio_file
            )
            return response

        response = await loop.run_in_executor(None, _call_api)

        for chunk in response:
            text = None
            if hasattr(chunk, 'text'):
                text = chunk.text
            elif isinstance(chunk, dict):
                text = chunk.get('text', '')
            elif hasattr(chunk, 'choices'):
                for choice in chunk.choices:
                    if hasattr(choice, 'delta') and hasattr(choice.delta, 'content'):
                        text = choice.delta.content

            if text:
                yield text

    async def close(self) -> None:
        """清理资源"""
        self._client = None
        logger.debug("GLM ASR 客户端已关闭")