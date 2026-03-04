"""
模型评估器
Model Evaluator

评估微调后模型的表现
"""

import torch
from typing import List, Dict, Optional
from pathlib import Path
from loguru import logger

try:
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel
    from evaluate import load
    import numpy as np
except ImportError:
    logger.warning("评估依赖未安装，部分功能不可用")


class ModelEvaluator:
    """
    模型评估器

    功能：
    1. 角色扮演质量评估
    2. 与基座模型对比
    3. 毒性检测
    4. BLEU/ROUGE/BERTScore 计算
    """

    def __init__(
        self,
        model_path: str,
        base_model: str = None,
        device: str = "cuda"
    ):
        """
        初始化评估器

        Args:
            model_path: 微调模型路径
            base_model: 基座模型路径（用于对比）
            device: 设备
        """
        self.model_path = model_path
        self.base_model = base_model
        self.device = device

        self.model = None
        self.tokenizer = None
        self.base_model_obj = None

        logger.info(f"[ModelEvaluator] 初始化评估器")
        logger.info(f"[ModelEvaluator] 模型路径: {model_path}")

    def load_model(self):
        """加载模型"""
        logger.info(f"[ModelEvaluator] 加载模型")

        # 加载分词器
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_path,
            trust_remote_code=True
        )

        # 加载模型
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_path,
            torch_dtype=torch.bfloat16,
            device_map=self.device,
            trust_remote_code=True
        )

        self.model.eval()

        logger.info(f"[ModelEvaluator] 模型加载完成")

    def load_base_model(self):
        """加载基座模型（用于对比）"""
        if not self.base_model:
            logger.warning(f"[ModelEvaluator] 未指定基座模型")
            return

        logger.info(f"[ModelEvaluator] 加载基座模型: {self.base_model}")

        self.base_model_obj = AutoModelForCausalLM.from_pretrained(
            self.base_model,
            torch_dtype=torch.bfloat16,
            device_map=self.device,
            trust_remote_code=True
        )

        self.base_model_obj.eval()

        logger.info(f"[ModelEvaluator] 基座模型加载完成")

    def generate_response(
        self,
        prompt: str,
        model=None,
        max_length: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9
    ) -> str:
        """
        生成回复

        Args:
            prompt: 提示词
            model: 模型（默认使用 self.model）
            max_length: 最大长度
            temperature: 温度参数
            top_p: top-p 参数

        Returns:
            生成的文本
        """
        if model is None:
            model = self.model

        inputs = self.tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=256
        ).to(self.device)

        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=max_length,
                temperature=temperature,
                top_p=top_p,
                do_sample=True,
                pad_token_id=self.tokenizer.pad_token_id
            )

        # 解码
        response = self.tokenizer.decode(
            outputs[0][inputs['input_ids'].shape[1]:],
            skip_special_tokens=True
        )

        return response

    def evaluate_roleplay_quality(
        self,
        test_dataset: List[Dict],
        categories: List[str] = None
    ) -> Dict:
        """
        评估角色扮演质量

        Args:
            test_dataset: 测试数据集
            categories: 评估类别

        Returns:
            评估指标字典
        """
        logger.info(f"[ModelEvaluator] 评估角色扮演质量")
        logger.info(f"[ModelEvaluator] 测试样本数: {len(test_dataset)}")

        metrics = {
            "character_consistency": [],  # 角色一致性
            "personality_adherence": [],  # 个性符合度
            "dialogue_naturalness": [],   # 对话自然度
            "emotional_expression": []    # 情绪表达
        }

        for item in test_dataset:
            # 生成回复
            prompt = self._create_prompt(item)
            response = self.generate_response(prompt)

            # 评估各个维度
            metrics["character_consistency"].append(
                self._check_consistency(response)
            )
            metrics["personality_adherence"].append(
                self._check_personality(response)
            )
            metrics["dialogue_naturalness"].append(
                self._check_naturalness(response)
            )
            metrics["emotional_expression"].append(
                self._check_emotions(response)
            )

        # 计算平均分
        results = {}
        for key, values in metrics.items():
            results[key] = {
                "mean": float(np.mean(values)),
                "std": float(np.std(values)),
                "min": float(np.min(values)),
                "max": float(np.max(values))
            }

        logger.info(f"[ModelEvaluator] 角色扮演评估完成")
        return results

    def compare_with_base(
        self,
        prompts: List[str]
    ) -> Dict:
        """
        与基座模型对比

        Args:
            prompts: 测试提示词列表

        Returns:
            对比结果
        """
        logger.info(f"[ModelEvaluator] 与基座模型对比")
        logger.info(f"[ModelEvaluator] 测试提示词数: {len(prompts)}")

        if not self.base_model_obj:
            logger.error(f"[ModelEvaluator] 基座模型未加载")
            return {}

        results = {
            "prompts": [],
            "base_model_responses": [],
            "finetuned_responses": [],
            "preference": []
        }

        for prompt in prompts:
            # 基座模型生成
            base_response = self.generate_response(
                prompt,
                model=self.base_model_obj
            )

            # 微调模型生成
            finetuned_response = self.generate_response(
                prompt,
                model=self.model
            )

            results["prompts"].append(prompt)
            results["base_model_responses"].append(base_response)
            results["finetuned_responses"].append(finetuned_response)

            # 简单的偏好判断（实际需要人工评估）
            # 这里基于长度和多样性
            base_score = len(base_response) * 0.5 + len(set(base_response)) * 0.5
            finetuned_score = len(finetuned_response) * 0.5 + len(set(finetuned_response)) * 0.5

            preference = "finetuned" if finetuned_score > base_score else "base"
            results["preference"].append(preference)

        # 统计偏好
        finetuned_wins = results["preference"].count("finetuned")
        win_rate = finetuned_wins / len(prompts)

        results["win_rate"] = win_rate

        logger.info(f"[ModelEvaluator] 微调模型胜率: {win_rate:.2%}")

        return results

    def calculate_bleu_rouge(
        self,
        predictions: List[str],
        references: List[str]
    ) -> Dict:
        """
        计算 BLEU 和 ROUGE 分数

        Args:
            predictions: 预测文本列表
            references: 参考文本列表

        Returns:
            评估指标
        """
        try:
            # 加载评估指标
            bleu = load("bleu")
            rouge = load("rouge")

            # 计算 BLEU
            bleu_results = bleu.compute(
                predictions=predictions,
                references=references
            )

            # 计算 ROUGE
            rouge_results = rouge.compute(
                predictions=predictions,
                references=references
            )

            return {
                "bleu": bleu_results,
                "rouge": rouge_results
            }
        except Exception as e:
            logger.error(f"[ModelEvaluator] 指标计算失败: {e}")
            return {}

    def _create_prompt(self, item: Dict) -> str:
        """创建提示词"""
        conversation = item.get("conversation", [])

        prompt_parts = []
        for turn in conversation:
            if turn["role"] == "user":
                prompt_parts.append(f"User: {turn['content']}")
            elif turn["role"] == "assistant":
                prompt_parts.append(f"Assistant: {turn['content']}")

        # 最后一个用户问题
        prompt_parts.append("Assistant:")

        return "\n".join(prompt_parts)

    def _check_consistency(self, response: str) -> float:
        """检查角色一致性"""
        # 简化的启发式方法
        # 实际需要更复杂的NLP分析

        score = 0.5  # 基础分

        # 检查是否有第一人称代词（角色扮演的标志）
        if "我" in response:
            score += 0.2

        # 检查是否有情感表达
        if any(word in response for word in ["[happy]", "[sad]", "[angry]"]):
            score += 0.2

        # 检查长度
        if 10 < len(response) < 200:
            score += 0.1

        return min(score, 1.0)

    def _check_personality(self, response: str) -> float:
        """检查个性符合度"""
        score = 0.5

        # Neuro-sama 特征关键词
        neuro_keywords = [
            "skill issue",
            "cringe",
            "based",
            "cap",
            "OSU",
            "音游",
            "嘿嘿"
        ]

        response_lower = response.lower()
        matches = sum(1 for kw in neuro_keywords if kw.lower() in response_lower)

        score += matches * 0.1

        return min(score, 1.0)

    def _check_naturalness(self, response: str) -> float:
        """检查对话自然度"""
        score = 0.5

        # 检查标点符号
        if any(punct in response for punct in ["。", "！", "？", ".", "!", "?"]):
            score += 0.2

        # 检查重复
        words = response.split()
        unique_ratio = len(set(words)) / len(words) if words else 0

        if unique_ratio > 0.5:
            score += 0.2

        # 检查长度
        if 10 < len(response) < 200:
            score += 0.1

        return min(score, 1.0)

    def _check_emotions(self, response: str) -> float:
        """检查情绪表达"""
        emotions = ["[happy]", "[sad]", "[angry]", "[surprised]", "[neutral]"]

        has_emotion = any(emotion in response for emotion in emotions)

        return 1.0 if has_emotion else 0.5

    def save_results(
        self,
        results: Dict,
        output_path: str = "evaluation_results.json"
    ):
        """
        保存评估结果

        Args:
            results: 评估结果
            output_path: 输出文件路径
        """
        import json

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        logger.info(f"[ModelEvaluator] 结果已保存: {output_path}")
