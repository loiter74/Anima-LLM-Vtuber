"""
数据集管理系统
Dataset Management System

提供完整的数据集管理功能：
- 数据采集、清洗、去重
- 质量评分和过滤
- 训练/验证/测试集划分
- 统计和搜索
"""

from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import json
import hashlib
from loguru import logger


class DatasetManager:
    """
    数据集管理器

    功能：
    1. 数据添加和导入
    2. 数据清洗和去重
    3. 质量评分和过滤
    4. 数据集划分（train/val/test）
    5. 统计和搜索
    """

    def __init__(self, base_path: str = "datasets"):
        """
        初始化数据集管理器

        Args:
            base_path: 数据集根目录
        """
        self.base_path = Path(base_path)
        self.raw_path = self.base_path / "raw"
        self.processed_path = self.base_path / "processed"
        self.metadata_path = self.base_path / "metadata"

        # 创建目录
        for path in [self.raw_path, self.processed_path, self.metadata_path]:
            path.mkdir(parents=True, exist_ok=True)

        # 元数据文件
        self.stats_file = self.metadata_path / "data_stats.json"
        self.scores_file = self.metadata_path / "quality_scores.json"
        self.categories_file = self.metadata_path / "categories.json"

        # 加载元数据
        self.stats = self._load_json(self.stats_file, {})
        self.quality_scores = self._load_json(self.scores_file, {})
        self.categories = self._load_json(self.categories_file, {})

        logger.info(f"[DatasetManager] 初始化完成，路径: {self.base_path}")

    def _load_json(self, path: Path, default: dict) -> dict:
        """加载 JSON 文件"""
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return default

    def _save_json(self, path: Path, data: dict):
        """保存 JSON 文件"""
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def add_data(
        self,
        source: str,
        data: List[Dict],
        category: str,
        sub_category: str = None
    ) -> int:
        """
        添加新数据

        Args:
            source: 数据源标识
            data: 对话数据列表
            category: 主分类
            sub_category: 子分类（可选）

        Returns:
            添加的数据条数
        """
        count = 0

        # 按分类保存
        category_path = self.raw_path / category
        if sub_category:
            category_path = category_path / sub_category
        category_path.mkdir(parents=True, exist_ok=True)

        # 保存每条数据
        for item in data:
            # 生成唯一ID
            content = json.dumps(item, sort_keys=True)
            item_id = hashlib.md5(content.encode()).hexdigest()

            # 添加元数据
            item["id"] = f"{source}_{item_id}"
            item["source"] = source
            item["category"] = category
            if sub_category:
                item["sub_category"] = sub_category
            item["added_at"] = datetime.now().isoformat()

            # 保存到文件
            file_path = category_path / f"{item['id']}.json"
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(item, f, ensure_ascii=False, indent=2)

            count += 1

        # 更新统计
        self._update_stats(category, sub_category, count)

        logger.info(f"[DatasetManager] 添加了 {count} 条数据到 {category}/{sub_category or 'N/A'}")

        return count

    def _update_stats(self, category: str, sub_category: str, count: int):
        """更新数据统计"""
        key = f"{category}/{sub_category}" if sub_category else category

        if key not in self.stats:
            self.stats[key] = {
                "category": category,
                "sub_category": sub_category,
                "total_count": 0,
                "last_updated": None
            }

        self.stats[key]["total_count"] += count
        self.stats[key]["last_updated"] = datetime.now().isoformat()

        self._save_json(self.stats_file, self.stats)

    def quality_score(self, text: str) -> float:
        """
        计算文本质量分数

        评分维度：
        1. 长度（50-500字符为最佳）
        2. 多样性（包含标点、表情等）
        3. 完整性（有开头和结尾）
        4. 清洁度（无重复字符、无乱码）

        Args:
            text: 待评分文本

        Returns:
            质量分数（0.0-1.0）
        """
        score = 1.0

        # 1. 长度检查
        length = len(text)
        if length < 10:
            score *= 0.3
        elif length < 30:
            score *= 0.6
        elif 30 <= length <= 500:
            score *= 1.0
        elif length > 1000:
            score *= 0.7

        # 2. 多样性检查
        has_punctuation = any(c in text for c in ['。', '！', '？', '.', '!', '?'])
        has_emoji = any(ord(c) > 127 for c in text)
        if has_punctuation:
            score *= 1.1
        if has_emoji:
            score *= 1.05

        # 3. 完整性检查
        if not text.strip()[0].isupper() and not text.strip()[0].isalpha():
            score *= 0.9
        if not text.strip()[-1] in ['。', '！', '？', '.', '!', '?', '~']:
            score *= 0.9

        # 4. 清洁度检查
        # 检查重复字符
        if len(set(text)) / len(text) < 0.3:
            score *= 0.5

        # 限制在 0-1 之间
        return min(max(score, 0.0), 1.0)

    def get_statistics(self) -> Dict:
        """
        获取数据统计信息

        Returns:
            统计信息字典
        """
        total_count = sum(item["total_count"] for item in self.stats.values())

        return {
            "total_categories": len(self.stats),
            "total_items": total_count,
            "categories": self.stats,
            "last_updated": datetime.now().isoformat()
        }

    def search(
        self,
        query: str,
        category: str = None,
        limit: int = 10
    ) -> List[Dict]:
        """
        搜索数据

        Args:
            query: 搜索关键词
            category: 分类过滤（可选）
            limit: 返回数量限制

        Returns:
            匹配的数据列表
        """
        results = []

        # 遍历原始数据
        for category_path in self.raw_path.iterdir():
            if category and category_path.name != category:
                continue

            for item_file in category_path.rglob("*.json"):
                try:
                    with open(item_file, 'r', encoding='utf-8') as f:
                        item = json.load(f)

                    # 简单的关键词匹配
                    content = json.dumps(item, ensure_ascii=False).lower()
                    if query.lower() in content:
                        results.append(item)
                        if len(results) >= limit:
                            return results
                except Exception as e:
                    logger.warning(f"[DatasetManager] 搜索失败: {item_file}, 错误: {e}")

        return results

    def export_for_training(
        self,
        output_format: str = "jsonl",
        train_ratio: float = 0.8,
        val_ratio: float = 0.1,
        test_ratio: float = 0.1
    ) -> Dict[str, str]:
        """
        导出训练数据

        Args:
            output_format: 输出格式（jsonl）
            train_ratio: 训练集比例
            val_ratio: 验证集比例
            test_ratio: 测试集比例

        Returns:
            导出文件路径字典
        """
        assert abs(train_ratio + val_ratio + test_ratio - 1.0) < 1e-6, \
            "比例之和必须等于 1.0"

        # 收集所有数据
        all_data = []
        for category_path in self.raw_path.rglob("*.json"):
            try:
                with open(category_path, 'r', encoding='utf-8') as f:
                    item = json.load(f)
                    all_data.append(item)
            except Exception as e:
                logger.warning(f"[DatasetManager] 读取失败: {category_path}, 错误: {e}")

        logger.info(f"[DatasetManager] 收集到 {len(all_data)} 条数据")

        # 随机打乱
        import random
        random.shuffle(all_data)

        # 划分数据集
        total = len(all_data)
        train_end = int(total * train_ratio)
        val_end = train_end + int(total * val_ratio)

        train_data = all_data[:train_end]
        val_data = all_data[train_end:val_end]
        test_data = all_data[val_end:]

        # 导出函数
        def export_jsonl(data, path):
            with open(path, 'w', encoding='utf-8') as f:
                for item in data:
                    f.write(json.dumps(item, ensure_ascii=False) + '\n')

        # 导出文件
        train_file = self.processed_path / "train.jsonl"
        val_file = self.processed_path / "validation.jsonl"
        test_file = self.processed_path / "test.jsonl"

        export_jsonl(train_data, train_file)
        export_jsonl(val_data, val_file)
        export_jsonl(test_data, test_file)

        logger.info(f"[DatasetManager] 导出完成: train={len(train_data)}, val={len(val_data)}, test={len(test_data)}")

        return {
            "train": str(train_file),
            "validation": str(val_file),
            "test": str(test_file)
        }

    def clean_and_deduplicate(self) -> int:
        """
        清洗和去重数据

        Returns:
            移除的重复数据数量
        """
        seen_hashes = set()
        duplicates_removed = 0

        for category_path in self.raw_path.rglob("*.json"):
            try:
                with open(category_path, 'r', encoding='utf-8') as f:
                    item = json.load(f)

                # 计算哈希
                content = json.dumps(item, sort_keys=True)
                content_hash = hashlib.md5(content.encode()).hexdigest()

                if content_hash in seen_hashes:
                    # 删除重复文件
                    category_path.unlink()
                    duplicates_removed += 1
                else:
                    seen_hashes.add(content_hash)
            except Exception as e:
                logger.warning(f"[DatasetManager] 清洗失败: {category_path}, 错误: {e}")

        logger.info(f"[DatasetManager] 清洗完成，移除 {duplicates_removed} 条重复数据")

        return duplicates_removed
