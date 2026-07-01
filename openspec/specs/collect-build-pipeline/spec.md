## MODIFIED Requirements

### Requirement: Target material gathering
系统 SHALL 自动寻找并收集建造所需的缺失材料，并 SHALL 使用 Resource Locator 优先定位最近的可获取来源。

#### Scenario: Gather missing materials
- **WHEN** 检测到某种材料数量 < 目标需求
- **THEN** Bot SHALL 使用 mc_collect 工具收集该材料
- **AND** mc_collect SHALL consult Resource Locator before blind exploration
- **AND** 优先收集最近的可获取来源

#### Scenario: Gather until sufficient
- **WHEN** Bot 执行收集行为
- **THEN** 持续收集直到该材料数量 >= 目标需求，或 Resource Locator 返回结构化无法获取原因

#### Scenario: Reuse discovered material source
- **WHEN** Resource Locator 已记录某材料的可用资源点
- **THEN** Bot SHALL 优先尝试该资源点，确认仍可采集后再继续搜索

#### Scenario: Stop repeating impossible search
- **WHEN** Resource Locator 返回 `TOOL_REQUIRED`, `UNSAFE_AREA`, `RESOURCE_NOT_FOUND`, or `SEARCH_TIMEOUT`
- **THEN** material gathering SHALL stop or trigger recovery instead of repeating the same failed search indefinitely
