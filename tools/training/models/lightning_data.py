"""
PyTorch Lightning 数据模块
Lightning Data Module for Training

使用 PyTorch Lightning DataModule 简化数据加载
"""

import os
from typing import Optional, Dict, Any
from pathlib import Path

import torch
from torch.utils.data import Dataset, DataLoader
from loguru import logger

try:
    from datasets import load_dataset, Dataset as HFDataset
    from transformers import AutoTokenizer
    import pytorch_lightning as pl
except ImportError:
    logger.error("请安装依赖: pip install datasets transformers pytorch-lightning")
    raise


class ConversationDataset(Dataset):
    """
    对话数据集

    格式：
    [
        {
            "conversation": [
                {"role": "user", "content": "..."},
                {"role": "assistant", "content": "..."}
            ]
        },
        ...
    ]
    """

    def __init__(
        self,
        data: HFDataset,
        tokenizer: AutoTokenizer,
        max_length: int = 512
    ):
        self.data = data
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        example = self.data[idx]

        # 格式化对话
        text = self._format_conversation(example["conversation"])

        # Tokenize
        encodings = self.tokenizer(
            text,
            truncation=True,
            max_length=self.max_length,
            padding="max_length",
            return_tensors="pt"
        )

        # 创建 labels（用于计算损失）
        labels = encodings["input_ids"].clone()
        # 将 padding token 的 label 设为 -100（忽略）
        labels[labels == self.tokenizer.pad_token_id] = -100

        return {
            "input_ids": encodings["input_ids"].squeeze(0),
            "attention_mask": encodings["attention_mask"].squeeze(0),
            "labels": labels.squeeze(0)
        }

    def _format_conversation(self, conversation: list) -> str:
        """格式化对话为训练文本"""
        formatted_texts = []

        for turn in conversation:
            role = turn["role"]
            content = turn["content"]

            if role == "user":
                formatted_texts.append(f"User: {content}")
            elif role == "assistant":
                formatted_texts.append(f"Assistant: {content}")
            elif role == "system":
                formatted_texts.append(f"System: {content}")

        return "\n".join(formatted_texts)


class LightningDataModule(pl.LightningDataModule):
    """
    PyTorch Lightning 数据模块

    功能：
    1. 自动加载数据集
    2. 自动划分训练/验证/测试集
    3. 自动创建 DataLoader
    4. 支持多 GPU 数据并行
    """

    def __init__(
        self,
        data_path: str,
        tokenizer: AutoTokenizer,
        batch_size: int = 4,
        max_length: int = 512,
        num_workers: int = 4,
        train_val_split: float = 0.1,
        shuffle: bool = True
    ):
        super().__init__()

        self.data_path = data_path
        self.tokenizer = tokenizer
        self.batch_size = batch_size
        self.max_length = max_length
        self.num_workers = num_workers
        self.train_val_split = train_val_split
        self.shuffle = shuffle

        self.train_dataset = None
        self.val_dataset = None
        self.test_dataset = None

        logger.info(f"[LightningDataModule] 初始化数据模块")
        logger.info(f"[LightningDataModule] 数据路径: {data_path}")
        logger.info(f"[LightningDataModule] 批次大小: {batch_size}")

    def prepare_data(self):
        """
        准备数据（只在主进程执行一次）

        功能：
        - 下载数据
        - 预处理数据
        """
        logger.info(f"[LightningDataModule] 准备数据: {self.data_path}")

        # 检查数据文件是否存在
        if not os.path.exists(self.data_path):
            raise FileNotFoundError(f"数据文件不存在: {self.data_path}")

    def setup(self, stage: Optional[str] = None):
        """
        设置数据集（在每个 GPU 上执行）

        Args:
            stage: "fit", "validate", "test", "predict"
        """
        logger.info(f"[LightningDataModule] 设置数据集 (stage={stage})")

        # 加载数据集
        if self.data_path.endswith(".jsonl"):
            dataset = load_dataset("json", data_files=self.data_path, split="train")
        else:
            dataset = load_from_disk(self.data_path)

        logger.info(f"[LightningDataModule] 加载数据集: {len(dataset)} 条")

        # 划分数据集
        if stage == "fit" or stage is None:
            split_dataset = dataset.train_test_split(test_size=self.train_val_split)
            self.train_dataset = ConversationDataset(
                split_dataset["train"],
                self.tokenizer,
                self.max_length
            )
            self.val_dataset = ConversationDataset(
                split_dataset["test"],
                self.tokenizer,
                self.max_length
            )

            logger.info(f"[LightningDataModule] 训练集: {len(self.train_dataset)} 条")
            logger.info(f"[LightningDataModule] 验证集: {len(self.val_dataset)} 条")

        if stage == "test":
            self.test_dataset = ConversationDataset(
                dataset,
                self.tokenizer,
                self.max_length
            )
            logger.info(f"[LightningDataModule] 测试集: {len(self.test_dataset)} 条")

    def train_dataloader(self):
        """返回训练数据加载器"""
        return DataLoader(
            self.train_dataset,
            batch_size=self.batch_size,
            shuffle=self.shuffle,
            num_workers=self.num_workers,
            pin_memory=True
        )

    def val_dataloader(self):
        """返回验证数据加载器"""
        return DataLoader(
            self.val_dataset,
            batch_size=self.batch_size,
            shuffle=False,
            num_workers=self.num_workers,
            pin_memory=True
        )

    def test_dataloader(self):
        """返回测试数据加载器"""
        return DataLoader(
            self.test_dataset,
            batch_size=self.batch_size,
            shuffle=False,
            num_workers=self.num_workers,
            pin_memory=True
        )


def load_from_disk(path):
    """从磁盘加载数据集（兼容性函数）"""
    try:
        from datasets import load_from_disk as load
        return load(path)
    except:
        # 如果是目录，尝试加载 JSONL
        jsonl_files = list(Path(path).glob("*.jsonl"))
        if jsonl_files:
            return load_dataset("json", data_files=str(jsonl_files[0]), split="train")
        raise
