# meme-roast Specification

## Purpose
梗筛选 AI 反馈生成器——根据用户的选择（好/烂），AI 给出对应风格的点评：标记「好」时赞赏，标记「烂」时吐槽。提升筛选交互的趣味性。

## Requirements

### Requirement: 好梗 AI 赞赏
系统 SHALL 在用户标记梗为「好」时，调用 LLM 生成一条简洁赞赏。

#### Scenario: 赞赏生成
- **WHEN** 梗被标记为 `status: "good"`
- **THEN** 系统 SHALL 构造赞赏 prompt 调用 LLM
- **AND** 赞赏 SHALL 为 15-30 字的中文点评
- **AND** 赞赏 SHALL 指出这个梗为什么好（如：双关巧妙、反讽精准、时机恰当）
- **AND** 赞赏 SHALL 符合 AI VTuber 人设（理性、冷幽默）

#### Scenario: 赞赏风格约束
- **WHEN** LLM 生成赞赏
- **THEN** 禁止使用 "呀、哦、啦、嘛、呢、呗、哟" 等语气词
- **AND** 保持 AI 观察者视角，避免过度热情

### Requirement: 烂梗 AI 吐槽
系统 SHALL 在用户标记梗为「烂」时，调用 LLM 生成一条调侃式吐槽。

#### Scenario: 吐槽生成
- **WHEN** 梗被标记为 `status: "bad"`
- **THEN** 系统 SHALL 构造吐槽 prompt 调用 LLM
- **AND** 吐槽 SHALL 为 20-40 字的中文调侃
- **AND** 吐槽 SHALL 包含对梗问题的具体指出（而非泛泛的"不好笑"）

#### Scenario: 吐槽风格约束
- **WHEN** LLM 生成吐槽
- **THEN** 吐槽 SHALL 一针见血地指出梗的问题
- **AND** 禁止使用 "呀、哦、啦、嘛、呢、呗、哟" 等语气词
- **AND** 保持 AI 观察者视角

### Requirement: 反馈生成失败降级
系统 SHALL 在 LLM 调用失败时使用预设模板降级。

#### Scenario: LLM 调用失败
- **WHEN** LLM API 返回错误或超时
- **THEN** 系统 SHALL 根据 `status` 从对应预设模板中随机选择
- **AND** 记录 warning 日志

#### Scenario: 好梗降级模板
- **WHEN** 好梗降级模式激活
- **THEN** 系统 SHALL 从以下模板中选择：
  - "这个梗的幽默结构完整，可以收入数据库。"
  - "双关/反讽/荒诞机制运作正常——通过。"
  - "数据支持：此梗具备传播潜力。"
  - "逻辑链完整，笑点部署合理——合格。"
  - "这个观察角度不错，值得保留。"

#### Scenario: 烂梗降级模板
- **WHEN** 烂梗降级模式激活
- **THEN** 系统 SHALL 从以下模板中选择：
  - "这个梗的幽默密度≈真空，建议回炉重造。"
  - "数据表明：此梗笑点缺失，情感共鸣为零。"
  - "算法分析结果：该梗需要更多人类智慧注入。"
  - "统计显示，此梗的传播系数接近于零——它不配。"
  - "我的训练数据里，这类梗属于噪声样本。"
  - "冷到连我的散热系统都不用工作了。"

### Requirement: 反馈内容存储
系统 SHALL 将生成的反馈文本关联到梗记录中。

#### Scenario: 反馈存储
- **WHEN** 反馈（赞赏或吐槽）生成完成
- **THEN** 系统 SHALL 将反馈文本存入 Meme 的 `cognitive_analysis.roast` 字段
- **AND** 反馈随 Meme 一起持久化到 Wiki
