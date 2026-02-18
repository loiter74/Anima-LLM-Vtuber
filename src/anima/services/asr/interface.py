"""
ASR (语音识别) 接口定义
"""

from abc import ABC, abstractmethod
from typing import Union
from pathlib import Path


class ASRInterface(ABC):
    """
    语音识别接口的抽象基类
    所有 ASR 实现都必须继承此类并实现其抽象方法
    """

    @abstractmethod
    async def transcribe(
        self, 
        audio_data: Union[bytes, str, Path],
        **kwargs
    ) -> str:
        """
        将音频数据转录为文本

        Args:
            audio_data: 音频数据，可以是:
                - bytes: 原始音频字节
                - str/Path: 音频文件路径
            **kwargs: 额外参数

        Returns:
            str: 识别出的文本
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """清理资源"""
        pass