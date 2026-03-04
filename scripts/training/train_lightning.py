"""
PyTorch Lightning 训练脚本
Simplified Training Script with PyTorch Lightning

使用方法：
```bash
# 基础训练
python scripts/training/train_lightning.py \\
    --model Qwen/Qwen2.5-7B-Instruct \\
    --data training_data/training.jsonl \\
    --output model_ckpt/lora/my-model

# 自定义配置
python scripts/training/train_lightning.py \\
    --model Qwen/Qwen2.5-7B-Instruct \\
    --data training_data/training.jsonl \\
    --output model_ckpt/lora/my-model \\
    --r 32 \\
    --lora_alpha 64 \\
    --batch_size 8 \\
    --epochs 5 \\
    --lr 1e-4

# 多 GPU 训练
python scripts/training/train_lightning.py \\
    --model Qwen/Qwen2.5-7B-Instruct \\
    --data training_data/training.jsonl \\
    --output model_ckpt/lora/my-model \\
    --devices 2
```
"""

import os
import sys
import argparse
from pathlib import Path
from loguru import logger

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

try:
    import pytorch_lightning as pl
    from pytorch_lightning.callbacks import ModelCheckpoint, EarlyStopping
    from pytorch_lightning.loggers import WandbLogger, TensorBoardLogger
    from transformers import AutoTokenizer

    from training.models.lightning_module import SimpleLightningModule, LoRALightningModule
    from training.models.lightning_data import LightningDataModule
except ImportError as e:
    logger.error(f"缺少依赖: {e}")
    logger.info("请安装: pip install pytorch-lightning transformers datasets")
    sys.exit(1)


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="PyTorch Lightning LoRA 训练")

    # 模型参数
    parser.add_argument("--model", type=str, required=True, help="基座模型名称或路径")
    parser.add_argument("--tokenizer", type=str, default=None, help="分词器名称（默认与模型相同）")

    # 数据参数
    parser.add_argument("--data", type=str, required=True, help="训练数据路径（.jsonl）")
    parser.add_argument("--max_length", type=int, default=512, help="最大序列长度")
    parser.add_argument("--batch_size", type=int, default=4, help="批次大小")
    parser.add_argument("--num_workers", type=int, default=4, help="数据加载线程数")

    # LoRA 参数
    parser.add_argument("--r", type=int, default=16, help="LoRA rank")
    parser.add_argument("--lora_alpha", type=int, default=32, help="LoRA alpha")
    parser.add_argument("--lora_dropout", type=float, default=0.05, help="LoRA dropout")

    # 训练参数
    parser.add_argument("--epochs", type=int, default=3, help="训练轮数")
    parser.add_argument("--lr", type=float, default=2e-4, help="学习率")
    parser.add_argument("--weight_decay", type=float, default=0.01, help="权重衰减")
    parser.add_argument("--warmup_steps", type=int, default=100, help="预热步数")
    parser.add_argument("--gradient_clip_val", type=float, default=1.0, help="梯度裁剪")

    # 输出参数
    parser.add_argument("--output", type=str, required=True, help="输出目录")
    parser.add_argument("--checkpoint_dir", type=str, default=None, help="检查点目录")

    # 训练配置
    parser.add_argument("--devices", type=int, default=1, help="GPU 数量")
    parser.add_argument("--precision", type=str, default="bf16", choices=["32", "16", "bf16"], help="精度")
    parser.add_argument("--accumulate_grad_batches", type=int, default=4, help="梯度累积步数")
    parser.add_argument("--val_check_interval", type=float, default=0.25, help="验证间隔")

    # 日志和监控
    parser.add_argument("--logger", type=str, default="tensorboard", choices=["wandb", "tensorboard", "none"], help="日志类型")
    parser.add_argument("--project", type=str, default="anima-training", help="项目名称（WandB）")
    parser.add_argument("--run_name", type=str, default=None, help="运行名称（WandB）")

    # 其他
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument("--debug", action="store_true", help="调试模式")

    return parser.parse_args()


def main():
    """主函数"""
    args = parse_args()

    # 设置日志
    logger.remove()
    logger.add(sys.stdout, level="DEBUG" if args.debug else "INFO")

    logger.info("=" * 80)
    logger.info("PyTorch Lightning LoRA 训练")
    logger.info("=" * 80)

    # 打印配置
    logger.info(f"基座模型: {args.model}")
    logger.info("训练数据: {args.data}")
    logger.info(f"输出目录: {args.output}")
    logger.info(f"LoRA Rank: {args.r}")
    logger.info(f"学习率: {args.lr}")
    logger.info(f"批次大小: {args.batch_size}")
    logger.info(f"训练轮数: {args.epochs}")

    # 创建输出目录
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    checkpoint_dir = Path(args.checkpoint_dir) if args.checkpoint_dir else output_dir / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    # 加载分词器
    logger.info("加载分词器...")
    tokenizer = AutoTokenizer.from_pretrained(
        args.tokenizer or args.model,
        trust_remote_code=True,
        padding_side="right"
    )

    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # 创建数据模块
    logger.info("准备数据...")
    data_module = LightningDataModule(
        data_path=args.data,
        tokenizer=tokenizer,
        batch_size=args.batch_size,
        max_length=args.max_length,
        num_workers=args.num_workers,
        train_val_split=0.1,
        shuffle=True
    )

    # 创建模型
    logger.info("创建模型...")
    model = SimpleLightningModule(
        model_name=args.model,
        lora_r=args.r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        learning_rate=args.lr,
        weight_decay=args.weight_decay,
        max_grad_norm=args.gradient_clip_val,
        warmup_steps=args.warmup_steps
    )

    # 设置日志
    logger_args = None
    if args.logger == "wandb":
        logger_args = WandbLogger(
            project=args.project,
            name=args.run_name or f"{args.model.replace('/', '-')}_{args.r}",
            save_dir=str(output_dir)
        )
    elif args.logger == "tensorboard":
        logger_args = TensorBoardLogger(
            save_dir=str(output_dir),
            name="logs"
        )

    # 设置回调
    callbacks = []

    # 模型检查点
    checkpoint_callback = ModelCheckpoint(
        dirpath=str(checkpoint_dir),
        filename="model-{epoch:02d}-{val_loss:.2f}",
        save_top_k=3,
        monitor="val_loss",
        mode="min",
        save_last=True
    )
    callbacks.append(checkpoint_callback)

    # 早停
    early_stop_callback = EarlyStopping(
        monitor="val_loss",
        patience=3,
        mode="min"
    )
    callbacks.append(early_stop_callback)

    # 创建训练器
    logger.info("创建训练器...")
    trainer = pl.Trainer(
        max_epochs=args.epochs,
        devices=args.devices,
        precision=args.precision,
        accelerator="gpu" if args.devices > 0 else "cpu",
        strategy="ddp" if args.devices > 1 else "auto",
        callbacks=callbacks,
        logger=logger_args,
        log_every_n_steps=10,
        val_check_interval=args.val_check_interval,
        gradient_clip_val=args.gradient_clip_val,
        accumulate_grad_batches=args.accumulate_grad_batches,
        enable_progress_bar=True,
        enable_model_summary=True
    )

    # 开始训练
    logger.info("开始训练...")
    trainer.fit(model, data_module)

    # 保存模型
    logger.info(f"保存模型到: {output_dir}")
    model.save_model(str(output_dir))

    logger.info("训练完成！")


if __name__ == "__main__":
    main()
