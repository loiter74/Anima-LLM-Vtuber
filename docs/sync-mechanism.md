# Animetta 数据同步机制

> 保证飞书表格和项目文档两处记录联动

## 架构设计

```
┌─────────────────────────────────────────────────────────┐
│                    飞书表格 (Source of Truth)              │
│  token: Io94sSOnShYdkXtuLl4c6FLDnnd                     │
├─────────────────────────────────────────────────────────┤
│  Sheet1      │ 36个月路线图                              │
│  Epic列表    │ 6个Epic                                  │
│  Milestone   │ M1-M3                                    │
│  Issue模板   │ 背景/范围/不做范围/验收标准                │
│  Roadmap     │ 5个月方向                                 │
│  Scope       │ 7月做/不做                               │
│  Risk Log    │ 6个风险                                  │
│  Backlog     │ 11个任务                                 │
│  Not Now     │ 7个禁止任务                              │
│  Review      │ 月度复盘                                 │
└─────────────────────────────────────────────────────────┘
                           │
                           │ 每周同步 / 手动触发
                           ▼
┌─────────────────────────────────────────────────────────┐
│                    项目文档 (只读副本)                     │
│  Anima/docs/                                            │
├─────────────────────────────────────────────────────────┤
│  roadmap.md           │ 从Roadmap子表同步                │
│  scope-2026-07.md     │ 从Scope子表同步                  │
│  risk-log.md          │ 从Risk Log子表同步               │
│  backlog.md           │ 从Backlog子表同步                │
│  not-now.md           │ 从Not Now子表同步                │
│  retrospective/       │ 月底手动填写                     │
└─────────────────────────────────────────────────────────┘
```

## 同步规则

### 飞书 → 项目文档（自动）

**触发方式**：
1. 每周定时任务自动同步
2. 手动运行：`python scripts/sync_feishu_to_docs.py`

**同步内容**：
- Roadmap → `docs/roadmap.md`
- Scope-2026-07 → `docs/scope-2026-07.md`
- Risk Log → `docs/risk-log.md`
- Backlog → `docs/backlog.md`
- Not Now → `docs/not-now.md`

**不自动同步**：
- `docs/retrospective/` — 月底手动填写
- Issue模板 — 模板固定，不需要同步

### 项目文档 → 飞书（手动）

**场景**：用户在项目文档中更新了详细说明（如Scope、Risk）

**操作**：
1. 更新项目文档
2. 手动更新飞书表格对应子表
3. 或运行反向同步脚本（待实现）

## 使用流程

### 日常更新（飞书为主）

1. **更新任务状态**：直接在飞书表格修改
2. **添加新任务**：在Backlog或Not Now子表添加
3. **调整优先级**：在Backlog子表修改
4. **查看项目状态**：打开飞书表格

### 月底复盘（项目文档为主）

1. **运行同步脚本**：`python scripts/sync_feishu_to_docs.py`
2. **填写复盘文档**：`docs/retrospective/2026-07.md`
3. **更新飞书表格**：将复盘结论同步到Monthly Review子表
4. **提交git**：保留历史记录

### 定时任务读取

定时任务直接从飞书表格读取：
```bash
lark-cli sheets +csv-get \
  --spreadsheet-token "Io94sSOnShYdkXtuLl4c6FLDnnd" \
  --sheet-name "Roadmap" \
  --range "Roadmap!A1:D10"
```

## 同步脚本

### 位置
`scripts/sync_feishu_to_docs.py`

### 用法
```bash
# 同步飞书到项目文档
python scripts/sync_feishu_to_docs.py

# 查看帮助
python scripts/sync_feishu_to_docs.py --help
```

### 定时任务集成
```bash
# 每周日凌晨2点同步
0 2 * * 0 cd /path/to/anima && python scripts/sync_feishu_to_docs.py
```

## 注意事项

1. **飞书是Source of Truth**：所有状态更新优先在飞书进行
2. **项目文档是副本**：同步后不要手动修改状态字段
3. **复盘文档例外**：月底复盘在项目文档中手动填写
4. **冲突处理**：如果两边都更新了，以飞书为准

## 未来扩展

1. **反向同步脚本**：从项目文档同步到飞书
2. **Webhook触发**：飞书更新时自动触发同步
3. **版本控制**：同步时自动提交git
4. **通知机制**：同步失败时通知用户

*Last updated: 2026-07-04*
