"""
快速训练脚本（极简版）
Quick Training Script - Minimal

最简单的训练脚本，只需 3 行代码即可开始训练

使用方法：
```bash
python scripts/training/quick_train_lightning.py
```
"""

import sys
from pathlib import Path
from loguru import logger

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

try:
    import pytorch_lightning as pl
    from transformers import AutoTokenizer
    from training.models.lightning_module import SimpleLightningModule
    from training.models.lightning_data import LightningDataModule
except ImportError as e:
    logger.error(f"缺少依赖: {e}")
    logger.info("请安装: pip install pytorch-lightning transformers datasets")
    sys.exit(1)


def quick_train(
    model_name: str = "Qwen/Qwen2.5-7B-Instruct",
    data_path: str = "training_data/training.jsonl",
    output_dir: str = "model_ckpt/lora/quick-model",
    max_epochs: int = 3,
    batch_size: int = 4,
    learning_rate: float = 2e-4
):
    """
    快速训练 LoRA 模型

    Args:
        model_name: 基座模型名称
        data_path: 训练数据路径
        output_dir: 输出目录
        max_epochs: 训练轮数
        batch_size: 批次大小
        learning_rate: 学习率
    """

    logger.info("=" * 60)
    logger.info("快速训练 LoRA 模型")
    logger.info("=" * 60)
    logger.info(f"模型: {model_name}")
    logger.info(f"数据: {data_path}")
    logger.info(f"输出: {output_dir}")

    # 1. 加载分词器
    logger.info("加载分词器...")
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # 2. 准备数据
    logger.info("准备数据...")
    data_module = LightningDataModule(
        data_path=data_path,
        tokenizer=tokenizer,
        batch_size=batch_size,
        max_length=512,
        num_workers=4
    )

    # 3. 创建模型
    logger.info("创建模型...")
    model = SimpleLightningModule(
        model_name=model_name,
        learning_rate=learning_rate
    )

    # 4. 训练
    logger.info("开始训练...")
    trainer = pl.Trainer(
        max_epochs=max_epochs,
        precision="bf16",
        accelerator="auto",
        devices=1,
        log_every_n_steps=10
    )

    trainer.fit(model, data_module)

    # 5. 保存
    logger.info(f"保存模型到: {output_dir}")
    model.save_model(output_dir)

    logger.info("训练完成！")

    return model, trainer


if __name__ == "__main__":
    # 默认配置
    config = {
        "model_name": "Qwen/Qwen2.5-7B-Instruct",
        "data_path": "training_data/training.jsonl",
        "output_dir": "model_ckpt/lora/quick-model",
        "max_epochs": 3,
        "batch_size": 4,
        "learning_rate": 2e-4
    }

    # 检查数据文件是否存在
    if not Path(config["data_path"]).exists():
        logger.warning(f"数据文件不存在: {config['data_path']}")
        logger.info("请先运行数据收集脚本或指定正确的数据路径")

        # 尝试查找数据文件
        data_dir = Path("datasets")
        if data_dir.exists():
            jsonl_files = list(data_dir.glob("*.jsonl"))
            if jsonl_files:
                config["data_path"] = str(jsonl_files[0])
                logger.info(f"找到数据文件: {config['data_path']}")
            else:
                logger.error("未找到任何数据文件")
                sys.exit(1)
        else:
            logger.error("数据目录不存在: training_data/")
            sys.exit(1)

    # 开始训练
    model, trainer = quick_train(**config)
