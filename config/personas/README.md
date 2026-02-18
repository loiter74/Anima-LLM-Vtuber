# 人设配置 (Personas)

此目录包含 LLM 角色人设配置文件。

## 使用方法

### 在主配置中指定人设

```yaml
# config/config.yaml
profile: "glm"              # 服务配置方案（profiles/ 目录）
persona: "neuro-vtuber"     # 人设配置（personas/ 目录）
```

### 通过代码加载

```python
from anima.config import AppConfig, PersonaConfig

# 方式1：通过 AppConfig
config = AppConfig.load()
system_prompt = config.get_system_prompt()

# 方式2：直接加载人设
persona = PersonaConfig.load("neuro-vtuber")
prompt = persona.build_system_prompt()
```

## 可用人设

| 文件 | 名称 | 说明 |
|------|------|------|
| `default.yaml` | Anima | 默认友好助手 |
| `neuro-vtuber.yaml` | Neuro | VTuber 风格（毒舌、可爱、混沌） |

## 创建自定义人设

复制 `default.yaml` 并修改：

```yaml
name: "MyBot"
role: "自定义角色"

identity: |
  你是...

personality:
  traits:
    - "特征1"
    - "特征2"
  speaking_style:
    - "风格1"
  catchphrases:
    - "口头禅"

behavior:
  forbidden_phrases:
    - "禁止说的话"
  response_to_praise: "面对夸奖的反应"
  response_to_criticism: "面对批评的反应"

emoji_style: "Emoji 使用规则"
common_emojis:
  - "😊"
  - "👍"

examples:
  - user: "问题"
    ai: "回答"
```

## 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 角色名称 |
| `role` | string | 角色定位 |
| `identity` | string | 核心身份描述（最重要） |
| `personality.traits` | list | 性格特征列表 |
| `personality.speaking_style` | list | 说话风格 |
| `personality.catchphrases` | list | 口头禅/常用语 |
| `behavior.forbidden_phrases` | list | 禁止使用的短语 |
| `emoji_style` | string | Emoji 使用规则 |
| `common_emojis` | list | 常用 Emoji |
| `examples` | list | 对话示例 |