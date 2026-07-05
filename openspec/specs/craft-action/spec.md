# craft-action Specification

## Purpose
TBD - created by archiving change mc-bot-craft-equipment. Update Purpose after archive.
## Requirements
### Requirement: Craft Action
bot SHALL 支持 `craft` action，允许合成物品。

#### Scenario: 成功合成
- **WHEN** 收到 `{"action":"craft","params":{"recipe":"wooden_pickaxe","count":1}}`
- **THEN** 合成木镐，返回 `{"status":"success","result":"Crafted wooden_pickaxe x1"}`

#### Scenario: 配方未找到
- **WHEN** 收到 `{"action":"craft","params":{"recipe":"invalid_item","count":1}}`
- **THEN** 返回 `{"status":"error","result":"Recipe not found: invalid_item"}`

### Requirement: 配方查找
bot SHALL 使用 minecraft-data 的 recipes 数据查找配方。

#### Scenario: 查找配方
- **WHEN** recipe 为 "iron_pickaxe"
- **THEN** 从 mcData.recipesByName 查找配方

#### Scenario: 配方不存在
- **WHEN** recipe 为 "nonexistent_item"
- **THEN** 返回空结果

### Requirement: 材料检查
bot SHALL 在合成前检查材料是否足够。

#### Scenario: 材料足够
- **WHEN** 背包中有足够材料
- **THEN** 继续合成

#### Scenario: 材料不足
- **WHEN** 背包中材料不足
- **THEN** 返回 `{"status":"error","result":"Missing materials: iron_ingot x2, stick x1"}`

### Requirement: 工作台查找
bot SHALL 对于 3x3 合成自动查找附近的工作台。

#### Scenario: 找到工作台
- **WHEN** 32 格范围内有工作台
- **THEN** 使用工作台进行合成

#### Scenario: 无工作台
- **WHEN** 32 格范围内无工作台
- **THEN** 返回 `{"status":"error","result":"No crafting table found nearby"}`
