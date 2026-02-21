# -*- coding: utf-8 -*-
"""
使用 edge-tts 生成中文测试语音
简化版本，直接生成 MP3
"""

import asyncio
import edge_tts
from pathlib import Path

# 项目目录
PROJECT_ROOT = Path(__file__).parent.parent
TEST_AUDIO_DIR = PROJECT_ROOT / "frontend" / "public" / "test_audio"
TEST_AUDIO_DIR.mkdir(parents=True, exist_ok=True)

# 测试文本
TEST_CASES = [
    {
        "text": "你好，我是人工智能助手。今天天气真不错，我们可以聊聊天吗？",
        "voice": "zh-CN-XiaoxiaoNeural",
        "filename": "test_chinese_female.mp3"
    },
    {
        "text": "语音识别技术正在快速发展，现在的AI助手已经能听懂中文了。",
        "voice": "zh-CN-YunxiNeural",
        "filename": "test_chinese_male.mp3"
    },
    {
        "text": "测试语音，请问你能听懂我在说什么吗？这是一个语音识别的测试。",
        "voice": "zh-CN-XiaoyiNeural",
        "filename": "test_chinese_young.mp3"
    }
]

async def generate_audio(text: str, voice: str, output_path: Path):
    """生成单个语音文件"""
    print(f"正在生成: {output_path.name}")
    print(f"  文本: {text}")
    print(f"  语音: {voice}")

    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(output_path))

        file_size = output_path.stat().st_size
        print(f"  [OK] 成功: {output_path.name} ({file_size} 字节)")
        return True

    except Exception as e:
        print(f"  [ERROR] 失败: {e}")
        return False

async def main():
    """主函数"""
    print("=" * 60)
    print("中文测试语音生成工具")
    print("=" * 60)
    print()

    success_count = 0

    for i, test_case in enumerate(TEST_CASES, 1):
        print(f"[{i}/{len(TEST_CASES)}]")
        output_path = TEST_AUDIO_DIR / test_case["filename"]

        if await generate_audio(
            test_case["text"],
            test_case["voice"],
            output_path
        ):
            success_count += 1
        print()

    print("=" * 60)
    print(f"生成完成! 成功: {success_count}/{len(TEST_CASES)}")
    print("=" * 60)
    print(f"音频保存目录: {TEST_AUDIO_DIR}")
    print()

    # 列出所有文件
    audio_files = list(TEST_AUDIO_DIR.glob("*.mp3")) + list(TEST_AUDIO_DIR.glob("*.wav"))
    if audio_files:
        print("可用的测试音频:")
        for f in sorted(audio_files):
            size = f.stat().st_size
            print(f"  - {f.name} ({size} 字节)")
        print()

        print("在前端使用方法:")
        print("  这些文件已保存到 frontend/public/test_audio/")
        print("  可以直接在浏览器中通过 /test_audio/文件名 访问")
        print()

if __name__ == "__main__":
    # 设置 Windows 控制台编码
    import sys
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    asyncio.run(main())
