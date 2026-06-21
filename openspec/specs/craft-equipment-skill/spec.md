# craft-equipment-skill Specification

## Purpose
TBD - created by archiving change mc-bot-craft-equipment. Update Purpose after archive.
## Requirements
### Requirement: 智能装备合成
`craft_equipment` Skill SHALL 根据可用材料自动选择最佳装备。

#### Scenario: 有木头
- **WHEN** 背包中有 oak_log >= 3
- **THEN** 制造木棍、木镐、木斧、木剑

#### Scenario: 有铁锭
- **WHEN** 背包中有 iron_ingot >= 10
- **THEN** 制造铁镐、铁斧、铁剑

#### Scenario: 有钻石
- **WHEN** 背包中有 diamond >= 3
- **THEN** 制造钻石镐、钻石斧、钻石剑

### Requirement: 基础工具合成
`craft_basic_tools` Skill SHALL 制造基础木制工具。

#### Scenario: 有木头
- **WHEN** 背包中有 oak_log >= 3
- **THEN** 制造木棍、木镐、木斧、木剑

### Requirement: 盔甲合成
`craft_armor` Skill SHALL 制造铁质盔甲套装。

#### Scenario: 有足够铁锭
- **WHEN** 背包中有 iron_ingot >= 24
- **THEN** 制造铁头盔、铁胸甲、铁护腿、铁靴子

#### Scenario: 铁锭不足
- **WHEN** 背包中 iron_ingot < 24
- **THEN** 跳过该 Skill

