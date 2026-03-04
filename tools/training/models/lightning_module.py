"""
PyTorch Lightning LoRA 模块
Lightning Module for LoRA Fine-Tuning

使用 PyTorch Lightning 简化训练流程
"""

import os
from typing import Dict, Optional, Any
from dataclasses import dataclass

import torch
from loguru import logger
from torch.optim import AdamW

try:
    import pytorch_lightning as pl
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import LoraConfig, get_peft_model, TaskType
except ImportError:
    logger.error("请安装 PyTorch Lightning: pip install pytorch-lightning")
    raise


@dataclass
class LightningLoRAConfig:
    """Lightning LoRA 配置"""

    # 模型配置
    model_name: str = "Qwen/Qwen2.5-7B-Instruct"
    tokenizer_name: Optional[str] = None

    # LoRA 参数
    r: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    target_modules: list = None
    bias: str = "none"

    # 训练参数
    learning_rate: float = 2e-4
    weight_decay: float = 0.01
    max_grad_norm: float = 1.0
    warmup_steps: int = 100
    lr_scheduler_type: str = "cosine"

    # 其他配置
    max_seq_length: int = 512
    gradient_checkpointing: bool = True

    def __post_init__(self):
        if self.target_modules is None:
            self.target_modules = [
                "q_proj", "k_proj", "v_proj", "o_proj",
                "gate_proj", "up_proj", "down_proj"
            ]


class LoRALightningModule(pl.LightningModule):
    """
    PyTorch Lightning LoRA 训练模块

    功能：
    1. 自动处理训练/验证/测试循环
    2. 自动处理优化器和学习率调度
    3. 支持 GPU/TPU 多节点训练
    4. 自动混合精度训练 (AMP)
    5. 梯度检查点支持
    """

    def __init__(self, config: LightningLoRAConfig):
        super().__init__()

        self.config = config
        self.save_hyperparameters()

        # 加载模型
        logger.info(f"[LoRALightning] 加载模型: {config.model_name}")
        self.model = AutoModelForCausalLM.from_pretrained(
            config.model_name,
            torch_dtype=torch.bfloat16,
            trust_remote_code=True
        )

        # 配置 LoRA
        logger.info(f"[LoRALightning] 配置 LoRA (r={config.r})")
        lora_config = LoraConfig(
            r=config.r,
            lora_alpha=config.lora_alpha,
            target_modules=config.target_modules,
            lora_dropout=config.lora_dropout,
            bias=config.bias,
            task_type=TaskType.CAUSAL_LM
        )

        self.model = get_peft_model(self.model, lora_config)

        # 启用梯度检查点
        if config.gradient_checkpointing:
            self.model.gradient_checkpointing_enable()

        # 打印可训练参数
        self.model.print_trainable_parameters()

        # 加载分词器
        tokenizer_name = config.tokenizer_name or config.model_name
        self.tokenizer = AutoTokenizer.from_pretrained(
            tokenizer_name,
            trust_remote_code=True,
            padding_side="right"
        )

        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

    def forward(self, input_ids, attention_mask=None, labels=None):
        """前向传播"""
        return self.model(
            input_ids=input_ids,
            attention_mask=attention_mask,
            labels=labels
        )

    def training_step(self, batch, batch_idx):
        """训练步骤"""
        outputs = self(
            input_ids=batch["input_ids"],
            attention_mask=batch["attention_mask"],
            labels=batch["labels"]
        )

        loss = outputs.loss
        self.log("train_loss", loss, prog_bar=True, logger=True, on_step=True, on_epoch=True)
        return loss

    def validation_step(self, batch, batch_idx):
        """验证步骤"""
        outputs = self(
            input_ids=batch["input_ids"],
            attention_mask=batch["attention_mask"],
            labels=batch["labels"]
        )

        loss = outputs.loss
        self.log("val_loss", loss, prog_bar=True, logger=True, on_step=False, on_epoch=True)
        return loss

    def test_step(self, batch, batch_idx):
        """测试步骤"""
        return self.validation_step(batch, batch_idx)

    def configure_optimizers(self):
        """配置优化器和学习率调度器"""
        # 只训练 LoRA 参数
        lora_params = [p for n, p in self.model.named_parameters() if p.requires_grad]

        optimizer = AdamW(
            lora_params,
            lr=self.config.learning_rate,
            weight_decay=self.config.weight_decay
        )

        # 学习率调度器
        if self.config.lr_scheduler_type == "cosine":
            scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
                optimizer,
                T_max=self.trainer.max_steps,
                eta_min=1e-6
            )
        else:
            scheduler = torch.optim.lr_scheduler.LinearLR(
                optimizer,
                start_factor=0.1,
                total_iters=self.config.warmup_steps
            )

        return {
            "optimizer": optimizer,
            "lr_scheduler": {
                "scheduler": scheduler,
                "interval": "step",
                "frequency": 1
            }
        }

    def on_save_checkpoint(self, checkpoint):
        """保存检查点时的钩子"""
        logger.info(f"[LoRALightning] 保存检查点: {self.trainer.current_epoch}")

    def on_load_checkpoint(self, checkpoint):
        """加载检查点时的钩子"""
        logger.info(f"[LoRALightning] 加载检查点")

    def save_model(self, output_dir: str):
        """保存最终模型"""
        os.makedirs(output_dir, exist_ok=True)

        # 保存 LoRA 适配器
        self.model.save_pretrained(output_dir)

        # 保存分词器
        self.tokenizer.save_pretrained(output_dir)

        logger.info(f"[LoRALightning] 模型已保存到: {output_dir}")


class SimpleLightningModule(pl.LightningModule):
    """
    简化的 Lightning 模块（用于快速原型）

    使用方法：
    ```python
    model = SimpleLightningModule(
        model_name="Qwen/Qwen2.5-7B-Instruct",
        lora_r=16,
        learning_rate=2e-4
    )
    trainer = pl.Trainer(max_epochs=3, precision="bf16")
    trainer.fit(model, train_dataloader, val_dataloader)
    ```
    """

    def __init__(
        self,
        model_name: str,
        lora_r: int = 16,
        lora_alpha: int = 32,
        lora_dropout: float = 0.05,
        learning_rate: float = 2e-4,
        weight_decay: float = 0.01,
        max_grad_norm: float = 1.0,
        warmup_steps: int = 100,
        **kwargs
    ):
        config = LightningLoRAConfig(
            model_name=model_name,
            r=lora_r,
            lora_alpha=lora_alpha,
            lora_dropout=lora_dropout,
            learning_rate=learning_rate,
            weight_decay=weight_decay,
            max_grad_norm=max_grad_norm,
            warmup_steps=warmup_steps,
            **kwargs
        )

        super().__init__()
        self.config = config
        self.save_hyperparameters()

        # 加载模型
        logger.info(f"[SimpleLightning] 加载模型: {model_name}")
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            torch_dtype=torch.bfloat16,
            trust_remote_code=True
        )

        # 配置 LoRA
        lora_config = LoraConfig(
            r=lora_r,
            lora_alpha=lora_alpha,
            lora_dropout=lora_dropout,
            target_modules=[
                "q_proj", "k_proj", "v_proj", "o_proj",
                "gate_proj", "up_proj", "down_proj"
            ],
            bias="none",
            task_type=TaskType.CAUSAL_LM
        )

        self.model = get_peft_model(self.model, lora_config)
        self.model.gradient_checkpointing_enable()

        # 打印可训练参数
        self.model.print_trainable_parameters()

    def forward(self, input_ids, attention_mask=None, labels=None):
        return self.model(
            input_ids=input_ids,
            attention_mask=attention_mask,
            labels=labels
        )

    def training_step(self, batch, batch_idx):
        outputs = self(
            input_ids=batch["input_ids"],
            attention_mask=batch["attention_mask"],
            labels=batch["labels"]
        )
        loss = outputs.loss
        self.log("train_loss", loss, prog_bar=True)
        return loss

    def validation_step(self, batch, batch_idx):
        outputs = self(
            input_ids=batch["input_ids"],
            attention_mask=batch["attention_mask"],
            labels=batch["labels"]
        )
        loss = outputs.loss
        self.log("val_loss", loss, prog_bar=True)
        return loss

    def configure_optimizers(self):
        lora_params = [p for n, p in self.model.named_parameters() if p.requires_grad]
        optimizer = AdamW(lora_params, lr=self.config.learning_rate, weight_decay=self.config.weight_decay)

        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
            optimizer,
            T_max=self.trainer.max_steps,
            eta_min=1e-6
        )

        return {
            "optimizer": optimizer,
            "lr_scheduler": {
                "scheduler": scheduler,
                "interval": "step"
            }
        }
