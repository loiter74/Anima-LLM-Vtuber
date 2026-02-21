#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""音频输出测试脚本"""

import sys
import os
import asyncio

# 添加 src 到 Python 路径
script_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(script_dir, 'src')
sys.path.insert(0, src_dir)

from anima.config.app import AppConfig
from anima.service_context import ServiceContext
from loguru import logger
import yaml

async def test_tts():
    """测试 TTS 服务"""
    print("=" * 50)
    print("音频输出测试")
    print("=" * 50)

    # 加载配置
    config_path = os.path.join(script_dir, 'config', 'config.yaml')
    with open(config_path, 'r', encoding='utf-8') as f:
        config_data = yaml.safe_load(f)
    app_config = AppConfig(**config_data)

    print(f"\n[配置]")
    print(f"  TTS: {app_config.services.tts}")
    print(f"  LLM: {app_config.services.agent}")

    # 创建服务上下文
    print(f"\n[1/3] 初始化服务...")
    service_context = ServiceContext()
    await service_context.load_from_config(app_config)

    print(f"  ✅ TTS 服务已加载: {type(service_context.tts).__name__}")
    print(f"  ✅ LLM 服务已加载: {type(service_context.agent).__name__}")

    # 测试 LLM
    test_text = "你好，我是AI助手。"
    print(f"\n[2/3] 测试 LLM 生成文本...")
    print(f"  输入: {test_text}")

    try:
        full_response = ""
        async for chunk in service_context.agent.chat_stream(test_text):
            full_response += chunk
            print(f"  生成: {chunk}", end="", flush=True)

        print(f"\n  ✅ LLM 响应: {full_response}")

        # 测试 TTS
        print(f"\n[3/3] 测试 TTS 生成音频...")
        output_path = os.path.join(script_dir, "test_output.mp3")

        result = await service_context.tts.synthesize(full_response, output_path)
        print(f"  ✅ 音频已生成: {result}")

        if result and os.path.exists(result):
            file_size = os.path.getsize(result)
            print(f"  文件大小: {file_size} bytes")
            print(f"\n[完成] ✅ 所有测试通过！")
            print(f"  可以播放音频文件: {result}")
        else:
            print(f"\n[错误] ❌ 音频文件不存在")

    except Exception as e:
        print(f"\n[错误] ❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        await service_context.close()

    return True

if __name__ == "__main__":
    success = asyncio.run(test_tts())
    sys.exit(0 if success else 1)
