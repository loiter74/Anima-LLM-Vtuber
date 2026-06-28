from __future__ import annotations

"""
Local LoRA fine-tuned model service
Local Lora LLM Service


Uses locally fine-tuned models for inference
"""

import asyncio
from collections.abc import AsyncIterator

import torch
from loguru import logger

from animetta.config.core.registry import ProviderRegistry

from .interface import LLMInterface


@ProviderRegistry.register_service("llm", "local_lora")
class LocalLoraLLM(LLMInterface):
    """
    Local LoRA fine-tuned model service

    Uses locally fine-tuned models for conversation
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
        Initialize the local LoRA model

        Args:
            base_model_name: Base model name
            lora_path: LoRA adapter path
            device: Device (cuda/cpu)
            system_prompt: System prompt
        """
        self.base_model_name = base_model_name
        self.lora_path = lora_path
        self.requested_device = device  # Save user-requested device
        self.device = self._resolve_device(device)  # Auto-degradation
        self.system_prompt = system_prompt

        self.model = None
        self.tokenizer = None
        self._loaded = False

        # Conversation history
        self.history: list = []

        logger.info("[LocalLoraLLM] Initializing")
        logger.info(f"[LocalLoraLLM] Base model: {base_model_name}")
        logger.info(f"[LocalLoraLLM] LoRA path: {lora_path}")
        logger.info(f"[LocalLoraLLM] Requested device: {device}")
        logger.info(f"[LocalLoraLLM] Actual device: {self.device}")

        if self.device != self.requested_device:
            logger.warning(f"[LocalLoraLLM] ⚠️ Device auto-downgraded: {self.requested_device} → {self.device}")
            logger.warning("[LocalLoraLLM] ⚠️ Performance will be affected, please check CUDA installation")

        # Preload model (avoid timeout on first call)
        logger.info("[LocalLoraLLM] 🔄 Starting model preload...")
        self.load_model()
        logger.info("[LocalLoraLLM] ✅ Model preload complete")

    def _resolve_device(self, requested_device: str) -> str:
        """
        Resolve device, auto-downgrade CUDA → CPU

        Args:
            requested_device: User-requested device

        Returns:
            str: Actual device to use
        """
        if requested_device == "cpu":
            return "cpu"

        # Check if CUDA is available
        try:
            if torch.cuda.is_available():
                return "cuda"
        except Exception:
            logger.debug("[LocalLoraLLM] Failed to check CUDA availability")

        # CUDA not available, downgrade to CPU
        logger.warning("[LocalLoraLLM] CUDA not available, will use CPU")
        return "cpu"

    @classmethod
    def from_config(cls, config, system_prompt: str = "", **kwargs):
        """
        Create an instance from configuration

        Args:
            config: LocalLoraLLMConfig
            system_prompt: System prompt
            **kwargs: Additional parameters

        Returns:
            LocalLoraLLM instance
        """
        return cls(
            base_model_name=config.base_model_name,
            lora_path=config.lora_path,
            device=config.device,
            system_prompt=system_prompt
        )

    def load_model(self):
        """Load the model"""
        if self._loaded:
            return

        try:
            import os

            from peft import PeftModel
            from transformers import AutoModelForCausalLM, AutoTokenizer

            logger.info(f"[LocalLoraLLM] Loading base model: {self.base_model_name}")

            # Check if it is a local path (Windows drive letter or absolute path)
            is_local_path = (
                os.path.isabs(self.base_model_name) or
                (len(self.base_model_name) > 2 and self.base_model_name[1] == ':') or
                self.base_model_name.startswith('/')
            )

            # Load tokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.base_model_name,
                trust_remote_code=True,
                local_files_only=is_local_path
            )

            if self.tokenizer.pad_token is None:
                self.tokenizer.pad_token = self.tokenizer.eos_token

            # Select dtype based on device
            if self.device == "cuda":
                torch_dtype = torch.bfloat16
                device_map = "cuda"
            else:  # cpu
                torch_dtype = torch.float32  # CPU uses float32
                device_map = "cpu"

            # Load base model
            logger.info(f"[LocalLoraLLM] Using device: {device_map}, dtype: {torch_dtype}")
            base_model = AutoModelForCausalLM.from_pretrained(
                self.base_model_name,
                torch_dtype=torch_dtype,
                device_map=device_map,
                trust_remote_code=True,
                low_cpu_mem_usage=True,  # Reduce CPU memory usage
                local_files_only=is_local_path
            )

            # Load LoRA adapter
            logger.info(f"[LocalLoraLLM] Loading LoRA adapter: {self.lora_path}")

            self.model = PeftModel.from_pretrained(
                base_model,
                self.lora_path,
                is_trainable=False
            )

            self.model.eval()
            self._loaded = True

            logger.info("[LocalLoraLLM] ✅ Model loaded successfully")

            # Performance tips
            if self.device == "cpu":
                logger.warning("[LocalLoraLLM] ⚠️ Using CPU for inference, performance will be slower")
                logger.warning("[LocalLoraLLM] 💡 Consider installing CUDA-enabled PyTorch for better performance")

        except Exception as e:
            logger.error(f"[LocalLoraLLM] ❌ Model loading failed: {e}")
            logger.error("[LocalLoraLLM] 💡 Please check:")
            logger.error(f"[LocalLoraLLM]    1. Is the model path correct: {self.base_model_name}")
            logger.error(f"[LocalLoraLLM]    2. Is the LoRA path correct: {self.lora_path}")
            logger.error("[LocalLoraLLM]    3. Are transformers and peft installed")
            raise

    async def chat_stream(self, text: str) -> AsyncIterator[str]:
        """
        Streaming conversation

        Args:
            text: Input text

        Yields:
            Generated text chunks
        """
        # Ensure the model is loaded
        if not self._loaded:
            self.load_model()

        # Build prompt
        prompt = self._format_prompt(text)

        # Tokenize
        inputs = self.tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=256
        ).to(self.device)

        # Generation parameters
        generation_kwargs = {
            "max_new_tokens": 512,
            "temperature": 0.7,
            "top_p": 0.9,
            "do_sample": True,
            "pad_token_id": self.tokenizer.pad_token_id,
            "eos_token_id": self.tokenizer.eos_token_id
        }

        # Streaming generation
        try:
            from transformers import TextIteratorStreamer

            streamer = TextIteratorStreamer(
                self.tokenizer,
                skip_prompt=True,
                skip_special_tokens=True
            )

            generation_kwargs["streamer"] = streamer

            # Generate in a background thread
            import threading

            def generate():
                with torch.no_grad():
                    self.model.generate(**inputs, **generation_kwargs)

            thread = threading.Thread(target=generate)
            thread.start()

            # Stream output
            for text in streamer:
                yield text

            thread.join()

        except Exception as e:
            logger.error(f"[LocalLoraLLM] Generation failed: {e}")
            yield f"【生成失败: {str(e)}】"

    def _format_prompt(self, text: str) -> str:
        """
        Format the prompt

        Args:
            text: User input

        Returns:
            Formatted prompt
        """
        # Use Qwen Chat template format
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": text}
        ]

        # Use tokenizer's chat template
        prompt = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )

        return prompt

    async def chat(self, text: str) -> str:
        """
        Non-streaming conversation (async)

        Args:
            text: Input text

        Returns:
            Complete generated text
        """
        # Ensure the model is loaded
        if not self._loaded:
            self.load_model()

        # Build prompt
        prompt = self._format_prompt(text)

        logger.info("[LocalLoraLLM] Starting response generation...")
        logger.debug(f"[LocalLoraLLM] Input prompt length: {len(prompt)} chars")

        # Use thread pool to execute blocking model generation

        def generate_sync():
            # Tokenize
            inputs = self.tokenizer(
                prompt,
                return_tensors="pt",
                truncation=True,
                max_length=256
            ).to(self.device)

            # Generate
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

            # Decode
            response = self.tokenizer.decode(
                outputs[0][inputs['input_ids'].shape[1]:],
                skip_special_tokens=True
            )

            return response

        # Execute blocking call in thread pool
        response = await asyncio.to_thread(generate_sync)

        logger.info("[LocalLoraLLM] ✅ Generation complete")
        logger.debug(f"[LocalLoraLLM] Output length: {len(response)} chars")

        return response

    def set_system_prompt(self, prompt: str) -> None:
        """Set the system prompt"""
        self.system_prompt = prompt
        logger.debug("[LocalLoraLLM] System prompt updated")

    def get_history(self) -> list:
        """Get conversation history"""
        return self.history.copy()

    def clear_history(self) -> None:
        """Clear conversation history"""
        self.history.clear()
        logger.debug("[LocalLoraLLM] Conversation history cleared")

    def handle_interrupt(self, heard_response: str = "") -> None:
        """Handle user interruption"""
        logger.debug(f"[LocalLoraLLM] Handling interrupt: heard='{heard_response[:50]}...'")
        # Can save the partial response heard into history here
        if heard_response:
            self.history.append({"role": "assistant", "content": heard_response})

    def set_memory_from_history(self, conf_uid: str, history_uid: str) -> None:
        """Restore conversation memory from history (not yet implemented)"""
        logger.debug(f"[LocalLoraLLM] Restoring memory from history: conf_uid={conf_uid}, history_uid={history_uid}")

    async def close(self):
        """Close the model and release resources"""
        if self.model is not None:
            del self.model
            self.model = None

        if self.tokenizer is not None:
            del self.tokenizer
            self.tokenizer = None

        self._loaded = False

        logger.info("[LocalLoraLLM] Model unloaded")
