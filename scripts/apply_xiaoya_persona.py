"""
快速切换到小雅人设
"""

import sys
from pathlib import Path

# 添加 src 到路径
src_dir = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_dir))


def apply_xiaoya_persona():
    """应用小雅人设"""

    print("=" * 60)
    print("应用小雅人设")
    print("=" * 60)

    # 1. 检查人设文件是否存在
    persona_path = Path(__file__).parent.parent / "config" / "personas" / "xiaoya.yaml"

    if not persona_path.exists():
        print(f"❌ 人设文件不存在: {persona_path}")
        return False

    print(f"✅ 找到人设文件: {persona_path}")

    # 2. 修改config.yaml
    config_path = Path(__file__).parent.parent / "config" / "config.yaml"

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 替换persona设置
        if "persona:" in content:
            new_content = content.sub(
                r'persona:\s*\S+',
                'persona: "xiaoya"'
            )
        else:
            # 添加persona设置
            new_content = content + '\n\npersona: "xiaoya"'

        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(new_content)

        print(f"✅ 已更新配置文件: {config_path}")
        print(f"   persona: xiaoya")

    except Exception as e:
        print(f"❌ 更新配置文件失败: {e}")
        return False

    # 3. 测试人设加载
    try:
        from anima.config.enhanced_persona import EnhancedPersonaBuilder

        builder = EnhancedPersonaBuilder.from_yaml("xiaoya")
        system_prompt = builder.build_system_prompt()

        print(f"\n✅ 人设加载成功！")
        print(f"\n系统提示词预览（前500字符）:")
        print("-" * 60)
        print(system_prompt[:500] + "...")
        print("-" * 60)

    except Exception as e:
        print(f"❌ 人设加载失败: {e}")
        print(f"\n请检查是否安装了必要的依赖:")
        print(f"pip install pyyaml")

    # 4. 完成提示
    print("\n" + "=" * 60)
    print("✅ 小雅人设已应用！")
    print("=" * 60)
    print("\n下一步：")
    print("1. 重启服务器: python -m anima.socketio_server")
    print("2. 与小雅对话，感受鲜明的个性！")
    print("\n示例对话：")
    print("  你: 你好")
    print("  小雅: 嘿嘿~ 你好呀！今天想聊点什么？")
    print("  你: 我心情不好")
    print("  小雅: 诶？怎么啦？发生什么事了吗？别难过，我会陪着你的...")

    return True


if __name__ == "__main__":
    success = apply_xiaoya_persona()
    sys.exit(0 if success else 1)
