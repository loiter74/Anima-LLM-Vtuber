"""
数据采集器基类
Data Collector Base Class
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from loguru import logger


class BaseCollector(ABC):
    """
    数据采集器基类

    所有采集器都必须继承此类并实现 collect 方法
    """

    def __init__(self, name: str):
        """
        初始化采集器

        Args:
            name: 采集器名称
        """
        self.name = name
        self.collected_count = 0
        self.error_count = 0

    @abstractmethod
    def collect(self, **kwargs) -> List[Dict]:
        """
        采集数据

        Args:
            **kwargs: 采集参数

        Returns:
            采集到的对话数据列表
        """
        pass

    def validate_data(self, data: Dict) -> bool:
        """
        验证数据格式

        Args:
            data: 待验证的数据

        Returns:
            是否有效
        """
        required_fields = ["conversation"]

        for field in required_fields:
            if field not in data:
                logger.warning(f"[{self.name}] 数据缺少字段: {field}")
                return False

        # 验证对话格式
        if not isinstance(data["conversation"], list):
            logger.warning(f"[{self.name}] conversation 必须是列表")
            return False

        for turn in data["conversation"]:
            if "role" not in turn or "content" not in turn:
                logger.warning(f"[{self.name}] 对话轮次缺少必要字段")
                return False

            if turn["role"] not in ["user", "assistant", "system"]:
                logger.warning(f"[{self.name}] 无效的角色: {turn['role']}")
                return False

        return True

    def normalize_data(self, raw_data: Dict) -> Dict:
        """
        标准化数据格式

        Args:
            raw_data: 原始数据

        Returns:
            标准化后的数据
        """
        normalized = {
            "conversation": raw_data.get("conversation", []),
            "metadata": raw_data.get("metadata", {})
        }

        # 添加元数据
        normalized["metadata"]["collector"] = self.name
        normalized["metadata"]["collected_at"] = None  # 将在添加时设置

        return normalized

    def collect_and_validate(self, **kwargs) -> List[Dict]:
        """
        采集并验证数据

        Args:
            **kwargs: 采集参数

        Returns:
            有效数据列表
        """
        raw_data_list = self.collect(**kwargs)
        valid_data_list = []

        for raw_data in raw_data_list:
            # 标准化
            normalized = self.normalize_data(raw_data)

            # 验证
            if self.validate_data(normalized):
                valid_data_list.append(normalized)
                self.collected_count += 1
            else:
                self.error_count += 1

        logger.info(
            f"[{self.name}] 采集完成: "
            f"有效={self.collected_count}, "
            f"无效={self.error_count}"
        )

        return valid_data_list
