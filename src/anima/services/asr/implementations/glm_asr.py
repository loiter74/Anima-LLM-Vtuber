"""
GLM ASR 实现 - 使用智谱 AI GLM ASR API
"""

from typing import Union, Optional
from pathlib import Path
import tempfile
import os

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
        audio_data: Union[bytes, str, Path],
        stream: Optional[bool] = None,
        **kwargs
    ) -> str:
        """
        将音频数据转录为文本

        Args:
            audio_data: 音频数据，可以是:
                - bytes: 原始音频字节
                - str/Path: 音频文件路径
            stream: 是否使用流式调用（可选，覆盖默认值）
            **kwargs: 额外参数

        Returns:
            str: 识别出的文本
        """
        client = self._get_client()
        
        # 使用传入参数或默认值
        use_stream = stream if stream is not None else self.stream

        # 处理输入数据
        file_path = None
        temp_file = None
        
        if isinstance(audio_data, bytes):
            # 如果是字节数据，写入临时文件
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
            temp_file.write(audio_data)
            temp_file.close()
            file_path = temp_file.name
        else:
            # 如果是文件路径
            file_path = str(audio_data)

        logger.debug(f"GLM ASR 处理音频文件: {file_path} (stream={use_stream})")

        try:
            if use_stream:
                result = await self._transcribe_stream(client, file_path)
            else:
                result = await self._transcribe_sync(client, file_path)
            
            logger.info(f"GLM ASR 识别结果: {result}")
            return result
            
        finally:
            # 清理临时文件
            if temp_file and os.path.exists(temp_file.name):
                os.unlink(temp_file.name)

    async def _transcribe_sync(self, client, file_path: str) -> str:
        """非流式识别"""
        import asyncio
        
        loop = asyncio.get_event_loop()
        
        def _call_api():
            response = client.audio.transcriptions(
                model=self.model,
                file=file_path,
                stream=False
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

    async def _transcribe_stream(self, client, file_path: str) -> str:
        """流式识别"""
        import asyncio
        
        loop = asyncio.get_event_loop()
        
        def _call_api():
            response = client.audio.transcriptions(
                model=self.model,
                file=file_path,
                stream=True
            )
            return response

        response = await loop.run_in_executor(None, _call_api)
        
        # 收集所有文本
        full_text = []
        
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
        
        return ''.join(full_text)

    async def transcribe_stream(
        self,
        audio_data: Union[bytes, str, Path],
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
        
        client = self._get_client()
        
        # 处理输入数据
        file_path = None
        temp_file = None
        
        if isinstance(audio_data, bytes):
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
            temp_file.write(audio_data)
            temp_file.close()
            file_path = temp_file.name
        else:
            file_path = str(audio_data)

        try:
            loop = asyncio.get_event_loop()
            
            def _call_api():
                response = client.audio.transcriptions(
                    model=self.model,
                    file=file_path,
                    stream=True
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
                    
        finally:
            if temp_file and os.path.exists(temp_file.name):
                os.unlink(temp_file.name)

    async def close(self) -> None:
        """清理资源"""
        self._client = None
        logger.debug("GLM ASR 客户端已关闭")