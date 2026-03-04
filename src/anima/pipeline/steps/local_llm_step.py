"""
Local LLM Step
本地模型步骤 - 调用LocalLLM进行简单应答（无persona）
"""

from typing import Optional
from loguru import logger

from ..base import PipelineStep
from ...core.context import PipelineContext
from ...services.llm.interface import LLMInterface


class LocalLLMStep(PipelineStep):
    """
    本地LLM步骤

    使用本地LLM进行简单应答，不传入persona配置
    输出将由底座LLM（GLM API）应用persona后生成最终回复
    """

    name = "local_llm"

    def __init__(
        self,
        local_llm: LLMInterface,
    ):
        """
        初始化本地LLM步骤

        Args:
            local_llm: 本地LLM引擎（无system prompt）
        """
        super().__init__()
        self.local_llm = local_llm

        # 注意：system_prompt应该在ServiceContext.init_local_llm()中已经清空
        # 这里不需要再次调用set_system_prompt()

        logger.info(f"[LocalLLMStep] 初始化完成")

    async def process(self, context: PipelineContext) -> None:
        """
        处理Pipeline上下文

        Args:
            context: Pipeline上下文
        """
        if not context.text:
            logger.debug("[LocalLLMStep] 文本为空，跳过")
            return

        original_text = context.text

        try:
            logger.info(f"[LocalLLMStep] 📥 用户输入: {original_text}")
            logger.info(f"[LocalLLMStep] 🔄 正在调用LocalLLM生成简单应答...")

            # 调用LocalLLM生成简单应答（非流式）
            simple_response = await self.local_llm.chat(original_text)

            if simple_response:
                # 将LocalLLM的输出保存到metadata，供后续步骤使用
                context.metadata["local_llm_response"] = simple_response
                context.text = simple_response  # 更新context.text为LocalLLM的输出

                logger.info(f"[LocalLLMStep] ✅ LocalLLM应答完成")
                logger.info(f"[LocalLLMStep] 📤 LocalLLM输出: {simple_response}")
                logger.info(f"[LocalLLMStep] 📊 输出长度: {len(simple_response)} 字符")
            else:
                logger.warning("[LocalLLMStep] LocalLLM输出为空，使用原始输入")

        except Exception as e:
            logger.error(f"[LocalLLMStep] ❌ LocalLLM调用失败: {e}")
            logger.warning(f"[LocalLLMStep] 使用原始输入")
            # 失败时使用原始输入，不影响后续流程
            context.metadata["local_llm_error"] = str(e)
