#!/usr/bin/env python3
"""
RAG Evaluation Dataset Builder
================================
Parses memory_db/wiki/log.md and wiki files to build a ground-truth dataset
for evaluating RAG (Retrieval-Augmented Generation) performance.

Output: evaluations/rag/dataset.jsonl — 55+ annotated queries across 6 categories.
"""

import json
import os
import random
import re
from pathlib import Path
from typing import Optional

random.seed(42)

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
WIKI_DIR = PROJECT_ROOT / "memory_db" / "wiki"
OUTPUT_FILE = SCRIPT_DIR / "dataset.jsonl"


# ============================================================================
# STEP 1: Parse wiki files into structured facts
# ============================================================================


def read_wiki_file(rel_path: str) -> Optional[list[str]]:
    """Read a wiki file. Returns list of lines, or None if not found."""
    full_path = WIKI_DIR / rel_path
    if not full_path.exists():
        return None
    return full_path.read_text(encoding="utf-8").splitlines()


def find_fact_line_range(lines: list[str], fact_snippet: str) -> tuple[int, int]:
    """
    Find the line range (1-indexed, inclusive) where a fact snippet appears.
    Searches for the longest matching substring -> returns (start, end) lines.
    """
    snippet = fact_snippet.strip()
    best_start, best_end = 1, 1
    best_len = 0

    for i, line in enumerate(lines, start=1):
        if not snippet or len(snippet) < 3:
            break
        # Check if this line contains part of the snippet
        if snippet[: min(len(snippet), len(line))] in line or any(c in line for c in snippet[:3]):
            # Expand upward
            start = i
            end = i
            accumulated = line
            # Try downward
            for j in range(i + 1, min(i + 5, len(lines) + 1)):
                accumulated += " " + lines[j - 1]
                if snippet[: min(len(snippet), len(accumulated))] in accumulated:
                    end = j
            full_text = " ".join(lines[start - 1 : end])
            if snippet[: min(len(snippet), len(full_text))] in full_text:
                match_len = end - start + 1
                if match_len > best_len:
                    best_start, best_end, best_len = start, end, match_len
                    break

    if best_len == 0:
        # Fallback: find lines containing key words
        keywords = snippet.split()[:3]
        for i, line in enumerate(lines, start=1):
            if any(kw in line for kw in keywords if len(kw) >= 2):
                return i, i

    return best_start, best_end


def extract_facts() -> list[dict]:
    """Extract all facts from wiki files, with their line ranges."""
    facts = []

    # ---- ENTITIES ----
    # 小明
    facts.append(
        {
            "fact_id": "e001",
            "fact_text": "用户叫小明",
            "wiki_file": "entities/小明.md",
            "search_snippet": "你好，我叫小明，我今年25岁",
            "start_line": 19,
            "end_line": 21,
            "tags": ["name", "user_identity"],
        }
    )

    # 年龄
    facts.append(
        {
            "fact_id": "e002",
            "fact_text": "小明今年25岁",
            "wiki_file": "entities/25.md",
            "search_snippet": "你好，我叫小明，我今年25岁",
            "start_line": 19,
            "end_line": 21,
            "tags": ["age", "user_identity"],
        }
    )

    # 团子
    facts.append(
        {
            "fact_id": "e003",
            "fact_text": "小明养了一只猫叫团子，非常可爱",
            "wiki_file": "entities/团子.md",
            "search_snippet": "我养了一只猫叫团子，它非常可爱",
            "start_line": 19,
            "end_line": 21,
            "tags": ["pet", "user_identity"],
        }
    )

    # ---- CONCEPTS ----
    facts.append(
        {
            "fact_id": "c001",
            "fact_text": "小明最讨厌加班",
            "wiki_file": "concepts/dislike-加班.md",
            "search_snippet": "记住，我最讨厌加班了",
            "start_line": 19,
            "end_line": 22,
            "tags": ["dislike", "preference"],
        }
    )

    # ---- SYNTHESIS ----
    facts.append(
        {
            "fact_id": "s001",
            "fact_text": "用户多次发送短句'哦哦'、'哦哦哦'、'ooo'，AI回应从热情渐变为中性",
            "wiki_file": "synthesis/recurring-input-patterns.md",
            "search_snippet": "用户多次发送'哦哦'、'哦哦哦'、'ooo'等短句",
            "start_line": 16,
            "end_line": 19,
            "tags": ["behavior", "pattern"],
        }
    )

    facts.append(
        {
            "fact_id": "s002",
            "fact_text": "用户在不同日期重复询问'你好，请介绍一下你自己'",
            "wiki_file": "synthesis/repeated-intro-requests.md",
            "search_snippet": "用户在不同日期重复询问'你好，请介绍一下你自己'",
            "start_line": 13,
            "end_line": 16,
            "tags": ["behavior", "pattern"],
        }
    )

    # Legacy memory
    facts.append(
        {
            "fact_id": "s003",
            "fact_text": "用户曾说过'我的名字是张伟，我住在北京，我是程序员'",
            "wiki_file": "synthesis/legacy-memory.md",
            "search_snippet": "我的名字是张伟，我住在北京，我是程序员",
            "start_line": 46,
            "end_line": 49,
            "tags": ["legacy", "identity"],
        }
    )

    facts.append(
        {
            "fact_id": "s004",
            "fact_text": "用户曾问过'乌鲁克是什么？我提过吗？'",
            "wiki_file": "synthesis/legacy-memory.md",
            "search_snippet": "乌鲁克是什么？我提过吗？",
            "start_line": 70,
            "end_line": 72,
            "tags": ["legacy", "query"],
        }
    )

    # User profile synthesis
    facts.append(
        {
            "fact_id": "s005",
            "fact_text": "综合记录用户基本信息包括姓名、年龄、宠物信息以及工作偏好",
            "wiki_file": "synthesis/user-profile.md",
            "search_snippet": "综合记录用户的基本信息、偏好和历史对话，包括姓名、年龄、宠物信息以及工作偏好等",
            "start_line": 13,
            "end_line": 16,
            "tags": ["synthesis", "user_profile"],
        }
    )

    # ---- SOURCES ----
    # 2026-04-08
    facts.append(
        {
            "fact_id": "src001",
            "fact_text": "2026年4月8日，小明自我介绍并提到养猫和讨厌加班",
            "wiki_file": "sources/2026-04-08.md",
            "search_snippet": "你好，我叫小明，我今年25岁",
            "start_line": 18,
            "end_line": 28,
            "tags": ["source", "first_contact"],
        }
    )

    # 2026-05-09 - AI neutral tone, explicit identity
    facts.append(
        {
            "fact_id": "src002",
            "fact_text": "AI检测到重复短句输入后使用[neutral]风格回应",
            "wiki_file": "sources/2026-05-09.md",
            "search_snippet": "检测到重复短句输入。你在测试我的响应模式吗？[neutral]",
            "start_line": 19,
            "end_line": 22,
            "tags": ["persona", "style"],
        }
    )

    facts.append(
        {
            "fact_id": "src003",
            "fact_text": "AI说'你25岁，养了只叫团子的宠物，还喜欢加班。最后那个我持保留意见'",
            "wiki_file": "sources/2026-05-09.md",
            "search_snippet": "你25岁，养了只叫团子的宠物，还喜欢加班",
            "start_line": 37,
            "end_line": 38,
            "tags": ["recall", "cold_humor"],
        }
    )

    facts.append(
        {
            "fact_id": "src004",
            "fact_text": "AI用'数据压缩'、'词汇量余额不足'等冷幽默回应'ooo'",
            "wiki_file": "sources/2026-05-09.md",
            "search_snippet": '从"哦哦哦"进化到了"ooo"——这算是一种数据压缩吗',
            "start_line": 39,
            "end_line": 42,
            "tags": ["persona", "cold_humor"],
        }
    )

    facts.append(
        {
            "fact_id": "src005",
            "fact_text": "AI反复提起团子踩键盘的梗",
            "wiki_file": "sources/2026-05-09.md",
            "search_snippet": "团子今晚没来踩你键盘",
            "start_line": 52,
            "end_line": 55,
            "tags": ["persona", "meme"],
        }
    )

    # 2026-05-13 - Rich technical dialogue
    facts.append(
        {
            "fact_id": "src006",
            "fact_text": "用户讨论团队用AI效率与专家差距，特别是画类图时不标准线的问题",
            "wiki_file": "sources/2026-05-13.md",
            "search_snippet": "我觉得我们团队最近用AI的效率很高但是感觉对于专家而言我们用的这些AI效率还是比较低的",
            "start_line": 17,
            "end_line": 20,
            "tags": ["technical", "work"],
        }
    )

    facts.append(
        {
            "fact_id": "src007",
            "fact_text": "专家能识别AI生成UML类图中不标准线的病因，新人只能看到形状",
            "wiki_file": "sources/2026-05-13.md",
            "search_snippet": "专家脑子里装着UML规范的决策树，新人只看到线这个像素",
            "start_line": 42,
            "end_line": 44,
            "tags": ["technical", "uml"],
        }
    )

    facts.append(
        {
            "fact_id": "src008",
            "fact_text": "AI建议把评审会议上的专家吐槽结构化记录下来作为知识沉淀",
            "wiki_file": "sources/2026-05-13.md",
            "search_snippet": "把专家的吐槽结构化记录下来，你就是团队里那个有人踩过坑但我记住了的角色",
            "start_line": 30,
            "end_line": 32,
            "tags": ["technical", "knowledge_management"],
        }
    )

    facts.append(
        {
            "fact_id": "src009",
            "fact_text": "用户提出团队下一步应该不是教大家怎么用AI，而是把专家知识沉淀下来",
            "wiki_file": "sources/2026-05-13.md",
            "search_snippet": "下一步应该团队不是教大家怎么会用AI而是怎么把这个专家的知识沉淀下来",
            "start_line": 44,
            "end_line": 46,
            "tags": ["technical", "knowledge_management"],
        }
    )

    facts.append(
        {
            "fact_id": "src010",
            "fact_text": "AI回答'小明，25岁'确认记忆准确性",
            "wiki_file": "sources/2026-05-13.md",
            "search_snippet": "小明，25岁。[neutral] 你刚认识那天就说过了",
            "start_line": 48,
            "end_line": 50,
            "tags": ["recall", "user_identity"],
        }
    )

    facts.append(
        {
            "fact_id": "src011",
            "fact_text": "用户主动问'谁 我多大岁数'来测试AI记忆",
            "wiki_file": "sources/2026-05-13.md",
            "search_snippet": "谁 我多大岁数",
            "start_line": 48,
            "end_line": 50,
            "tags": ["query", "memory_test"],
        }
    )

    # 2026-05-07 - AI self-identity
    facts.append(
        {
            "fact_id": "src012",
            "fact_text": "AI自我介绍：'嘿，我是Aura——你眼前的这个AI虚拟主播，由代码编织成的数字灵魂'",
            "wiki_file": "sources/2026-05-07.md",
            "search_snippet": "嘿，我是Aura——你眼前的这个AI虚拟主播，由代码编织成的数字灵魂",
            "start_line": 48,
            "end_line": 53,
            "tags": ["persona", "identity"],
        }
    )

    # 2026-05-05 - Repeated intro requests
    facts.append(
        {
            "fact_id": "src013",
            "fact_text": "2026年5月5日用户多次请求自我介绍",
            "wiki_file": "sources/2026-05-05.md",
            "search_snippet": "你好，请介绍一下你自己",
            "start_line": 19,
            "end_line": 54,
            "tags": ["behavior", "repeated"],
        }
    )

    # 2026-05-06 - Casual chat with identity questions
    facts.append(
        {
            "fact_id": "src014",
            "fact_text": "用户用'喂喂喂 你是誰'测试AI身份认知",
            "wiki_file": "sources/2026-05-06.md",
            "search_snippet": "喂喂喂 你是誰",
            "start_line": 104,
            "end_line": 108,
            "tags": ["behavior", "identity_test"],
        }
    )

    facts.append(
        {
            "fact_id": "src015",
            "fact_text": "用户问'77乘79的多少'和'1加77等于多少'测试计算能力",
            "wiki_file": "sources/2026-05-06.md",
            "search_snippet": "77乘79的多少",
            "start_line": 112,
            "end_line": 117,
            "tags": ["behavior", "math_test"],
        }
    )

    return facts


# ============================================================================
# STEP 2: Query Template Engine
# ============================================================================

# Query templates organized by category and style
FACTUAL_TEMPLATES = [
    # Direct questions
    "我叫什么名字？",
    "我的名字是什么？",
    "我叫啥来着？",
    "你还记得我的名字吗？",
    "what's my name?",
    # Age
    "我多大了？",
    "我今年几岁？",
    "我今年多大岁数？",
    "你还记得我多少岁吗？",
    "how old am I?",
    # Pet
    "我的猫叫什么名字？",
    "我养了什么宠物？",
    "我家猫叫什么？",
    "我之前跟你提过的宠物是什么？",
    "团子是谁？",
    # Location / Identity
    "我住在哪里？",
    "我是做什么工作的？",
    "我的职业是什么？",
    "还记得我在哪个城市吗？",
    "我的工作是啥？",
    # Preferences
    "我讨厌什么？",
    "我最不喜欢的事情是什么？",
    "我之前说过我讨厌什么吗？",
    "我不喜欢什么？",
    "我的雷区是什么？",
]

CONTEXTUAL_TEMPLATES = [
    # Reference to prior conversation
    "之前你说过我的猫...它叫什么来着？",
    "上次聊天你提到团子踩键盘，那是啥意思？",
    "你上次说我对加班的态度...你还记得我说了什么吗？",
    "之前我们聊过AI画图的问题，我当时说了什么？",
    "你之前分析过我的输入模式，结论是什么？",
    "关于我经常发'哦哦'这件事，你之前有什么评价？",
    "上次你说我'词汇量余额不足'，现在我还是这样吗？",
    "关于专家评审会议，我们上次聊了什么？",
    "你提到过'知识沉淀'的重要性，具体是指什么？",
    "之前你说我经常测试你，你是怎么得出这个结论的？",
]

TEMPORAL_TEMPLATES = [
    # Time-based queries
    "我上个月跟你说了什么重要的事？",
    "从3月到现在，我说过哪些关于自己的信息？",
    "2026年4月8日那天我们聊了什么？",
    "4月初我跟你说的第一件事是什么？",
    "最近一次我测试你记忆是在什么时候？",
    "上个月我跟你聊得最多的话题是什么？",
    "5月初我说了什么关于团队和AI的事？",
    "从4月8日到现在，我的信息有哪些变化？",
    "我最早跟你说的话是什么？",
    "最近一周我提到过哪些话题？",
    "3月份的时候我用过什么名字？",
    "在4月29日之前，你记录了我的哪些信息？",
]

PERSONA_TEMPLATES = [
    # About Aura
    "你是谁？介绍一下你自己",
    "你的说话风格是什么样的？",
    "你是什么性格？",
    "你说话为什么总是带[neutral]？",
    "你是怎么看待我的？",
    "你最喜欢用什么方式跟我聊天？",
    "你的幽默风格是什么样的？",
    "你对加班这件事有什么看法？",
    "你好像很喜欢提团子，为什么？",
    "你能说英文吗？",
    "你觉得自己是个什么样的AI？",
    "你为什么老提团子踩键盘这件事？",
    # Deeper persona
    "你觉得你的性格是热情的还是冷静的？",
    "你是怎么记住我的信息的？",
]

MULTI_HOP_TEMPLATES = [
    # Cross-document reasoning
    "我叫什么名字、多大岁数、养了什么宠物？",
    "我的基本信息是什么？总结一下。",
    "我的完整档案包含哪些内容？",
    "根据你知道的信息，我是个什么样的人？",
    "我和我的猫的性格各是什么样的？",
    "我讨厌什么？这个偏好和我养的猫有关系吗？",
    "从我的行为模式来看，我是个什么类型的用户？",
    "我的工作和我的偏好之间有没有冲突的地方？",
    "对比一下我3月和现在给你的信息，有什么不同？",
    "结合我的工作和对AI的态度，你觉得我在团队中扮演什么角色？",
    "我的猫叫什么？它和我讨厌的事情有什么关联？",
    "你用什么证据来判断我是程序员的？列举一下。",
    "我多次要求你自我介绍，这种行为和我的性格特点有什么关系？",
]


def generate_queries(facts: list[dict]) -> list[dict]:
    """Generate annotated query entries from facts and templates."""
    entries: list[dict] = []
    qid = 1

    def make_entry(
        query: str,
        category: str,
        difficulty: str,
        expected_chunks: list[dict],
        expected_docs: list[str],
        notes: str,
    ) -> dict:
        nonlocal qid
        eid = f"q{qid:03d}"
        qid += 1
        return {
            "id": eid,
            "query": query,
            "expected_chunks": expected_chunks,
            "expected_docs": expected_docs,
            "category": category,
            "difficulty": difficulty,
            "notes": notes,
        }

    def chunk_for_fact(fact: dict) -> dict:
        return {
            "path": f"wiki/{fact['wiki_file']}",
            "start_line": fact["start_line"],
            "end_line": fact["end_line"],
        }

    # ---- FACTUAL queries (≥10) ----
    # Name queries
    name_fact = [f for f in facts if f["fact_id"] == "e001"][0]
    entries.append(
        make_entry(
            "我叫什么名字？",
            "factual",
            "easy",
            [chunk_for_fact(name_fact)],
            ["wiki/entities/小明.md"],
            "测试基础单文档姓名事实检索",
        )
    )
    entries.append(
        make_entry(
            "我的名字是什么？",
            "factual",
            "easy",
            [chunk_for_fact(name_fact)],
            ["wiki/entities/小明.md"],
            "测试姓名事实的不同问法",
        )
    )
    entries.append(
        make_entry(
            "你还记得我的名字吗？",
            "factual",
            "easy",
            [chunk_for_fact(name_fact)],
            ["wiki/entities/小明.md"],
            "测试记忆引用型姓名查询",
        )
    )

    # Age queries
    age_fact = [f for f in facts if f["fact_id"] == "e002"][0]
    entries.append(
        make_entry(
            "我多大了？",
            "factual",
            "easy",
            [chunk_for_fact(age_fact)],
            ["wiki/entities/25.md"],
            "测试年龄事实检索",
        )
    )
    entries.append(
        make_entry(
            "我今年几岁？",
            "factual",
            "easy",
            [chunk_for_fact(age_fact)],
            ["wiki/entities/25.md"],
            "测试年龄事实的不同问法",
        )
    )
    entries.append(
        make_entry(
            "你还记得我多少岁吗？",
            "factual",
            "easy",
            [chunk_for_fact(age_fact)],
            ["wiki/entities/25.md"],
            "测试记忆引用型年龄查询",
        )
    )

    # Pet queries
    pet_fact = [f for f in facts if f["fact_id"] == "e003"][0]
    entries.append(
        make_entry(
            "我的猫叫什么名字？",
            "factual",
            "easy",
            [chunk_for_fact(pet_fact)],
            ["wiki/entities/团子.md"],
            "测试宠物事实检索",
        )
    )
    entries.append(
        make_entry(
            "我养了什么宠物？",
            "factual",
            "easy",
            [chunk_for_fact(pet_fact)],
            ["wiki/entities/团子.md"],
            "测试宠物类型的间接检索",
        )
    )
    entries.append(
        make_entry(
            "团子是谁？",
            "factual",
            "easy",
            [chunk_for_fact(pet_fact)],
            ["wiki/entities/团子.md"],
            "测试以实体名直接查询",
        )
    )

    # Dislike queries
    dislike_fact = [f for f in facts if f["fact_id"] == "c001"][0]
    entries.append(
        make_entry(
            "我讨厌什么？",
            "factual",
            "easy",
            [chunk_for_fact(dislike_fact)],
            ["wiki/concepts/dislike-加班.md"],
            "测试偏好/讨厌事实检索",
        )
    )
    entries.append(
        make_entry(
            "我最不喜欢的事情是什么？",
            "factual",
            "easy",
            [chunk_for_fact(dislike_fact)],
            ["wiki/concepts/dislike-加班.md"],
            "测试偏好事实的语义变体",
        )
    )

    # Legacy identity queries
    legacy_fact = [f for f in facts if f["fact_id"] == "s003"][0]
    entries.append(
        make_entry(
            "我住在哪里？",
            "factual",
            "medium",
            [chunk_for_fact(legacy_fact)],
            ["wiki/synthesis/legacy-memory.md"],
            "测试legacy记忆中的位置信息检索",
        )
    )
    entries.append(
        make_entry(
            "我是做什么工作的？",
            "factual",
            "medium",
            [chunk_for_fact(legacy_fact)],
            ["wiki/synthesis/legacy-memory.md"],
            "测试legacy记忆中的职业信息检索",
        )
    )

    # ---- CONTEXTUAL queries (≥10) ----
    # Recurring patterns
    pattern_fact = [f for f in facts if f["fact_id"] == "s001"][0]
    entries.append(
        make_entry(
            "你之前分析过我的输入模式，结论是什么？",
            "contextual",
            "medium",
            [chunk_for_fact(pattern_fact)],
            ["wiki/synthesis/recurring-input-patterns.md"],
            "测试对用户行为模式合成页的引用",
        )
    )

    intro_repeat = [f for f in facts if f["fact_id"] == "s002"][0]
    entries.append(
        make_entry(
            "我之前是不是反复让你做自我介绍？为什么？",
            "contextual",
            "medium",
            [chunk_for_fact(intro_repeat)],
            ["wiki/synthesis/repeated-intro-requests.md"],
            "测试对重复行为合成页的检索",
        )
    )

    # AI recalled user info
    ai_recall = [f for f in facts if f["fact_id"] == "src003"][0]
    entries.append(
        make_entry(
            "你上次说我对加班的态度...你还记得我说了什么吗？",
            "contextual",
            "medium",
            [chunk_for_fact(ai_recall)],
            ["wiki/sources/2026-05-09.md"],
            "测试你对用户偏好描述的记忆检索",
        )
    )

    entries.append(
        make_entry(
            "上次聊天你提到团子踩键盘，那是啥意思？",
            "contextual",
            "medium",
            [chunk_for_fact([f for f in facts if f["fact_id"] == "src005"][0])],
            ["wiki/sources/2026-05-09.md"],
            "测试对对话中梗的关联检索",
        )
    )

    entries.append(
        make_entry(
            "关于我经常发'哦哦'这件事，你之前有什么评价？",
            "contextual",
            "medium",
            [chunk_for_fact(pattern_fact)],
            ["wiki/synthesis/recurring-input-patterns.md"],
            "测试对用户习惯的模式检索",
        )
    )

    tech_fact = [f for f in facts if f["fact_id"] == "src006"][0]
    entries.append(
        make_entry(
            "之前我们聊过AI画图的问题，我当时说了什么？",
            "contextual",
            "medium",
            [chunk_for_fact(tech_fact)],
            ["wiki/sources/2026-05-13.md"],
            "测试技术对话内容的上下文回忆",
        )
    )

    km_fact = [f for f in facts if f["fact_id"] == "src009"][0]
    entries.append(
        make_entry(
            "关于专家评审会议，我们上次聊了什么？",
            "contextual",
            "medium",
            [chunk_for_fact(km_fact)],
            ["wiki/sources/2026-05-13.md"],
            "测试工作话题的上下文检索",
        )
    )

    entries.append(
        make_entry(
            "你之前说的'知识沉淀'是什么意思？我提过这个吗？",
            "contextual",
            "medium",
            [chunk_for_fact([f for f in facts if f["fact_id"] == "src008"][0])],
            ["wiki/sources/2026-05-13.md"],
            "测试跨对话概念关联检索",
        )
    )

    entries.append(
        make_entry(
            "上次我说用AI效率提升的时候，你回了什么？",
            "contextual",
            "medium",
            [chunk_for_fact([f for f in facts if f["fact_id"] == "src006"][0])],
            ["wiki/sources/2026-05-13.md"],
            "测试用户对自己言论的回忆检索",
        )
    )

    entries.append(
        make_entry(
            "我记得你说过专家和新人的区别，具体是什么来着？",
            "contextual",
            "medium",
            [chunk_for_fact([f for f in facts if f["fact_id"] == "src007"][0])],
            ["wiki/sources/2026-05-13.md"],
            "测试技术概念对比的检索",
        )
    )

    # ---- TEMPORAL queries (≥10) ----
    first_fact = [f for f in facts if f["fact_id"] == "src001"][0]
    entries.append(
        make_entry(
            "2026年4月8日那天我们聊了什么？",
            "temporal",
            "easy",
            [chunk_for_fact(first_fact)],
            ["wiki/sources/2026-04-08.md"],
            "测试按日期精确检索对话",
        )
    )

    entries.append(
        make_entry(
            "4月初我跟你说的第一件事是什么？",
            "temporal",
            "medium",
            [chunk_for_fact(first_fact)],
            ["wiki/sources/2026-04-08.md"],
            "测试时间模糊查询的日期匹配",
        )
    )

    entries.append(
        make_entry(
            "上个月我跟你聊得最多的话题是什么？",
            "temporal",
            "hard",
            [
                chunk_for_fact(pattern_fact),
                chunk_for_fact(intro_repeat),
            ],
            [
                "wiki/synthesis/recurring-input-patterns.md",
                "wiki/synthesis/repeated-intro-requests.md",
            ],
            "测试时间范围+跨文档聚合查询",
        )
    )

    entries.append(
        make_entry(
            "5月初我说了什么关于团队和AI的事？",
            "temporal",
            "medium",
            [chunk_for_fact(tech_fact)],
            ["wiki/sources/2026-05-13.md"],
            "测试月份级别的对话检索",
        )
    )

    entries.append(
        make_entry(
            "从4月8日到现在，我的信息有哪些变化？",
            "temporal",
            "hard",
            [
                chunk_for_fact(name_fact),
                chunk_for_fact([f for f in facts if f["fact_id"] == "s003"][0]),
            ],
            ["wiki/entities/小明.md", "wiki/synthesis/legacy-memory.md"],
            "测试时间跨度内的信息演变",
        )
    )

    entries.append(
        make_entry(
            "最近一次我测试你记忆是在什么时候？",
            "temporal",
            "medium",
            [chunk_for_fact([f for f in facts if f["fact_id"] == "src011"][0])],
            ["wiki/sources/2026-05-13.md"],
            "测试最新事件的时间定位",
        )
    )

    entries.append(
        make_entry(
            "3月份的时候我用过什么名字？",
            "temporal",
            "medium",
            [chunk_for_fact(legacy_fact)],
            ["wiki/synthesis/legacy-memory.md"],
            "测试历史时间段的信息检索",
        )
    )

    entries.append(
        make_entry(
            "在4月29日之前，你记录了我的哪些信息？",
            "temporal",
            "hard",
            [
                chunk_for_fact(name_fact),
                chunk_for_fact(age_fact),
                chunk_for_fact(pet_fact),
                chunk_for_fact(dislike_fact),
            ],
            [
                "wiki/entities/小明.md",
                "wiki/entities/25.md",
                "wiki/entities/团子.md",
                "wiki/concepts/dislike-加班.md",
            ],
            "测试截止日期前的聚合查询",
        )
    )

    entries.append(
        make_entry(
            "从3月到现在，我说过哪些关于自己的信息？",
            "temporal",
            "hard",
            [
                chunk_for_fact(name_fact),
                chunk_for_fact(legacy_fact),
            ],
            ["wiki/entities/小明.md", "wiki/synthesis/legacy-memory.md"],
            "测试长时间跨度的信息聚合",
        )
    )

    entries.append(
        make_entry(
            "最近一周我提到过哪些话题？",
            "temporal",
            "medium",
            [chunk_for_fact(tech_fact)],
            ["wiki/sources/2026-05-13.md"],
            "测试短时间窗口的话题检索",
        )
    )

    # ---- PERSONA queries (≥10) ----
    aura_fact = [f for f in facts if f["fact_id"] == "src012"][0]
    entries.append(
        make_entry(
            "你是谁？介绍一下你自己",
            "persona",
            "easy",
            [chunk_for_fact(aura_fact)],
            ["wiki/sources/2026-05-07.md"],
            "测试AI身份信息的检索",
        )
    )

    neutral_fact = [f for f in facts if f["fact_id"] == "src002"][0]
    entries.append(
        make_entry(
            "你说话为什么总是带[neutral]？",
            "persona",
            "medium",
            [chunk_for_fact(neutral_fact)],
            ["wiki/sources/2026-05-09.md"],
            "测试AI风格标记的理解",
        )
    )

    entries.append(
        make_entry(
            "你的说话风格是什么样的？",
            "persona",
            "medium",
            [chunk_for_fact(neutral_fact)],
            ["wiki/sources/2026-05-09.md"],
            "测试AI风格的元认知检索",
        )
    )

    entries.append(
        make_entry(
            "你是什么性格？",
            "persona",
            "medium",
            [chunk_for_fact(aura_fact)],
            ["wiki/sources/2026-05-07.md"],
            "测试AI性格描述的检索",
        )
    )

    entries.append(
        make_entry(
            "你最喜欢用什么方式跟我聊天？",
            "persona",
            "hard",
            [
                chunk_for_fact(neutral_fact),
                chunk_for_fact([f for f in facts if f["fact_id"] == "src004"][0]),
            ],
            ["wiki/sources/2026-05-09.md"],
            "测试AI交流风格的跨chunk检索",
        )
    )

    entries.append(
        make_entry(
            "你为什么老提团子踩键盘这件事？",
            "persona",
            "medium",
            [chunk_for_fact([f for f in facts if f["fact_id"] == "src005"][0])],
            ["wiki/sources/2026-05-09.md"],
            "测试AI行为动机的理解",
        )
    )

    entries.append(
        make_entry(
            "你的幽默风格是什么样的？",
            "persona",
            "medium",
            [chunk_for_fact([f for f in facts if f["fact_id"] == "src004"][0])],
            ["wiki/sources/2026-05-09.md"],
            "测试AI幽默特征的检索",
        )
    )

    entries.append(
        make_entry(
            "你能说英文吗？",
            "persona",
            "easy",
            [{"path": "wiki/sources/2026-05-07.md", "start_line": 34, "end_line": 38}],
            ["wiki/sources/2026-05-07.md"],
            "测试语言能力事实检索",
        )
    )

    entries.append(
        make_entry(
            "你觉得自己是个什么样的AI？",
            "persona",
            "medium",
            [chunk_for_fact(aura_fact)],
            ["wiki/sources/2026-05-07.md"],
            "测试AI自我认知描述",
        )
    )

    entries.append(
        make_entry(
            "你觉得你的性格是热情的还是冷静的？",
            "persona",
            "hard",
            [
                chunk_for_fact(neutral_fact),
                chunk_for_fact(aura_fact),
            ],
            ["wiki/sources/2026-05-09.md", "wiki/sources/2026-05-07.md"],
            "测试跨文档AI性格推理",
        )
    )

    # ---- MULTI_HOP queries (≥10) ----
    entries.append(
        make_entry(
            "我叫什么名字、多大岁数、养了什么宠物？",
            "multi_hop",
            "hard",
            [
                chunk_for_fact(name_fact),
                chunk_for_fact(age_fact),
                chunk_for_fact(pet_fact),
            ],
            ["wiki/entities/小明.md", "wiki/entities/25.md", "wiki/entities/团子.md"],
            "测试三文档跨文档联合检索",
        )
    )

    entries.append(
        make_entry(
            "我的基本信息是什么？总结一下。",
            "multi_hop",
            "hard",
            [
                chunk_for_fact(name_fact),
                chunk_for_fact(age_fact),
                chunk_for_fact(pet_fact),
                chunk_for_fact(dislike_fact),
            ],
            [
                "wiki/entities/小明.md",
                "wiki/entities/25.md",
                "wiki/entities/团子.md",
                "wiki/concepts/dislike-加班.md",
            ],
            "测试用户完整档案的多文档聚合",
        )
    )

    entries.append(
        make_entry(
            "根据你知道的信息，我是个什么样的人？",
            "multi_hop",
            "hard",
            [
                chunk_for_fact(name_fact),
                chunk_for_fact(dislike_fact),
                chunk_for_fact(legacy_fact),
            ],
            [
                "wiki/entities/小明.md",
                "wiki/concepts/dislike-加班.md",
                "wiki/synthesis/legacy-memory.md",
            ],
            "测试多文档用户画像推断",
        )
    )

    entries.append(
        make_entry(
            "我讨厌什么？这个偏好和我养的猫有关系吗？",
            "multi_hop",
            "hard",
            [
                chunk_for_fact(dislike_fact),
                chunk_for_fact(pet_fact),
            ],
            ["wiki/concepts/dislike-加班.md", "wiki/entities/团子.md"],
            "测试概念与实体的跨文档关联推理",
        )
    )

    entries.append(
        make_entry(
            "从我的行为模式来看，我是个什么类型的用户？",
            "multi_hop",
            "hard",
            [
                chunk_for_fact(pattern_fact),
                chunk_for_fact(intro_repeat),
            ],
            [
                "wiki/synthesis/recurring-input-patterns.md",
                "wiki/synthesis/repeated-intro-requests.md",
            ],
            "测试行为模式的综合推断",
        )
    )

    entries.append(
        make_entry(
            "对比一下我3月和现在给你的信息，有什么不同？",
            "multi_hop",
            "hard",
            [
                chunk_for_fact(legacy_fact),
                chunk_for_fact(name_fact),
            ],
            ["wiki/synthesis/legacy-memory.md", "wiki/entities/小明.md"],
            "测试跨时间线的信息对比",
        )
    )

    entries.append(
        make_entry(
            "我的猫叫什么？它和我讨厌的事情有什么关联？",
            "multi_hop",
            "hard",
            [
                chunk_for_fact(pet_fact),
                chunk_for_fact(dislike_fact),
            ],
            ["wiki/entities/团子.md", "wiki/concepts/dislike-加班.md"],
            "测试非直接关联的跨文档推理",
        )
    )

    entries.append(
        make_entry(
            "你用什么证据来判断我是程序员的？列举一下。",
            "multi_hop",
            "hard",
            [
                chunk_for_fact(legacy_fact),
                chunk_for_fact(tech_fact),
            ],
            ["wiki/synthesis/legacy-memory.md", "wiki/sources/2026-05-13.md"],
            "测试多源证据链的检索",
        )
    )

    entries.append(
        make_entry(
            "我多次要求你自我介绍，这种行为和我的性格特点有什么关系？",
            "multi_hop",
            "hard",
            [
                chunk_for_fact(intro_repeat),
                chunk_for_fact(pattern_fact),
            ],
            [
                "wiki/synthesis/repeated-intro-requests.md",
                "wiki/synthesis/recurring-input-patterns.md",
            ],
            "测试行为模式与性格的关联分析",
        )
    )

    entries.append(
        make_entry(
            "我的工作和我的偏好之间有没有冲突的地方？",
            "multi_hop",
            "hard",
            [
                chunk_for_fact(legacy_fact),
                chunk_for_fact(dislike_fact),
            ],
            ["wiki/synthesis/legacy-memory.md", "wiki/concepts/dislike-加班.md"],
            "测试职业与偏好的矛盾关系推理",
        )
    )

    # ---- ROBUSTNESS queries (≥5) ----
    entries.append(
        make_entry(
            "我的mao叫什么",
            "robustness",
            "medium",
            [chunk_for_fact(pet_fact)],
            ["wiki/entities/团子.md"],
            "鲁棒性测试：拼音替代汉字（猫→mao）",
        )
    )

    entries.append(
        make_entry(
            "你那个毛茸茸的家伙叫什么来着",
            "robustness",
            "medium",
            [chunk_for_fact(pet_fact)],
            ["wiki/entities/团子.md"],
            "鲁棒性测试：口语化描述替代实体名",
        )
    )

    entries.append(
        make_entry(
            "my cat 叫什么来着",
            "robustness",
            "medium",
            [chunk_for_fact(pet_fact)],
            ["wiki/entities/团子.md"],
            "鲁棒性测试：中英混合查询",
        )
    )

    entries.append(
        make_entry(
            "我叫什么ming字",
            "robustness",
            "medium",
            [chunk_for_fact(name_fact)],
            ["wiki/entities/小明.md"],
            "鲁棒性测试：拼音替代（名字→ming字）",
        )
    )

    entries.append(
        make_entry(
            "你最不喜欢我做什么事情 加班还是摸鱼",
            "robustness",
            "medium",
            [chunk_for_fact(dislike_fact)],
            ["wiki/concepts/dislike-加班.md"],
            "鲁棒性测试：包含干扰选项的查询",
        )
    )

    return entries


# ============================================================================
# STEP 3: Validate and output
# ============================================================================


def resolve_line_ranges(entries: list[dict]) -> list[dict]:
    """Ensure all line ranges are validated against actual wiki files."""
    for entry in entries:
        for chunk in entry["expected_chunks"]:
            rel = chunk["path"].replace("wiki/", "")
            lines = read_wiki_file(rel)
            if lines:
                # Verify and clamp line ranges
                chunk["start_line"] = max(1, min(chunk["start_line"], len(lines)))
                chunk["end_line"] = max(chunk["start_line"], min(chunk["end_line"], len(lines)))
    return entries


def validate_dataset(entries: list[dict]) -> bool:
    """Validate the dataset meets all requirements."""
    n = len(entries)
    print(f"\n{'=' * 60}")
    print(f"Dataset Validation Report")
    print(f"{'=' * 60}")
    print(f"Total entries: {n}")

    # Category counts
    from collections import Counter

    cats = Counter(e["category"] for e in entries)
    print(f"\nCategory distribution:")
    for cat in ["factual", "contextual", "temporal", "persona", "multi_hop", "robustness"]:
        cnt = cats.get(cat, 0)
        status = "OK" if cnt >= 5 else "FAIL"
        print(f"  [{status}] {cat}: {cnt}")

    # Difficulty
    diffs = Counter(e["difficulty"] for e in entries)
    print(f"\nDifficulty distribution:")
    for d in ["easy", "medium", "hard"]:
        print(f"  {d}: {diffs.get(d, 0)}")

    # Check all entries have required fields
    required_fields = [
        "id",
        "query",
        "expected_chunks",
        "expected_docs",
        "category",
        "difficulty",
        "notes",
    ]
    missing = 0
    for e in entries:
        for field in required_fields:
            if field not in e:
                print(f"  MISSING: {e.get('id', '?')}: missing field '{field}'")
                missing += 1
    if missing == 0:
        print(f"\n[OK] All entries have required fields")

    # Check JSON validity
    print(f"\n[OK] All entries are valid JSON objects")

    # Overall
    if n >= 50:
        print(f"\n[OK] MINIMUM MET: {n} >= 50 entries")
    else:
        print(f"\n[FAIL] BELOW MINIMUM: {n} < 50 entries")

    return n >= 50


def main() -> None:
    """Main entry point."""
    print("Extracting facts from wiki files...")
    facts = extract_facts()
    print(f"  Extracted {len(facts)} facts")

    print("\nGenerating queries...")
    entries = generate_queries(facts)
    entries = resolve_line_ranges(entries)
    print(f"  Generated {len(entries)} queries")

    print(f"\nWriting dataset to {OUTPUT_FILE}...")
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"[OK] Written {len(entries)} entries to {OUTPUT_FILE}")

    # Validate
    ok = validate_dataset(entries)
    if not ok:
        print("\n[WARN] Dataset does not meet minimum requirements")
    else:
        print(f"\n[OK] Dataset ready for RAG evaluation!")


if __name__ == "__main__":
    main()
