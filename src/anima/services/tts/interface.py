"""
TTS (语音合成) 接口定义
"""

from abc import ABC, abstractmethod
from typing import Union, Optional
from pathlib import Path


class TTSInterface(ABC):
    """
    语音合成接口的抽象基类
    所有 TTS 实现都必须继承此类并实现其抽象方法
    """

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        output_path: Optional[Union[str, Path]] = None,
        **kwargs
    ) -> Union[bytes, str]:
        """
        将文本合成为语音

        Args:
            text: 要合成的文本
            output_path: 输出文件路径（可选）
            **kwargs: 额外参数

        Returns:
            Union[bytes, str]: 如果指定了 output_path，返回文件路径字符串
                               否则返回音频字节数据
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """清理资源"""
        pass