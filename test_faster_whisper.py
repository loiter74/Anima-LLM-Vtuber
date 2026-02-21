#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试 Faster-Whisper ASR 配置"""

import sys
import os

# 添加 src 到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

print("=" * 60)
print("Faster-Whisper ASR 测试")
print("=" * 60)

try:
    # 测试配置导入
    from anima.config.providers.asr.faster_whisper import FasterWhisperASRConfig
    print("[OK] 配置类导入成功")

    # 创建配置实例
    config = FasterWhisperASRConfig()
    print(f"[OK] 配置实例创建成功:")
    print(f"   - type: {config.type}")
    print(f"   - model: {config.model}")
    print(f"   - language: {config.language}")
    print(f"   - device: {config.device}")

    # 测试服务类注册
    from anima.services.asr.implementations.faster_whisper_asr import FasterWhisperASR
    print("[OK] 服务类导入成功")

    print("\n" + "=" * 60)
    print("所有测试通过! Faster-Whisper ASR 集成成功!")
    print("=" * 60)

except ImportError as e:
    print(f"[ERROR] 导入错误: {e}")
    sys.exit(1)
except Exception as e:
    print(f"[ERROR] 测试失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
