"""
下载中文测试语音
从公开的语音数据集或 API 获取真实的中文语音样本
"""

import os
import requests
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
TEST_AUDIO_DIR = PROJECT_ROOT / "test_audio"

# 创建测试音频目录
TEST_AUDIO_DIR.mkdir(exist_ok=True)

def download_with_requests(url, output_path):
    """使用 requests 下载文件"""
    try:
        print(f"正在下载: {url}")
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        with open(output_path, 'wb') as f:
            f.write(response.content)

        print(f"✅ 下载成功: {output_path}")
        print(f"   文件大小: {len(response.content)} 字节")
        return True
    except Exception as e:
        print(f"❌ 下载失败: {e}")
        return False

def download_chinese_test_audio():
    """下载中文测试语音"""

    print("=" * 60)
    print("中文测试语音下载工具")
    print("=" * 60)
    print()

    # 方案 1: 从 Mozilla Common Voice 下载（中文样本）
    # 使用 GitHub 上的公开中文语音样本
    test_files = [
        {
            "name": "chinese_test_sample.wav",
            "url": "https://github.com/PaddlePaddle/PaddleSpeech/raw/develop/paddlespeech/t2s/exps/ge2e/audio/00001.wav",
            "description": "中文语音样本（PaddleSpeech 示例）"
        },
        {
            "name": "chinese_male.wav",
            "url": "https://raw.githubusercontent.com/wisdomfy/Chinese-Voice-Cloning/main/audio_samples/chinese_male.wav",
            "description": "中文男声样本"
        },
        {
            "name": "chinese_female.wav",
            "url": "https://raw.githubusercontent.com/wisdomfy/Chinese-Voice-Cloning/main/audio_samples/chinese_female.wav",
            "description": "中文女声样本"
        }
    ]

    # 方案 2: 使用 edge-tts 生成中文语音（推荐）
    print("方案 1: 尝试从网络下载中文语音样本...")
    print("-" * 60)

    downloaded = []
    for file_info in test_files:
        output_path = TEST_AUDIO_DIR / file_info["name"]
        if download_with_requests(file_info["url"], output_path):
            downloaded.append(output_path)
            print(f"   描述: {file_info['description']}")
            print()

    if not downloaded:
        print("⚠️ 网络下载失败，尝试使用 edge-tts 生成...")
        print("-" * 60)

        # 方案 2: 使用 edge-tts 本地生成
        try:
            import edge_tts

            async def generate_with_edge_tts():
                """使用 edge-tts 生成中文语音"""
                test_texts = [
                    ("你好，我是人工智能助手，很高兴认识你。", "chinese_greeting.mp3"),
                    ("今天天气真不错，我们可以聊聊天。", "chinese_chat.mp3"),
                    ("语音识别技术正在快速发展。", "chinese_tech.mp3"),
                ]

                generated = []
                for text, filename in test_texts:
                    output_path = TEST_AUDIO_DIR / filename
                    print(f"正在生成: {filename}")
                    print(f"   文本: {text}")

                    communicate = edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural")
                    await communicate.save(str(output_path))

                    print(f"✅ 生成成功: {output_path}")
                    print(f"   文件大小: {output_path.stat().st_size} 字节")
                    print()
                    generated.append(output_path)

                return generated

            import asyncio
            downloaded = asyncio.run(generate_with_edge_tts())

        except ImportError:
            print("❌ edge-tts 未安装")
            print("   安装方法: pip install edge-tts")
        except Exception as e:
            print(f"❌ 生成失败: {e}")

    # 总结
    print("=" * 60)
    print("下载完成！")
    print("=" * 60)
    print(f"测试音频目录: {TEST_AUDIO_DIR}")
    print()

    if downloaded:
        print("可用的测试音频文件:")
        for i, path in enumerate(downloaded, 1):
            print(f"  {i}. {path.name}")

        print()
        print("💡 使用方法:")
        print("   在浏览器控制台执行以下代码播放并测试:")
        print()
        for path in downloaded:
            if path.suffix == '.wav':
                print(f"   // 播放 {path.name}")
                print(f"   const audio = new Audio('/test_audio/{path.name}')")
                print(f"   audio.play()")
                print()
    else:
        print("⚠️ 未能下载任何测试文件")
        print()
        print("手动下载建议:")
        print("  1. 访问: https://www.voiptroubleshooter.com/open_speech/zh.html")
        print("  2. 下载中文语音样本")
        print("  3. 保存到:", TEST_AUDIO_DIR)

if __name__ == "__main__":
    download_chinese_test_audio()
