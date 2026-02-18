"""测试服务初始化"""
import asyncio
import sys
sys.path.insert(0, '.')

from anima.config import AppConfig
from anima.service_context import ServiceContext


async def test():
    print("=" * 60)
    print("测试服务初始化")
    print("=" * 60)

    # 加载配置
    config = AppConfig.load()
    print(f"ASR: {config.asr.type}")
    print(f"TTS: {config.tts.type}")
    print(f"LLM: {config.agent.llm_config.type}")
    print(f"Persona: {config.persona_name}")

    # 初始化服务上下文（使用 load_from_config 以加载人设）
    ctx = ServiceContext()
    ctx.session_id = "test"
    await ctx.load_from_config(config)
    
    print("✅ 所有服务初始化成功")

    # 测试 Agent
    print("\n" + "=" * 60)
    print("测试对话")
    print("=" * 60)
    
    response = await ctx.agent_engine.chat("你好，请做一下自我介绍。")
    print(f"\n🤖 Agent 响应:\n{response}")

    await ctx.close()
    print("\n✅ 所有测试通过!")


if __name__ == "__main__":
    asyncio.run(test())
