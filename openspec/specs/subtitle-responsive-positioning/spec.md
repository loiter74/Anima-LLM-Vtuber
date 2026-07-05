## Purpose
Defines the accepted behavior and requirements for the subtitle-responsive-positioning capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: 比例化位置存储
字幕位置 SHALL 以相对于 Live2D 容器的比例值（0.0~1.0）存储，而非绝对像素值。`posX` 表示面板中心点在容器中的水平比例，`posY` 表示面板底边在容器中的垂直比例。`null` 表示使用默认居中位置。存储数据 SHALL 包含 `_version: 2` 版本标记。

#### Scenario: 新用户默认居中
- **WHEN** 用户从未拖拽过字幕且 `localStorage` 中无位置数据
- **THEN** `store.posX` 和 `store.posY` 均为 `null`，字幕使用默认居中定位

#### Scenario: 用户拖拽字幕
- **WHEN** 用户在 Live2D 区域内拖拽字幕面板到新位置
- **THEN** 系统根据拖拽终点计算 `posX`/`posY` 的比例值（面板中心点 X / 容器宽度，面板底边距 / 容器高度），持久化到 localStorage 中 `_version: 2` 格式

#### Scenario: 旧格式数据迁移
- **WHEN** 系统读取到 `_version` 缺失且 `posX`/`posY` 为数字的旧格式数据
- **THEN** 系统将旧像素值除以当前容器宽高转换为比例值，写入 `_version: 2` 格式，并保存到 localStorage

### Requirement: 窗口缩放自适应
字幕 SHALL 在 Live2D 容器尺寸变化时（窗口缩放、面板折叠/展开、Live2D 弹出/回收），根据存储的比例值重新计算像素位置，保持相对定位不变。

#### Scenario: 窗口水平缩放
- **WHEN** 用户拖拽字幕后水平缩放窗口
- **THEN** 字幕的 `left` 像素值按比例更新（`容器宽度 × posX`），字幕在容器中的相对水平位置不变

#### Scenario: 面板折叠
- **WHEN** 用户折叠右侧 InteractivePanel
- **THEN** Live2D 容器变宽，字幕位置根据新容器尺寸和存储的比例值重新计算

#### Scenario: Live2D 弹出模式切换
- **WHEN** 用户点击弹出/回收 Live2D 按钮
- **THEN** 字幕位置根据新容器尺寸和存储的比例值重新计算

#### Scenario: 默认居中模式缩放
- **WHEN** 字幕处于默认居中模式（`posX === null`）且窗口缩放
- **THEN** 字幕通过 CSS（动态 `left` 计算加 `transform: translateX(-50%)`）自动保持居中，无需 JS 干预

### Requirement: 拖拽后保持居中对齐
字幕 SHALL 在自定义位置模式下始终使用 `transform: translateX(-50%)`，使面板以其水平中心点为锚点定位，保持视觉居中效果。

#### Scenario: 拖拽后字幕居中
- **WHEN** 用户拖拽字幕到自定义位置后释放
- **THEN** 字幕面板以 `left`（`posX × 容器宽度`）为中心点，通过 `translateX(-50%)` 将面板水平居中于该点

#### Scenario: 字幕文本变长
- **WHEN** 字幕文本内容变长（如从短句变为长句）
- **THEN** 面板宽度自动增加，但由于 `translateX(-50%)`，面板始终以 `posX` 指定的位置为中心

### Requirement: 动态面板偏移
默认居中模式下，字幕的 `left` SHALL 基于 InteractivePanel 的实际宽度动态计算，而非硬编码固定偏移，确保在各种面板宽度下正确居中于 Live2D 可用区域。

#### Scenario: 默认居中计算
- **WHEN** 字幕处于默认居中模式且 InteractivePanel 可见
- **THEN** 字幕的 `left` 值为 `(容器宽度 - 面板宽度) / 2`，即 Live2D 可见区域的水平中心

#### Scenario: 面板不可见时回退
- **WHEN** InteractivePanel 被折叠或不存在于 DOM 中
- **THEN** 字幕回退到 `left: 50%` 即容器全宽中心
