"""
Persona Enhancement Step
性格增强步骤 - 使用快速LLM优化用户输入，增强性格表现
"""

from typing import Optional
from loguru import logger

from ..base import PipelineStep
from ...core.context import PipelineContext
from ...services.llm.interface import LLMInterface


class PersonaEnhancementStep(PipelineStep):
    """
    性格增强步骤

    使用快速的LLM（如GLM API）优化用户输入，使其更符合AI性格设定

    功能：
    1. 分析用户意图和情感
    2. 添加相关的上下文信息
    3. 优化表达方式，引导AI以更符合性格的方式回复
    """

    name = "persona_enhancement"

    def __init__(
        self,
        optimizer_llm: LLMInterface,
        persona_name: str = "neuro-vtuber"
    ):
        """
        初始化性格增强步骤

        Args:
            optimizer_llm: 优化器LLM（建议使用快速的API LLM）
            persona_name: 人设名称
        """
        super().__init__()
        self.optimizer_llm = optimizer_llm
        self.persona_name = persona_name

        # 人设优化提示词模板
        self.system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        """构建优化器的系统提示词"""
        return f"""你是一个专业的对话优化助手，负责优化用户输入，使AI助手（{self.persona_name}）能够以更符合其性格的方式回复。

你的任务：
1. 分析用户的意图和情感
2. 识别需要AI关注的关键信息
3. 优化表达方式，但不要改变用户的原意
4. 添加适当的上下文引导（如果需要）

输出格式：
直接输出优化后的用户输入，不要添加任何解释、注释或额外内容。

示例：
用户输入: "你好"
优化输出: "你好呀！很高兴见到你！"

用户输入: "今天天气不错"
优化输出: "今天天气真好呢！你有没有出门走走？"

注意：
- 保持简洁，不要过度修改
- 保持自然对话风格
- 适当增加亲和力
"""

    async def process(self, context: PipelineContext) -> None:
        """
        处理Pipeline上下文

        Args:
            context: Pipeline上下文
        """
        if not context.text:
            logger.debug("[PersonaEnhancementStep] 文本为空，跳过")
            return

        original_text = context.text

        try:
            logger.debug(f"[PersonaEnhancementStep] 原始输入: {original_text[:100]}...")

            # 使用优化器LLM优化输入
            enhanced_prompt = await self._optimize_prompt(original_text)

            if enhanced_prompt and enhanced_prompt != original_text:
                context.text = enhanced_prompt
                logger.info(f"[PersonaEnhancementStep] ✅ 输入已优化")
                logger.debug(f"[PersonaEnhancementStep] 优化后: {enhanced_prompt[:100]}...")

                # 在元数据中记录原始输入
                context.metadata["original_user_input"] = original_text
                context.metadata["enhanced_by_optimizer"] = True
            else:
                logger.debug("[PersonaEnhancementStep] 输入无需优化")

        except Exception as e:
            logger.warning(f"[PersonaEnhancementStep] 优化失败: {e}")
            logger.warning(f"[PersonaEnhancementStep] 使用原始输入")
            # 优化失败时使用原始输入，不影响后续流程
            context.metadata["enhancement_error"] = str(e)

    async def _optimize_prompt(self, user_input: str) -> Optional[str]:
        """
        调用优化器LLM优化用户输入

        Args:
            user_input: 用户原始输入

        Returns:
            优化后的输入，如果优化失败则返回原始输入
        """
        try:
            # 调用优化器LLM（非流式，因为需要完整结果）
            response_text = ""
            async for chunk in self.optimizer_llm.chat_stream(user_input):
                if isinstance(chunk, str):
                    response_text += chunk
                elif isinstance(chunk, dict):
                    # 处理结构化输出
                    if chunk.get("type") == "sentence":
                        response_text += chunk.get("content", "")

            # 清理响应文本
            enhanced = response_text.strip()

            # 如果响应为空或与原文相同，返回原文
            if not enhanced or enhanced == user_input.strip():
                return user_input

            return enhanced

        except Exception as e:
            logger.error(f"[PersonaEnhancementStep] LLM调用失败: {e}")
            return user_input
