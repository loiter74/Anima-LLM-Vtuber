"""
GLM TTS 实现 - 使用智谱 AI GLM TTS API
"""

from typing import Union, Optional
from pathlib import Path
import tempfile
import os

from loguru import logger

from ..interface import TTSInterface


class GLMTTS(TTSInterface):
    """
    GLM TTS 实现
    使用智谱 AI 的 GLM TTS API 进行语音合成
    """

    def __init__(
        self,
        api_key: str,
        model: str = "glm-tts",
        voice: str = "female",
        response_format: str = "wav",
        speed: float = 1.0,
        volume: float = 1.0,
    ):
        """
        初始化 GLM TTS 客户端

        Args:
            api_key: 智谱 AI API Key
            model: TTS 模型，默认为 glm-tts
            voice: 音色，可选 male/female
            response_format: 输出格式，支持 wav/mp3/pcm
            speed: 语速，范围 0.5-2.0
            volume: 音量，范围 0.5-2.0
        """
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.response_format = response_format
        self.speed = speed
        self.volume = volume
        self._client = None

    def _get_client(self):
        """懒加载客户端"""
        if self._client is None:
            try:
                from zai import ZhipuAiClient
                self._client = ZhipuAiClient(api_key=self.api_key)
                logger.info("GLM TTS 客户端初始化成功")
            except ImportError as e:
                logger.error("未安装 zai-sdk，请运行: pip install zai-sdk")
                raise ImportError(
                    "zai-sdk 未安装，请运行: pip install zai-sdk"
                ) from e
        return self._client

    async def synthesize(
        self,
        text: str,
        output_path: Optional[Union[str, Path]] = None,
        voice: Optional[str] = None,
        speed: Optional[float] = None,
        volume: Optional[float] = None,
        response_format: Optional[str] = None,
        stream: bool = False,
        **kwargs
    ) -> Union[bytes, str]:
        """
        将文本合成为语音

        Args:
            text: 要合成的文本
            output_path: 输出文件路径（可选）
            voice: 音色（可选，覆盖默认值）
            speed: 语速（可选，覆盖默认值）
            volume: 音量（可选，覆盖默认值）
            response_format: 输出格式（可选，覆盖默认值）
            stream: 是否使用流式调用
            **kwargs: 额外参数

        Returns:
            Union[bytes, str]: 如果指定了 output_path，返回文件路径字符串
                               否则返回音频字节数据
        """
        client = self._get_client()
        
        # 使用传入参数或默认值
        actual_voice = voice or self.voice
        actual_speed = speed if speed is not None else self.speed
        actual_volume = volume if volume is not None else self.volume
        actual_format = response_format or self.response_format

        logger.debug(f"GLM TTS 合成文本: {text[:50]}... (voice={actual_voice}, format={actual_format})")

        try:
            if stream:
                # 流式调用
                return await self._synthesize_stream(
                    client, text, output_path, actual_voice, actual_format, actual_speed, actual_volume
                )
            else:
                # 非流式调用
                return await self._synthesize_sync(
                    client, text, output_path, actual_voice, actual_format, actual_speed, actual_volume
                )
        except Exception as e:
            logger.error(f"GLM TTS 合成失败: {e}")
            raise

    async def _synthesize_sync(
        self,
        client,
        text: str,
        output_path: Optional[Union[str, Path]],
        voice: str,
        response_format: str,
        speed: float,
        volume: float
    ) -> Union[bytes, str]:
        """非流式合成"""
        import asyncio
        
        # 在线程池中执行同步调用
        loop = asyncio.get_event_loop()
        
        def _call_api():
            response = client.audio.speech(
                model=self.model,
                input=text,
                voice=voice,
                response_format=response_format,
                speed=speed,
                volume=volume
            )
            return response

        response = await loop.run_in_executor(None, _call_api)

        if output_path:
            # 保存到文件
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            response.stream_to_file(str(output_path))
            logger.info(f"GLM TTS 音频已保存到: {output_path}")
            return str(output_path)
        else:
            # 返回字节数据
            import io
            buffer = io.BytesIO()
            for chunk in response.iter_bytes():
                buffer.write(chunk)
            audio_data = buffer.getvalue()
            logger.debug(f"GLM TTS 返回音频数据: {len(audio_data)} bytes")
            return audio_data

    async def _synthesize_stream(
        self,
        client,
        text: str,
        output_path: Optional[Union[str, Path]],
        voice: str,
        response_format: str,
        speed: float,
        volume: float
    ) -> Union[bytes, str]:
        """流式合成"""
        import asyncio
        import base64
        import io
        
        loop = asyncio.get_event_loop()
        
        def _call_api():
            response = client.audio.speech(
                model=self.model,
                input=text,
                voice=voice,
                stream=True,
                response_format='pcm',
                encode_format='base64',
                speed=speed,
                volume=volume
            )
            return response

        response = await loop.run_in_executor(None, _call_api)

        # 收集所有音频数据
        audio_chunks = []
        
        for chunk in response:
            for choice in chunk.choices:
                is_finished = choice.finish_reason
                if is_finished == "stop":
                    break
                audio_delta = choice.delta.content
                if audio_delta:
                    # 解码 base64 数据
                    audio_data = base64.b64decode(audio_delta)
                    audio_chunks.append(audio_data)

        # 合并所有音频数据
        all_audio = b''.join(audio_chunks)
        
        if output_path:
            # 保存到文件
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'wb') as f:
                f.write(all_audio)
            logger.info(f"GLM TTS 流式音频已保存到: {output_path}")
            return str(output_path)
        else:
            logger.debug(f"GLM TTS 流式返回音频数据: {len(all_audio)} bytes")
            return all_audio

    async def synthesize_stream(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: Optional[float] = None,
        volume: Optional[float] = None,
        **kwargs
    ):
        """
        流式合成语音，生成器返回音频块

        Args:
            text: 要合成的文本
            voice: 音色
            speed: 语速
            volume: 音量

        Yields:
            bytes: 音频数据块
        """
        import base64
        import asyncio
        
        client = self._get_client()
        
        actual_voice = voice or self.voice
        actual_speed = speed if speed is not None else self.speed
        actual_volume = volume if volume is not None else self.volume

        loop = asyncio.get_event_loop()
        
        def _call_api():
            response = client.audio.speech(
                model=self.model,
                input=text,
                voice=actual_voice,
                stream=True,
                response_format='pcm',
                encode_format='base64',
                speed=actual_speed,
                volume=actual_volume
            )
            return response

        response = await loop.run_in_executor(None, _call_api)

        for chunk in response:
            for choice in chunk.choices:
                is_finished = choice.finish_reason
                if is_finished == "stop":
                    return
                audio_delta = choice.delta.content
                if audio_delta:
                    # 解码 base64 数据并 yield
                    audio_data = base64.b64decode(audio_delta)
                    yield audio_data

    async def close(self) -> None:
        """清理资源"""
        self._client = None
        logger.debug("GLM TTS 客户端已关闭")