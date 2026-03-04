"""
部署 LoRA 模型到 Anima 系统
Deploy LoRA Model to Anima System

将微调后的模型集成到 Anima 系统中
"""

import sys
from pathlib import Path

# 添加 src 到路径
src_dir = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_dir))


def deploy_to_anima(
    lora_path: str,
    config_file: str = "config/services/llm/local_lora.yaml"
):
    """
    部署到 Anima 系统

    Args:
        lora_path: LoRA 模型路径
        config_file: 配置文件路径
    """
    print("=" * 80)
    print("部署 LoRA 模型到 Anima")
    print("=" * 80)

    # 1. 检查 LoRA 模型
    print("\n[步骤 1] 检查 LoRA 模型")
    print("-" * 80)

    lora_dir = Path(lora_path)
    if not lora_dir.exists():
        print(f"错误: LoRA 模型不存在: {lora_path}")
        print("\n请先训练模型:")
        print("  python scripts/training/quick_train.py")
        return False

    print(f"OK - LoRA 模型存在: {lora_path}")

    # 检查必要文件
    required_files = [
        "adapter_config.json",
        "adapter_model.safetensors"  # 或 adapter_model.bin
    ]

    for file in required_files:
        file_path = lora_dir / file
        if not file_path.exists():
            print(f"警告: 缺少文件 {file}")

    # 2. 更新配置文件
    print("\n[步骤 2] 更新配置文件")
    print("-" * 80)

    config_path = Path(config_file)
    if not config_path.exists():
        print(f"警告: 配置文件不存在: {config_file}")
        print("使用默认配置")

    import yaml

    # 读取配置
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    # 更新 LoRA 路径
    config['lora_path'] = str(lora_dir.absolute())

    # 保存配置
    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, allow_unicode=True)

    print(f"OK - 配置已更新: {config_file}")
    print(f"  lora_path: {config['lora_path']}")

    # 3. 测试加载
    print("\n[步骤 3] 测试模型加载")
    print("-" * 80)

    try:
        from anima.services.llm.implementations.local_lora_llm import LocalLoraLLM

        llm = LocalLoraLLM(
            base_model_name=config.get("base_model_name", "Qwen/Qwen2.5-7B-Instruct"),
            lora_path=str(lora_dir.absolute()),
            device=config.get("device", "cuda")
        )

        # 加载模型
        llm.load_model()

        print("OK - 模型加载成功")

    except Exception as e:
        print(f"错误: 模型加载失败: {e}")
        return False

    # 4. 测试推理
    print("\n[步骤 4] 测试推理")
    print("-" * 80)

    test_prompts = [
        "你喜欢什么游戏？",
        "你今天心情怎么样？"
    ]

    try:
        import asyncio

        async def test_inference():
            responses = []
            for prompt in test_prompts:
                print(f"\n提示词: {prompt}")

                # 流式测试
                response_parts = []
                async for chunk in llm.chat_stream(prompt):
                    response_parts.append(chunk)

                response = "".join(response_parts)
                print(f"回复: {response[:100]}...")

                responses.append(response)

            return responses

        responses = asyncio.run(test_inference())

        print("\nOK - 推理测试通过")

    except Exception as e:
        print(f"错误: 推理测试失败: {e}")
        return False

    # 5. 更新主配置
    print("\n[步骤 5] 更新主配置文件")
    print("-" * 80)

    main_config_path = Path("config/config.yaml")

    try:
        with open(main_config_path, 'r', encoding='utf-8') as f:
            main_config = yaml.safe_load(f)

        # 更新 LLM 提供商
        main_config['services']['llm'] = 'local_lora'

        # 保存
        with open(main_config_path, 'w', encoding='utf-8') as f:
            yaml.dump(main_config, f, allow_unicode=True)

        print(f"OK - 主配置已更新")
        print(f"  LLM 提供商: local_lora")

    except Exception as e:
        print(f"警告: 主配置更新失败: {e}")

    # 完成
    print("\n" + "=" * 80)
    print("部署完成！")
    print("=" * 80)

    print(f"\nLoRA 模型已成功集成到 Anima 系统")
    print(f"\n下一步:")
    print(f"  1. 重启 Anima 服务器")
    print(f"  2. 开始与 Neuro-sama 对话")
    print(f"  3. 观察微调后的效果")

    print(f"\n如需切换回基座模型:")
    print(f"  编辑 config/config.yaml")
    print(f"  将 llm: local_lora 改为 llm: glm")

    return True


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="部署 LoRA 模型到 Anima")
    parser.add_argument(
        "--lora-path",
        type=str,
        required=True,
        help="LoRA 模型路径"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config/services/llm/local_lora.yaml",
        help="配置文件路径"
    )

    args = parser.parse_args()

    success = deploy_to_anima(
        lora_path=args.lora_path,
        config_file=args.config
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
