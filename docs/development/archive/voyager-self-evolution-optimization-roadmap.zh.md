# Voyager 自进化系统优化 Roadmap

> 创建日期：2026-06-28
> 状态：规划中（未实施）
> 关联：[Voyager 生态调研](voyager-landscape-research.zh.md) ｜ [Minecraft 机器人架构](minecraft-bot-architecture.zh.md)
> 产物性质：**优化路线图**，记录全部优化项的内容与动机；后续按"change 拆分建议"逐个落地为 OpenSpec change，不在本文档直接实施。

---

## 1. 背景与定位

[Voyager 生态调研](voyager-landscape-research.zh.md) 的结论表明：本项目 `src/animetta/tools/minecraft/` 已是一套**接近完整的 Voyager 自研复刻 + 工程增强**（curriculum / skill library / verifier / code_generator / sandbox eval_code / self_evolution 全齐，verifier 双闸比官方纯 LLM 更省，self_evolution 已用 DeepSeek 不绑 GPT-4）。因此本 roadmap **不是"对照官方补差距"**，而是针对深挖中暴露的**真实瓶颈**做有优先级的优化。

最关键的发现（不在传统的"对标差距"里）：`self_evolution.py` 的 **give 材料补全**会污染 `verifier` 判断，使系统学到"假技能"。这是全 roadmap 的 P0。

## 2. 组织方式与模板

按**四个主题**分组（学习有效性 / 检索能力 / 评估能力 / 可维护性），每个优化项使用统一模板：

> **现状** → **问题** → **动机** → **方案** → **优先级** → **验收** → **后续 change** → **风险**

主题分组让逻辑内聚；优先级在每项内标注，并在第 7 节汇总成实施顺序。

---

## 3. 🔴 主题一：学习有效性（Learning Integrity）

### 3.1 移除 give 补全污染，恢复纯净学习环境

- **现状**：`self_evolution.py` 在每轮检测到 `task.success_criteria` 里的 `has_<item> >= N`，当 `0 < have < target` 且 `have >= target/5` 时，调用 `_rcon(f"give AnimettaBot minecraft:{item} {need}")` 直接补齐材料。代码注释自述"放宽禁作弊，避免无限找不到"。
- **问题**：give 之后 inventory 达标，`verify()` 的**闸1（确定性 inventory 检查）会立即判通过**，于是 `generate_with_iteration` 产出的 code-body skill 被 `to_skill()` 标记 `validated=True` 存入 `SkillLibrary`。但这些 skill **从未在"正常采集"下真正成功过**——真实运行时会失败。系统学到的是"假技能"，且会污染后续 `search_skills` 的检索结果（假技能被当作 reference 注入 code_generator prompt）。
- **动机**：论文 *Self-Verification* 的前提是**环境不插手**，agent 通过自身代码与环境交互完成任务，verifier 才能据此判断"代码是否真的有效"。give 补全破坏了"`validated` skill = 可靠可复用"这条**整个自进化系统的信任契约**。一旦契约失效，skill library 的累积学习失去意义——这是比"缺 embedding"重要一个数量级的问题，因此排 P0。
- **方案**：采用**默认关闭的开关**而非硬删除（工程稳健性）。
  1. 引入开关 `MC_EVO_ALLOW_GIVE`（环境变量 / config），**默认 `False`**。学习/生产模式下 give 分支永不执行。
  2. 仅当显式开启时才允许 give（保留调试能力，便于日后复现卡死场景）。
  3. 开关状态写入 `data/mc_evo_state.json` 日志，保证可追溯（某个 validated skill 是在纯净还是 give 模式下产生的）。
  4. **历史净化**：对库中已存的 `validated=True` skill，跑一次"关闭 give + 正常采集"复验；复现失败的降级为 `validated=False` 或交由现有 `SkillLibrary.cleanup()` 淘汰。
  5. 卡死兜底交给既有机制：curriculum 降级出题 / `SAME_TASK_LIMIT=10` 连续同任务即停 / `MAX_ROUNDS=60` 上限。
- **优先级**：**P0**（最高）
- **验收**：
  - 一轮 self_evolution 在 `MC_EVO_ALLOW_GIVE=False` 下跑完，新入库的每个 `validated=True` skill，在"无 give + 正常采集"独立重放下仍能成功。
  - 历史假技能被复验清理或降级。
  - evo_state 日志记录每轮 give 开关状态。
- **后续 change**：`mc-evo-purity`（独立、最小、第一个做）
- **风险**：关闭 give 后"找不到 X"概率上升，learning stall 增多 → 必须同步确认 `curriculum.next_task` 的降级出题能力足够（见 3.1 风险缓释：若 stall 率 > 阈值，需配合 curriculum 改进，但那属于另一个 change）。

---

## 4. 🟢 主题二：检索能力（Retrieval）

### 4.1 embedding 向量检索（条件触发型）

- **现状**：`catalog.py::SkillLibrary` 提供四种检索——`search_skills(goal)`（词袋命中计分）/ `search_by_keyword`（name×2 + desc + tags×2 加权）/ `search_by_tags`（tag overlap）/ `match_skills`（precondition 全满足 + 按 success_rate 排序）。当前规模 `predefined(15) + code_seeds(1) = 16` 条种子 + 若干 learned。
- **问题**：**当前无问题**。16 条规模下，词袋 + precondition + 加权评分完全够用。规模上到 50+ 后，词袋的召回率与语义匹配能力会明显弱于 embedding。
- **动机**：embedding 检索是论文 Voyager skill library 的核心卖点之一（description 向量索引、跨任务复用）。但它有**临界规模**——规模不够时收益盖不住引入向量库的复杂度。本项目 `memory/` 已在用 Chroma，复用成本低，但"低成本"不等于"现在就该做"。
- **方案**：**条件触发**——当 learned skill 积累到 **> 50 条**时启动：复用 `memory/` 的 Chroma 给 `Skill.description` 建索引，新增 `search_by_embedding(goal, k)`；保留现有词袋/keyword 作为 fallback（embedding 召回为空或冷启动时用）。与 `SkillLibrary.cleanup()`（成功率<0.3 且 ≥10 次淘汰）配合，控制库规模与质量。
- **优先级**：**P2**（条件触发，**现在不做**）
- **验收**：`N ≥ 50` 时，对一组测试 goal 的 top-k 召回准确率显著优于纯词袋；冷启动/空召回时正确回退到词袋。
- **后续 change**：`mc-skill-embedding`（延后，排在最后）
- **风险**：过早做即**过度工程**；与 `cleanup()` 的质量淘汰功能部分目标重叠（后者解决"质量"，embedding 解决"规模下的召回"），需明确边界避免重复治理。

---

## 5. 🟡 主题三：评估能力（Evaluation）

### 5.1 对齐 Odyssey benchmark 方法论

- **现状**：`benchmark/` 已有骨架（`scenarios.py` / `models.py` / `report.py` / `runner.py`），但任务集为自定义，无法与外部工作横向对比，也缺乏标准化维度来量化 agent 进步。
- **问题**：缺标准化评估，难以回答"我的 agent 到底多强、改进了多少、和社区比如何"。
- **动机**：[Odyssey](https://github.com/zju-vipa/odyssey)（IJCAI 2025, [arXiv:2407.15325](https://arxiv.org/abs/2407.15325)）是 Voyager 最活跃后继，其三类任务——**长程规划（long-term planning）/ 动态即时规划（dynamic-immediate planning）/ 自主探索（autonomous exploration）**——已成为 Minecraft LLM agent 社区的事实评估标准。**只借评估方法论，不移植 skill、不走 fine-tune**：Odyssey 的 fine-tuned LLaMA-3 路线与本项目"LangGraph 编排通用 LLM（DeepSeek 等）"的轻量路线**正交**，强行对齐模型层得不偿失。
- **方案**：在 `benchmark/` 新增对齐 Odyssey 三类任务的场景定义与指标产出（任务规格对齐，指标口径对齐并注明路线差异）。复用现有 `TechTreeMetrics` / `RunReport` 报告管道。
- **优先级**：**P1**
- **验收**：能产出与 Odyssey 三类任务口径一致的指标；报告显式注明"路线差异，不直接数值对比"。
- **后续 change**：`mc-benchmark-odyssey`
- **风险**：Odyssey 用 fine-tuned 模型，绝对数值不可直接对比 → 报告须标注；三类任务的精确定义需对照 Odyssey 论文/仓库核实，避免主观臆造。

---

## 6. 🟡 主题四：可维护性（Maintainability）

### 6.1 文档化 step vs code-body 选型标准

- **现状**：`executor.py` 以单一分支点 `if body.get("type") == "code"` 区分两种 skill 形态，但"何时该用 step skill / 何时该用 code-body skill"的选型规则，目前只散落在 `code_seeds.py` 顶部注释，未进入架构文档。
- **问题**：后续维护者无显式规则可循，容易误选型（例如把本该稳定的流程写成脆弱的 LLM 代码，或把本该涌现的任务硬塞进步骤序列）。
- **动机**：这是本项目相对**官方纯 code（Voyager）与 GITM 纯文本动作**的核心设计折中——**step skill** 锁定"已知可靠的操作序列"（14 种原子动作，可校验、可重试、安全），**code-body skill** 保留"未知/复杂任务的涌现空间"（LLM 生成 JS 走 sandbox）。这个折中是架构层面的有意决策，值得显式化，避免随维护侵蚀。
- **方案**：在 [`minecraft-bot-architecture.zh.md`](minecraft-bot-architecture.zh.md) 的 skill 章节补充"选型标准 + 正反例"小节。
- **优先级**：**P1**（轻量、零代码风险）
- **验收**：architecture 文档含明确选型规则（如"流程可枚举为原子动作且需高可靠 → step；需条件分支/探索/step 表达不了 → code-body"）+ 至少一组正反例。
- **后续 change**：`mc-skill-form-docs`（纯文档）
- **风险**：无。

### 6.2（可选）参考 Odyssey skill 清单补 predefined

- **现状**：`predefined.py` 共 15 条，集中在生存科技树（伐木 → 木/石/铁镐 → 装备/建筑）。
- **动机**：Odyssey 的 183 compositional skills 是现成的技能参考库。
- **方案**：**仅在项目目标扩展到"金装备/生存之外"时**，按形态对齐（step / code-body）按需移植，避免盲目搬运。
- **优先级**：**低**（条件触发）
- **风险**：形态或目标不对齐时，盲目移植只会给库增加噪音（且触发 4.1 所述 embedding 临界点的提前到来）。

---

## 7. change 拆分与实施顺序

每个优化项对应一个独立 OpenSpec change，按依赖与风险排序：

| 顺序 | change | 主题 | 大小 | 依赖 |
| --- | --- | --- | --- | --- |
| 1 | `mc-evo-purity` | 学习有效性 | 小（开关 + 复验 + 测试） | 无 |
| 2 | `mc-skill-form-docs` | 可维护性 | 小（纯文档） | 无 |
| 3 | `mc-benchmark-odyssey` | 评估能力 | 中 | 无（但 1 完成后评估更可信） |
| 4 | `mc-skill-embedding` | 检索能力 | 中 | learned skill > 50 条触发 |

**顺序动机**：
- `mc-evo-purity` 第一个：命门、独立、最小，且不解决它后续学习都不可信。
- `mc-skill-form-docs` 紧随：零风险、几乎零成本，顺手固化设计意图。
- `mc-benchmark-odyssey` 排第三：有了纯净学习（change 1）后，benchmark 结果才有意义。
- `mc-skill-embedding` 最后：条件触发，未达规模不做。

## 8. YAGNI｜明确不做

- ❌ **现在就上 embedding**——规模 16 条，过度工程。
- ❌ **盲目移植 Odyssey 183 skill 清单**——形态/目标未对齐，增噪。
- ❌ **走 Odyssey fine-tune LLaMA-3 路线**——与本项目 LangGraph + 通用 LLM 正交，得不偿失。
- ❌ **把多项合并成一个大 change**——违背 OpenSpec 单 change 聚焦原则，也违背 YAGNI。

---

## 附录 A：决策记录

| 决策点 | 选项 | 选择 | 动机 |
| --- | --- | --- | --- |
| 产出形态 | P0 单点 / P0+文档合并 / 完整 roadmap / 全打包 | **完整 roadmap** | 先记录全貌与动机，后续再拆 change |
| give 补全定位 | 临时 debug 应关 / 长期 fallback 加开关 / 不确定 | **临时 debug，应关闭** | 注释自述"放宽禁作弊"，学习必须纯净 |
| P0 实施方式 | 硬删除 / 默认关闭开关 | **默认关闭开关 + 历史复验** | 满足"学习纯净"且不丢调试能力、可追溯 |
| roadmap 结构 | 优先级分级 / 主题分组 / 时间阶段 | **主题分组 + 统一模板** | 逻辑内聚，主题内再标优先级 |
