"""
本地文件采集器
Local File Collector

从本地文件导入对话数据
"""

from pathlib import Path
from typing import List, Dict, Union
import json
from loguru import logger

from .base import BaseCollector


class LocalFileCollector(BaseCollector):
    """
    本地文件采集器

    支持的格式：
    - JSON (.json)
    - JSON Lines (.jsonl)
    """

    def __init__(self):
        super().__init__("LocalFileCollector")

    def collect(
        self,
        file_paths: List[str] = None,
        directory: str = None,
        pattern: str = "*.json"
    ) -> List[Dict]:
        """
        从本地文件采集数据

        Args:
            file_paths: 文件路径列表
            directory: 目录路径（与 file_paths 二选一）
            pattern: 文件匹配模式（当使用 directory 时）

        Returns:
            采集到的数据列表
        """
        # 收集文件路径
        files_to_process = []

        if file_paths:
            files_to_process = [Path(f) for f in file_paths]
        elif directory:
            dir_path = Path(directory)
            if not dir_path.exists():
                logger.error(f"[{self.name}] 目录不存在: {directory}")
                return []

            files_to_process = list(dir_path.rglob(pattern))
        else:
            logger.error(f"[{self.name}] 必须提供 file_paths 或 directory")
            return []

        # 处理文件
        all_data = []

        for file_path in files_to_process:
            try:
                data = self._read_file(file_path)
                if isinstance(data, list):
                    all_data.extend(data)
                else:
                    all_data.append(data)

                logger.info(f"[{self.name}] 读取文件: {file_path}")
            except Exception as e:
                logger.error(f"[{self.name}] 读取失败: {file_path}, 错误: {e}")
                self.error_count += 1

        return all_data

    def _read_file(self, file_path: Path) -> Union[Dict, List[Dict]]:
        """
        读取单个文件

        Args:
            file_path: 文件路径

        Returns:
            数据或数据列表
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            if file_path.suffix == '.jsonl':
                # JSON Lines 格式
                data = []
                for line in f:
                    line = line.strip()
                    if line:
                        data.append(json.loads(line))
                return data
            else:
                # JSON 格式
                return json.load(f)
