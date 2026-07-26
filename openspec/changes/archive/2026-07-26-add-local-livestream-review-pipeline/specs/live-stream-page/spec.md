## ADDED Requirements

### Requirement: 直播页面支持本地人眼评审模式
直播页面 SHALL 支持通过 URL 显式进入本地评审模式，并在该模式中使用与生产页面相同的控制器、视图和规范事件名称。

#### Scenario: 加载空场评审
- **WHEN** 页面使用 `review=1&scene=empty` 加载
- **THEN** 页面 SHALL 显示直播状态、Live2D 舞台和空弹幕状态

#### Scenario: 加载基础弹幕评审
- **WHEN** 页面使用 `review=1&scene=baseline` 加载
- **THEN** 页面 SHALL 以确定顺序显示基础弹幕并保持最终画面

### Requirement: 直播页面区分礼物与醒目留言
直播页面 SHALL 使用现有设计令牌为礼物和醒目留言提供可识别但克制的视觉标签，同时保持普通弹幕的结构和生产事件载荷兼容。

#### Scenario: 显示礼物弹幕
- **WHEN** 弹幕的 `is_gift` 为 true
- **THEN** 页面 SHALL 显示礼物标签并保留用户名、时间和正文

#### Scenario: 显示醒目留言
- **WHEN** 弹幕的 `is_super_chat` 为 true
- **THEN** 页面 SHALL 显示醒目留言标签并保留用户名、时间和正文
