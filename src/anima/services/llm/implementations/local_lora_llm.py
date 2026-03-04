"""
本地 LoRA 微调模型服务
Local Lora LLM Service

使用本地微调后的模型进行推理
"""

import asyncio
from typing import AsyncIterator, Dict, Optional
import torch
from loguru import logger

from ..interface import LLMInterface
from ....config.core.registry import ProviderRegistry


@ProviderRegistry.register_service("llm", "local_lora")
class LocalLoraLLM(LLMInterface):
    """
    本地 LoRA 微调模型服务

    使用本地微调后的模型进行对话
    """

    def __init__(
        self,
        base_model_name: str = "Qwen/Qwen2.5-7B-Instruct",
        lora_path: str = "models/lora/neuro-vtuber-v1",
        device: str = "cuda",
        system_prompt: str = "",
        **kwargs
    ):
        """
        初始化本地 LoRA 模型

        Args:
            base_model_name: 基座模型名称
            lora_path: LoRA 适配器路径
            device: 设备 (cuda/cpu)
            system_prompt: 系统提示词
        """
        self.base_model_name = base_model_name
        self.lora_path = lora_path
        self.requested_device = device  # 保存用户请求的设备
        self.device = self._resolve_device(device)  # 自动降级
        self.system_prompt = system_prompt

        self.model = None
        self.tokenizer = None
        self._loaded = False

        # 对话历史
        self.history: list = []

        logger.info(f"[LocalLoraLLM] 初始化")
        logger.info(f"[LocalLoraLLM] 基座模型: {base_model_name}")
        logger.info(f"[LocalLoraLLM] LoRA 路径: {lora_path}")
        logger.info(f"[LocalLoraLLM] 请求设备: {device}")
        logger.info(f"[LocalLoraLLM] 实际设备: {self.device}")

        if self.device != self.requested_device:
            logger.warning(f"[LocalLoraLLM] ⚠️ 设备已自动降级: {self.requested_device} → {self.device}")
            logger.warning(f"[LocalLoraLLM] ⚠️ 性能将受影响，请检查CUDA安装")

    def _resolve_device(self, requested_device: str) -> str:
        """
        解析设备，自动降级 CUDA → CPU

        Args:
            requested_device: 用户请求的设备

        Returns:
            str: 实际使用的设备
        """
        if requested_device == "cpu":
            return "cpu"

        # 检查CUDA是否可用
        try:
            if torch.cuda.is_available():
                return "cuda"
        except:
            pass

        # CUDA不可用，降级到CPU
        logger.warning(f"[LocalLoraLLM] CUDA不可用，将使用CPU")
        return "cpu"

    @classmethod
    def from_config(cls, config, system_prompt: str = "", **kwargs):
        """
        从配置创建实例

        Args:
            config: LocalLoraLLMConfig
            system_prompt: 系统提示词
            **kwargs: 其他参数

        Returns:
            LocalLoraLLM 实例
        """
        return cls(
            base_model_name=config.base_model_name,
            lora_path=config.lora_path,
            device=config.device,
            system_prompt=system_prompt
        )

    def load_model(self):
        """加载模型"""
        if self._loaded:
            return

        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            from peft import PeftModel

            logger.info(f"[LocalLoraLLM] 加载基座模型: {self.base_model_name}")

            # 加载分词器
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.base_model_name,
                trust_remote_code=True
            )

            if self.tokenizer.pad_token is None:
                self.tokenizer.pad_token = self.tokenizer.eos_token

            # 根据设备选择数据类型
            if self.device == "cuda":
                torch_dtype = torch.bfloat16
                device_map = "cuda"
            else:  # cpu
                torch_dtype = torch.float32  # CPU使用float32
                device_map = "cpu"

            # 加载基座模型
            logger.info(f"[LocalLoraLLM] 使用设备: {device_map}, 数据类型: {torch_dtype}")
            base_model = AutoModelForCausalLM.from_pretrained(
                self.base_model_name,
                torch_dtype=torch_dtype,
                device_map=device_map,
                trust_remote_code=True,
                low_cpu_mem_usage=True  # 减少CPU内存占用
            )

            # 加载 LoRA 适配器
            logger.info(f"[LocalLoraLLM] 加载 LoRA 适配器: {self.lora_path}")

            self.model = PeftModel.from_pretrained(
                base_model,
                self.lora_path,
                is_trainable=False
            )

            self.model.eval()
            self._loaded = True

            logger.info(f"[LocalLoraLLM] ✅ 模型加载完成")

            # 性能提示
            if self.device == "cpu":
                logger.warning(f"[LocalLoraLLM] ⚠️ 使用CPU推理，速度较慢")
                logger.warning(f"[LocalLoraLLM] 💡 建议安装CUDA版本PyTorch以获得更好性能")

        except Exception as e:
            logger.error(f"[LocalLoraLLM] ❌ 模型加载失败: {e}")
            logger.error(f"[LocalLoraLLM] 💡 请检查:")
            logger.error(f"[LocalLoraLLM]    1. 模型路径是否正确: {self.base_model_name}")
            logger.error(f"[LocalLoraLLM]    2. LoRA路径是否正确: {self.lora_path}")
            logger.error(f"[LocalLoraLLM]    3. 是否安装了transformers和peft")
            raise

    async def chat_stream(self, text: str) -> AsyncIterator[str]:
        """
        流式对话

        Args:
            text: 输入文本

        Yields:
            生成的文本片段
        """
        # 确保模型已加载
        if not self._loaded:
            self.load_model()

        # 构造提示词
        prompt = self._format_prompt(text)

        # Tokenize
        inputs = self.tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=256
        ).to(self.device)

        # 生成参数
        generation_kwargs = {
            "max_new_tokens": 512,
            "temperature": 0.7,
            "top_p": 0.9,
            "do_sample": True,
            "pad_token_id": self.tokenizer.pad_token_id,
            "eos_token_id": self.tokenizer.eos_token_id
        }

        # 流式生成
        try:
            from transformers import TextIteratorStreamer

            streamer = TextIteratorStreamer(
                self.tokenizer,
                skip_prompt=True,
                skip_special_tokens=True
            )

            generation_kwargs["streamer"] = streamer

            # 在后台线程中生成
            import threading

            def generate():
                with torch.no_grad():
                    self.model.generate(**inputs, **generation_kwargs)

            thread = threading.Thread(target=generate)
            thread.start()

            # 流式输出
            for text in streamer:
                yield text

            thread.join()

        except Exception as e:
            logger.error(f"[LocalLoraLLM] 生成失败: {e}")
            yield f"【生成失败: {str(e)}】"

    def _format_prompt(self, text: str) -> str:
        """
        格式化提示词

        Args:
            text: 用户输入

        Returns:
            格式化后的提示词
        """
        # 使用 Qwen Chat 模板格式
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": text}
        ]

        # 使用 tokenizer 的 chat template
        prompt = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )

        return prompt

    async def chat(self, text: str) -> str:
        """
        非流式对话

        Args:
            text: 输入文本

        Returns:
            生成的完整文本
        """
        # 确保模型已加载
        if not self._loaded:
            self.load_model()

        # 构造提示词
        prompt = self._format_prompt(text)

        # Tokenize
        inputs = self.tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=256
        ).to(self.device)

        # 生成
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=512,
                temperature=0.7,
                top_p=0.9,
                do_sample=True,
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id
            )

        # 解码
        response = self.tokenizer.decode(
            outputs[0][inputs['input_ids'].shape[1]:],
            skip_special_tokens=True
        )

        return response

    def set_system_prompt(self, prompt: str) -> None:
        """设置系统提示词"""
        self.system_prompt = prompt
        logger.debug(f"[LocalLoraLLM] 系统提示词已更新")

    def get_history(self) -> list:
        """获取对话历史"""
        return self.history.copy()

    def clear_history(self) -> None:
        """清空对话历史"""
        self.history.clear()
        logger.debug(f"[LocalLoraLLM] 对话历史已清空")

    def handle_interrupt(self, heard_response: str = "") -> None:
        """处理用户打断"""
        logger.debug(f"[LocalLoraLLM] 处理打断: heard='{heard_response[:50]}...'")
        # 可以在这里保存听到的部分回复到历史中
        if heard_response:
            self.history.append({"role": "assistant", "content": heard_response})

    def set_memory_from_history(self, conf_uid: str, history_uid: str) -> None:
        """从历史记录恢复对话记忆（暂未实现）"""
        logger.debug(f"[LocalLoraLLM] 从历史恢复记忆: conf_uid={conf_uid}, history_uid={history_uid}")

    async def close(self):
        """关闭模型，释放资源"""
        if self.model is not None:
            del self.model
            self.model = None

        if self.tokenizer is not None:
            del self.tokenizer
            self.tokenizer = None

        self._loaded = False

        logger.info(f"[LocalLoraLLM] 模型已卸载")
