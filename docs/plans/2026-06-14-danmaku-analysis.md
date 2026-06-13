# 弹幕数据分析计划

**创建时间**: 2026-06-14
**状态**: 进行中

## 目标

对1000条B站弹幕进行笑点类型分类，用于训练数据和直播模拟。

## 当前进度

| 阶段 | 状态 | 说明 |
|------|------|------|
| 数据收集 | ✅ 完成 | 从王老菊、稚嫩的魔法师等UP主收集1000条弹幕 |
| 前70条分析 | ✅ 完成 | 使用mimo模型精确分析 |
| 后930条分析 | ⏳ 待执行 | 需要用glm模型分析 |

## 数据文件

- **原始数据**: `data/training/danmaku_up.csv` (1000条)
- **分析结果**: `data/training/danmaku_final.csv` (1000条，前70条精确，后930条规则匹配)

## 分析结果统计（当前）

| humor_type | 数量 | 占比 |
|------------|------|------|
| 其他 | 763 | 76.3% |
| 玩梗 | 150 | 15.0% |
| 夸张 | 56 | 5.6% |
| 反讽 | 14 | 1.4% |
| 谐音 | 12 | 1.2% |
| 自嘲 | 4 | 0.4% |
| 双关 | 1 | 0.1% |

**问题**: "其他"占比过高（76%），因为后930条使用简单关键词匹配。

## 下一步操作

### 重启后用glm分析剩余930条

1. **确认glm配置生效**
   - 检查 `~/.config/opencode/opencode.json` 中的 `zhipuai` provider
   - 检查 `~/.config/opencode/oh-my-openagent.json` 中的 category 映射
   - 重启OpenCode使配置生效

2. **批量分析**
   - 每批50条弹幕
   - 使用 `unspecified-low` category（映射到 `zhipuai/glm-4-flash`）
   - 并行运行5个任务
   - 预计需要19批，约4轮并行

3. **更新CSV**
   - 将glm分析结果写入 `data/training/danmaku_final.csv`
   - 覆盖规则匹配的结果

### 脚本参考

```python
# 读取CSV，提取待分析的弹幕
import csv
with open('data/training/danmaku_up.csv', 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    rows = list(reader)

# 提取第71-1000行（index 70-999）
remaining = rows[70:1000]

# 每50条一批，创建prompt
for batch_idx in range(0, len(remaining), 50):
    batch = remaining[batch_idx:batch_idx+50]
    # 创建prompt...
```

### Prompt模板

```
分析以下50条B站弹幕的笑点类型。

只返回JSON数组，格式：
[{"index": 0, "humor_type": "玩梗"}, ...]

笑点类型选项：双关/谐音/反讽/玩梗/夸张/自嘲/其他

弹幕：
0. {content}
1. {content}
...

只返回JSON数组，不要其他内容。
```

## glm配置状态

已配置，需要重启OpenCode：

```json
// opencode.json - zai-coding-plan provider
"zai-coding-plan": {
  "models": {
    "glm-5.1": { "limit": { "context": 200000, "output": 131072 } },
    "glm-5.1-air": { "limit": { "context": 131000, "output": 131072 } }
  },
  "options": {
    "apiKey": "d870ba2f3c8e4e8586e32fec56d64238.Q5CDQViUAyl0UMPM",
    "baseURL": "https://open.bigmodel.cn/api/coding/paas/v4"
  }
}

// oh-my-openagent.json - category映射
"unspecified-low": { "model": "zai-coding-plan/glm-5.1" }
"quick": { "model": "zai-coding-plan/glm-5.1" }
```

## 验证glm是否工作

重启后运行：
```
task(category="unspecified-low", prompt="回复OK", run_in_background=true)
```

如果成功，继续批量分析。如果失败，回退到mimo。
