# Voyager 生态调研：官方、社区与本项目实现对照

> 调研日期：2026-06-28
>
> 范围：Voyager（Minecraft LLM 终身学习 agent）的官方实现、主要社区/衍生实现，以及它们与本项目 `src/animetta/tools/minecraft/` 自研 "Voyager 风格" 系统的对照。
>
> **核心结论先行**：本项目已经自研了一套**接近完整的 Voyager 复刻**（curriculum + skill library + verifier + sandbox eval_code 全齐），因此调研的真问题不是"要不要引入 Voyager"，而是"**相对官方原版差在哪、社区版（尤其 Odyssey）有什么能借鉴**"。

---

## 1. Voyager 是什么

**Voyager**（NVIDIA MineDojo 团队，NeurIPS 2023）是首个用 LLM 驱动的、在 Minecraft 中进行**开放式终身学习（open-ended lifelong learning）**的具身 agent。它无需人工干预、不微调模型，靠 GPT-4 持续探索世界、积累技能、做出新发现。

- 论文：[Voyager: An Open-Ended Embodied Agent with Large Language Models (arXiv:2305.16291)](https://arxiv.org/abs/2305.16291)
- 项目页：[voyager.minedojo.org](https://voyager.minedojo.org/)
- 官方代码：[github.com/MineDojo/Voyager](https://github.com/MineDojo/Voyager)

### 架构（重要：和本项目一样）

```
官方 Voyager
┌─────────────────────────────────────────────────────┐
│  Python brain  (GPT-4 + LangChain)                  │
│   ┌───────────────┐ ┌──────────────┐ ┌───────────┐  │
│   │  Automatic    │ │  Skill       │ │  Verifier │  │
│   │  Curriculum   │ │  Library     │ │  (GPT-4   │  │
│   │  (LLM→task)   │ │  (embedding  │ │   judge)  │  │
│   │  开放探索      │ │   retrieve)  │ │           │  │
│   └──────┬────────┘ └──────┬───────┘ └─────┬─────┘  │
│          └────────  JS code skill  ────────┘         │
└────────────────────────┬────────────────────────────┘
                         │ eval(JS)
                     ┌───▼────┐
                     │Mine-   │  ← JS bot
                     │flayer  │
                     └────────┘
```

**关键点**：官方 Voyager 也是「**Python 大脑 + JavaScript bot（Mineflayer）**」的双层架构——和本项目 `core/bridge.py`（Python）+ `bot/index.js`（Node/Mineflayer）的分层**完全一致**。本项目在架构骨架上与官方对齐。

### 三大核心组件

| 组件 | 官方做法 |
| --- | --- |
| **Automatic Curriculum** | LLM 根据当前状态（inventory / 已学技能 / 已完成任务）提出"下一个探索驱动型任务"，目标是**最大化新物品/方块的发现**。一个不断增长的动态 to-do。 |
| **Skill Library** | 一个不断增长的**可执行 JavaScript 代码**（skill）仓库。skill 以其 **description 的 embedding 向量**做索引，支持快速检索与组合。可在全新世界中复用。 |
| **Iterative Prompting + Verifier** | GPT-4 写 JS 代码完成任务；**执行错误反馈循环** + **GPT-4-as-judge verifier** 检查是否达成。失败则带反馈迭代，成功后把 skill 提交进库。 |

---

## 2. 官方实现现状（为什么要看社区版）

- **维护基本停滞**：官方仓库强依赖**旧版 LangChain**，自 `langchain==0.2.0+` 起导入即 break，需手动改用 `langchain-community`（见 [issue #163](https://github.com/MineDojo/Voyager/issues/163)）。这是社区转向 fork/重写的主要原因。
- **强绑定 OpenAI GPT-4**：原版需要 OpenAI API key，不直接支持本地 / 开源 LLM。
- **仍是参考标杆**：尽管代码老旧，论文的三组件设计仍是后续几乎所有 Minecraft LLM agent 的工作起点。

---

## 3. 社区与衍生实现

| 项目 | 类型 | 定位 | 对本项目的价值 |
| --- | --- | --- | --- |
| **[Odyssey](https://github.com/zju-vipa/odyssey)** (zju-vipa) | Voyager 后继 | IJCAI 2025，基于 Voyager 扩展：**40 primitive + 183 compositional skills**、新 agent 能力 benchmark（长程规划 / 动态即时规划 / 自主探索）、多 agent 框架（2025-02 开源）。**最活跃。** | **高**：skill 集与 benchmark 可直接借鉴/移植 |
| **[GITM](https://github.com/OpenGVLab/GITM)** (OpenGVLab) | 平行范式 | 用**文本知识 / 记忆**而非代码执行；**首个拿全主世界科技树**的 agent | 中：科技树推进思路（本项目已有 `survival/` + `tech_tree/`） |
| **[VillagerAgent](https://github.com/cnsdqd-dyb/VillagerAgent)** | 多 agent | 图基多 agent 协作（ACL 2024） | 低（除非未来做多 NPC 协作） |
| **[Co-Voyager](https://github.com/Itakello/Co-voyager)** (Itakello) | 协作扩展 | 解决 Voyager 在多 subtask 下的协作短板 | 低 |
| **社区 k8s fork** | 部署 | 打包 Fabric 服务器 + mods，支持**本地/开源 LLM** 跑 Voyager | 中：本项目已自带多 LLM provider，参考价值有限 |
| **[minecraft-llm-agent-community](https://github.com/gigio1023/minecraft-llm-agent-community)** | 社会模拟 | Mineflayer actor 追求 "LifeGoals"，偏社会模拟 | 低 |

> 纯 JS/TS 移植版几乎搜不到成熟项目——Minecraft LLM agent 生态仍是 Python 主导，JS 只作为 bot 端（这和本项目一致）。

---

## 4. 本项目现状定位（核心对照）

### 4.1 你已经有的

`src/animetta/tools/minecraft/` 下**已自研**的 Voyager 式组件：

```
skill/
  models.py         Skill 领域模型 + step 参数定义
  predefined.py     内置预定义技能
  library.py        SkillLibrary（SQLite 持久化）
  catalog.py        skill 检索（keyword/tag/precondition）
  executor.py       技能执行器
  verifier.py       ★ 对应官方 Verifier
  code_generator.py ★ 对应官方"LLM 写 JS code skill"
  code_seeds.py     代码 skill 种子
  extractor.py      从轨迹抽取技能
  validator.py / conditions.py / store.py
autonomous/
  curriculum.py     ★ 对应官方 Automatic Curriculum（LLM 驱动）
  loop.py           感知—决策—行动循环（8 级优先级）
  planner.py        LLM 规划器（先 search_skills 再问 LLM）
bot/
  sandbox.js        ★ Voyager eval_code 沙箱（code-body skill 运行环境）
other/
  self_evolution.py ★ 自我进化循环（最近提交：Voyager self-evolution loop）
survival/  tech_tree/  benchmark/   ← 你独有的工程化层
```

**结论**：Voyager 的三组件 + 沙箱 + 自进化循环，你**全都有**。不是"借鉴"，是"复刻 + 扩展"。

### 4.2 三组件逐项对照

| 组件 | 官方 Voyager | 本项目 | 差异解读 |
| --- | --- | --- | --- |
| **Curriculum 目标** | 完全开放探索（最大化新物品/方块发现） | LLM 驱动，但**收窄到生存科技树**（终极目标 `iron_pickaxe`） | 你更**聚焦、可 benchmark**；官方更"涌现"但难评估。是**有意的设计选择**，不一定是劣势。 |
| **Skill 检索** | description 的 **embedding 向量**检索 | `catalog.py` 提供 4 种：`search_skills(goal)` / `search_by_tags` / `match_skills(precondition)` / `search_by_keyword`，**无 embedding** | **最大缺口**。skill 数量小时够用；上规模后召回与语义匹配弱于官方。 |
| **Skill 形态** | 纯 JS **code-body**（可执行函数） | **step skill + code-body 混合** | 你多了 `step` 抽象（goto/collect/craft/...），更**可控、可校验、更安全**；官方更灵活但更"野"。 |
| **Verifier** | GPT-4-as-judge + 执行错误反馈循环 | `verifier.py` 存在 | 需确认：是否做到 GPT-as-judge + 失败重写循环，还是仅规则/状态校验。 |
| **持久化** | JSON 文件（skill 文件夹） | SQLite（`data/mc_skills.db`） | 你更**工程化**，利于统计与并发。 |
| **LLM 编排** | 旧 LangChain（0.2 break） | **LangGraph** | **你的优势**：依赖更现代、状态图更清晰、可维护性好。 |
| **Bot 端** | Mineflayer JS | Mineflayer JS（`bot/index.js`） | 一致。 |

### 4.3 一张图看清差异位置

```
                官方 Voyager          vs          本项目
Curriculum      开放探索(discovery)  ─┐
                                    └→ 生存科技树收窄    [设计差异, 非缺口]
Skill 检索      embedding 向量      ─┐
                                    └→ keyword/tag/cond   ★[可补的缺口]
Skill 形态      纯 code-body        ─┐
                                    └→ step + code-body   [你的扩展]
Verifier        GPT-judge + 重写    ─┐
                                    └→ verifier.py        [需确认强度]
LLM 编排        旧 LangChain        ─┐
                                    └→ LangGraph          [你的优势]
持久化          JSON 文件           ─┐
                                    └→ SQLite             [你的优势]
+ 独有          —                    →  survival/tech_tree/benchmark 工程化层
```

---

## 5. 值得深挖的线（供后续决策）

1. **embedding 检索缺口**
   你的 `catalog.py` 没有向量召回。本项目 `memory/` 已在用 Chroma，可低成本给 skill description 加 embedding 索引。**触发点**：当前 skill 库规模（predefined + learned）超过 ~50 条时收益开始显现。

2. **借鉴 Odyssey 的 skill 集 / benchmark**
   Odyssey 的 40 primitive + 183 compositional skills、以及它的 long-term planning / dynamic-immediate planning / autonomous exploration 三类 benchmark，可以作为本项目 `predefined.py` 与 `benchmark/` 的扩充来源——尤其 compositional skills 对你的 `step skill` 组合是直接参考。

3. **Curriculum 开放度的取舍**
   你的"生存科技树收窄"是**可 benchmark 的优势**（`survival/runner.py` + `tech_tree/runner.py` 都依赖这种确定性）。若未来想做"涌现式探索"演示，可参考官方的 discovery-driven 目标函数，做成一个可选模式而非替换。

4. **Verifier 强度对齐**
   核对 `verifier.py` 是否实现"GPT-as-judge + 执行错误反馈重写循环"。若仅做状态/规则校验，那是相对官方最薄弱的一环——而它恰恰是 skill 质量（学习有效性）的关键。

5. **与 GITM 文本范式的隐性亲缘**
   你的 `step skill`（预定义动作序列）其实更接近 GITM 的"文本动作"范式，而非 Voyager 的"纯代码"范式。本项目处于两者中间态——这是可以进一步显式化的设计点（哪些 skill 用 step、哪些用 code-body，标准是什么）。

---

## 6. 来源

- 官方 Voyager 仓库：[github.com/MineDojo/Voyager](https://github.com/MineDojo/Voyager)
- 论文：[arXiv:2305.16291](https://arxiv.org/abs/2305.16291) ｜ 项目页：[voyager.minedojo.org](https://voyager.minedojo.org/)
- langchain 兼容问题：[issue #163](https://github.com/MineDojo/Voyager/issues/163)
- Odyssey（IJCAI 2025）：[github.com/zju-vipa/odyssey](https://github.com/zju-vipa/odyssey)
- GITM：[github.com/OpenGVLab/GITM](https://github.com/OpenGVLab/GITM) ｜ 论文 [arXiv:2305.17144](https://arxiv.org/abs/2305.17144)
- VillagerAgent（ACL 2024）：[github.com/cnsdqd-dyb/VillagerAgent](https://github.com/cnsdqd-dyb/VillagerAgent)
- Co-Voyager：[github.com/Itakello/Co-voyager](https://github.com/Itakello/Co-voyager)
- minecraft-llm-agent-community：[github.com/gigio1023/minecraft-llm-agent-community](https://github.com/gigio1023/minecraft-llm-agent-community)
- Mineflayer：[github.com/PrismarineJS/mineflayer](https://github.com/PrismarineJS/mineflayer)

---

## 附录：四条建议的深度核实与最终结论（2026-06-28）

> 基于 `self_evolution.py` / `verifier.py` / `code_generator.py` / `catalog.py` / `predefined.py` / `code_seeds.py` 的实读，对前文 A/B/C/D 四条线的最终判断。
>
> **总判断**：本项目对 Voyager 的实现完成度**被第 4 节严重低估**——不是"复刻 ~90%"，而是**"完整复刻 + 工程增强"**，某些维度超过官方原版。真正的瓶颈不在"对照官方补差距"。

### A. Verifier + Code Generator 强度 —— ✅ **不是缺口，是亮点**（撤回"需确认"判断）

- **verifier.py 是双重验证（dual-gate）**：闸1 确定性 inventory 检查（正则 `has_X >= N`，零成本秒判）→ 判不了才走闸2 LLM（YES/NO + 理由）。**比官方纯 GPT-4-as-judge 更省 token、更低延迟**——这是对论文的工程改进，不是阉割。
- **code_generator.py 忠实实现论文迭代提示主循环**：LLM 写 JS → `eval_code` 执行 → 失败把"错误+上版代码"喂回重写 → ≤4 轮；并注入检索到的 verified 技能作 reference。`SYSTEM_PROMPT` 工程质量很高（API 表、inventory 是 object 不是 array、`stone→cobblestone` drop 关系、examples）。
- **self_evolution.py 是完整可跑的 60 轮循环**：`curriculum → search_skills → generate_with_iteration → eval_code → verify → to_skill(validated=True) 入库`，带**持久化**（`data/mc_evo_state.json` 跨会话恢复）、**防卡死**（连续 10 轮同任务即停）、**RCON 读服务端 inventory**（绕 mineflayer 缓存），且用 **DeepSeek 而非 GPT-4**——**已经解决了官方"强绑定 OpenAI"的痛点**。

  ⚠️ **唯一方法论瑕疵**：`self_evolution.py` 的"材料补全"（`_rcon give ...`，1/5 阈值）是半作弊，会**污染 verifier 判断**——give 补全后 inventory 达标，verifier 可能把一个真实环境下会失败的 skill 判成成功并存库。这是比"缺 embedding"重要 10 倍的问题。

### B. Embedding 检索 ROI —— ⏸ **现在不该做（过度工程）**

- 当前规模：`predefined(15) + code_seeds(1) = 16` 条种子 + 若干 learned。`catalog.py` 的词袋/关键词检索（`search_skills` 分词命中计分、`search_by_keyword` name×2+desc+tags×2 加权、`match_skills` precondition+success_rate 排序）在这个规模**完全够用**，且已有 `cleanup()`（成功率<0.3 且 ≥10 次自动淘汰）这种 embedding 系统反而不具备的工程化。
- **触发条件**：learned skill 积累到 **50+ 条**时再上 embedding（届时复用 `memory/` 的 Chroma）。现在上是过度工程。

### C. 借鉴 Odyssey —— 🟡 **benchmark 优于 skill 集移植；fine-tune 路线与你正交**

- Odyssey 三件套：40 primitive + **183**（非 133）compositional skills / fine-tuned LLaMA-3 / benchmark（IJCAI 2025, [arXiv:2407.15325](https://arxiv.org/abs/2407.15325)）。
- **fine-tuned LLaMA-3 路线和本项目正交**——你走 LangGraph 编排通用 LLM（DeepSeek），不 fine-tune。这是更轻量、更灵活的路线，没必要为了 skill 集去走重路线。
- **183 compositional skills 不急着移植**：(a) 形态未必对齐你的 step/code-body 双形态；(b) 你的目标收窄在"金装备/生存科技树"，大半用不上。
- **真正值得借鉴的是 Odyssey 的 benchmark 方法论**（长程规划 / 动态即时规划 / 自主探索三类任务）——你的 `benchmark/` 可对齐它做量化评估。

### D. step vs code-body 标准 —— ✅ **设计已成熟，只缺文档化**

- 已有明确分工（`executor.py` 单一分支点 `body.type=="code"`）：
  - **step skill** = 14 种原子动作的可校验序列，可控安全；`predefined.py` 15 条全在此。≈ GITM 文本动作范式。
  - **code-body skill** = LLM 生成 JS 走 `eval_code` 沙箱，处理 step 表达不了的复杂/新任务。≈ Voyager 代码范式。
- 这是**官方纯 code 与 GITM 纯文本的最优折中**——step 锁可靠基底、code-body 留涌现空间。设计成熟，**缺口只是没写进 architecture 文档**。

### 最终优先级（我的建议）

| 优先级 | 动作 | 依据 |
| --- | --- | --- |
| 🔴 P0 | **隔离/移除 `self_evolution.py` 的 give 材料补全**（或让 verifier 在 no-give 下复验） | 学习有效性根基；不解决则"学到的 skill"在真实环境会失败 |
| 🟡 P1 | **文档化 step vs code-body 选型标准**（写进 `minecraft-bot-architecture.md`） | D 线，零成本，避免后续维护者误改 |
| 🟡 P1 | **对齐 Odyssey benchmark 方法论**，量化评估 agent | C 线精华；`benchmark/` 已有骨架 |
| 🟢 P2 | **learned skill >50 条后再上 embedding 检索** | B 线；现在做是过度工程 |
| ⚪ 低 | 移植 Odyssey 的 compositional skill 清单 | 需先确认形态对齐 + 目标匹配 |
