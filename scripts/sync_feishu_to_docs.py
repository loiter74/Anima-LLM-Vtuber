#!/usr/bin/env python3
"""
Sync Animetta project data from Feishu sheets to local docs.

Usage:
    python scripts/sync_feishu_to_docs.py [--direction feishu_to_docs|docs_to_feishu]

Default: feishu_to_docs (Feishu is source of truth)
"""

import json
import subprocess
import sys
from pathlib import Path

# Config
FEISHU_TOKEN = "Io94sSOnShYdkXtuLl4c6FLDnnd"
DOCS_DIR = Path(__file__).parent.parent / "docs"


def run_lark_cli(args: list[str]) -> dict:
    """Run lark-cli command and return JSON output."""
    cmd = ["lark-cli"] + args + ["--format", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return json.loads(result.stdout)


def read_sheet(sheet_name: str, range_str: str) -> list[list[str]]:
    """Read data from Feishu sheet."""
    data = run_lark_cli(
        [
            "sheets",
            "+csv-get",
            "--spreadsheet-token",
            FEISHU_TOKEN,
            "--sheet-name",
            sheet_name,
            "--range",
            range_str,
        ]
    )
    # Parse CSV output
    csv_text = data.get("data", {}).get("csv", "")
    rows = []
    for line in csv_text.strip().split("\n"):
        if line.startswith("[row="):
            # Skip row annotations
            continue
        rows.append(line.split(","))
    return rows


def sync_roadmap() -> None:
    """Sync Roadmap sheet to docs/roadmap.md."""
    rows = read_sheet("Roadmap", "Roadmap!A1:D10")

    content = """# Animetta Roadmap

> 未来几个月的大方向安排。防止每天被新想法带跑。
>
> **Source of Truth**: [飞书表格](https://k1xawe1z6a6.feishu.cn/sheets/Io94sSOnShYdkXtuLl4c6FLDnnd)

## 路线图

| 时间范围 | 目标 | 关键交付物 | 状态 |
|----------|------|------------|------|
"""

    for row in rows[1:]:  # Skip header
        if len(row) >= 4:
            content += f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} |\n"

    content += """
---

## 使用规则

每次想做新功能时，问：

> 这个在当前 Roadmap 的哪个阶段？

如果不在当前月，就放到 Not Now。

*Last synced: {timestamp}*
"""

    # Write to file
    roadmap_path = DOCS_DIR / "roadmap.md"
    roadmap_path.parent.mkdir(parents=True, exist_ok=True)
    roadmap_path.write_text(content, encoding="utf-8")
    print(f"✓ Synced Roadmap → {roadmap_path}")


def sync_scope() -> None:
    """Sync Scope-2026-07 sheet to docs/scope-2026-07.md."""
    rows = read_sheet("Scope-2026-07", "Scope-2026-07!A1:C20")

    in_scope = []
    out_scope = []
    for row in rows[1:]:  # Skip header
        if len(row) >= 3:
            if row[0] == "做":
                in_scope.append((row[1], row[2]))
            elif row[0] == "不做":
                out_scope.append((row[1], row[2]))

    content = """# Animetta Scope - 2026年7月

> 这次到底做什么，不做什么。项目失败很多时候不是因为做得少，而是因为 Scope 一直膨胀。
>
> **Source of Truth**: [飞书表格](https://k1xawe1z6a6.feishu.cn/sheets/Io94sSOnShYdkXtuLl4c6FLDnnd)

## 做（In Scope）

| 内容 | 理由 |
|------|------|
"""
    for item, reason in in_scope:
        content += f"| {item} | {reason} |\n"

    content += """
## 不做（Out of Scope）

| 内容 | 理由 |
|------|------|
"""
    for item, reason in out_scope:
        content += f"| {item} | {reason} |\n"

    content += """
## 验收标准

**7月底必须证明**：

- [ ] Anima 能本地连续跑 10 分钟
- [ ] 聊天场景成立（不是普通ChatGPT套皮）
- [ ] LLM → TTS → Live2D → 前端 哪一段最不稳已定位
- [ ] 能录制 10 分钟 demo
- [ ] 人设文档已确定

## Scope 膨胀预警

如果出现以下情况，立即检查 Scope：

1. 想做"顺便加个小功能"
2. 觉得"这个也挺重要的"
3. 开始研究"以后可能需要的东西"
4. 被新想法吸引

**应对**：问自己 "这个在7月Scope里吗？" 如果不在，放到 Backlog 或 Not Now。

*Last synced: {timestamp}*
"""

    scope_path = DOCS_DIR / "scope-2026-07.md"
    scope_path.parent.mkdir(parents=True, exist_ok=True)
    scope_path.write_text(content, encoding="utf-8")
    print(f"✓ Synced Scope → {scope_path}")


def sync_risk_log() -> None:
    """Sync Risk Log sheet to docs/risk-log.md."""
    rows = read_sheet("Risk Log", "Risk Log!A1:D10")

    content = """# Animetta Risk Log

> 哪些事情最可能让项目失败。每个月更新一次。
>
> **Source of Truth**: [飞书表格](https://k1xawe1z6a6.feishu.cn/sheets/Io94sSOnShYdkXtuLl4c6FLDnnd)

## 当前风险（2026年7月）

| 风险 | 严重程度 | 应对方案 | 状态 |
|------|----------|----------|------|
"""

    for row in rows[1:]:  # Skip header
        if len(row) >= 4:
            content += f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} |\n"

    content += """
## 风险应对原则

### 高风险应对
- 每周检查一次
- 有明确的量化指标
- 月底必须验证

### 中风险应对
- 每月检查一次
- 有应对方案即可
- 不需要量化指标

## 月度风险评估

每月月底更新此文档：

1. 哪些风险发生了？
2. 应对方案是否有效？
3. 是否有新风险出现？
4. 下月重点关注哪些风险？

*Last synced: {timestamp}*
"""

    risk_path = DOCS_DIR / "risk-log.md"
    risk_path.parent.mkdir(parents=True, exist_ok=True)
    risk_path.write_text(content, encoding="utf-8")
    print(f"✓ Synced Risk Log → {risk_path}")


def sync_backlog() -> None:
    """Sync Backlog sheet to docs/backlog.md."""
    rows = read_sheet("Backlog", "Backlog!A1:D20")

    content = """# Animetta Backlog

> 想做但暂时没排期的任务集合。不是垃圾桶，而是"想法仓库"。
>
> **Source of Truth**: [飞书表格](https://k1xawe1z6a6.feishu.cn/sheets/Io94sSOnShYdkXtuLl4c6FLDnnd)

## 任务池

| 任务 | 优先级 | 依赖 | 备注 |
|------|--------|------|------|
"""

    for row in rows[1:]:  # Skip header
        if len(row) >= 4:
            content += f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} |\n"

    content += """
## 优先级说明

- **P0**：不做项目无法成立
- **P1**：做了项目明显更完整
- **P2**：锦上添花
- **P3**：以后再说

## 使用规则

1. 新想法先放 Backlog，不要直接进开发主线
2. 每月月底回顾 Backlog，调整优先级
3. 从 Backlog 提取任务到 Milestone 时，必须有明确的 Scope 和验收标准

*Last synced: {timestamp}*
"""

    backlog_path = DOCS_DIR / "backlog.md"
    backlog_path.parent.mkdir(parents=True, exist_ok=True)
    backlog_path.write_text(content, encoding="utf-8")
    print(f"✓ Synced Backlog → {backlog_path}")


def sync_not_now() -> None:
    """Sync Not Now sheet to docs/not-now.md."""
    rows = read_sheet("Not Now", "Not Now!A1:C10")

    content = """# Animetta Not Now - 2026年7月

> 本月明确禁止做的事情。防止 Scope 膨胀。
>
> **Source of Truth**: [飞书表格](https://k1xawe1z6a6.feishu.cn/sheets/Io94sSOnShYdkXtuLl4c6FLDnnd)

## 禁止任务清单

| 任务 | 禁止原因 | 解禁条件 |
|------|----------|----------|
"""

    for row in rows[1:]:  # Skip header
        if len(row) >= 3:
            content += f"| {row[0]} | {row[1]} | {row[2]} |\n"

    content += """
## 使用规则

1. 每次想做新功能，先检查是否在 Not Now 清单
2. 如果在清单中，问自己：解禁条件满足了吗？
3. 如果解禁条件未满足，坚决不做
4. 每月月底更新 Not Now 清单

## 如何解禁

当解禁条件满足时：
1. 从 Not Now 移除
2. 放入 Backlog（如果未排期）
3. 或放入 Milestone（如果已排期）

*Last synced: {timestamp}*
"""

    not_now_path = DOCS_DIR / "not-now.md"
    not_now_path.parent.mkdir(parents=True, exist_ok=True)
    not_now_path.write_text(content, encoding="utf-8")
    print(f"✓ Synced Not Now → {not_now_path}")


def main() -> None:
    """Main sync function."""
    import datetime

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    print("Syncing Feishu sheets to project docs...")
    print(f"Timestamp: {timestamp}")
    print()

    try:
        sync_roadmap()
        sync_scope()
        sync_risk_log()
        sync_backlog()
        sync_not_now()

        print()
        print("✓ All synced successfully!")
        print()
        print("Next steps:")
        print("1. Review the synced docs")
        print("2. Commit changes to git")
        print("3. Run this script weekly or before monthly review")

    except Exception as e:
        print(f"✗ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
