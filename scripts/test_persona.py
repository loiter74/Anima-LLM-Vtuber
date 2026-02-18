"""测试人设加载功能"""
import sys
sys.path.insert(0, '.')

from anima.config import PersonaConfig, AppConfig

print("=" * 60)
print("测试 1: 加载 neuro-vtuber 人设")
print("=" * 60)

persona = PersonaConfig.load("neuro-vtuber")
print(f"名称: {persona.name}")
print(f"角色: {persona.role}")
print(f"性格特征数量: {len(persona.personality.traits)}")
print(f"常用 Emoji: {' '.join(persona.common_emojis)}")

print("\n" + "=" * 60)
print("生成的系统提示词预览 (前 1500 字符):")
print("=" * 60)
prompt = persona.build_system_prompt()
print(prompt[:1500])
print("\n... (截断)")

print("\n" + "=" * 60)
print("测试 2: 通过 AppConfig 加载")
print("=" * 60)

config = AppConfig()
config.persona_name = "neuro-vtuber"
system_prompt = config.get_system_prompt()
print(f"系统提示词长度: {len(system_prompt)} 字符")

print("\n" + "=" * 60)
print("测试 3: 加载默认人设")
print("=" * 60)

default_persona = PersonaConfig.load("default")
print(f"默认人设名称: {default_persona.name}")
print(f"默认人设角色: {default_persona.role}")

print("\n✅ 所有测试通过!")