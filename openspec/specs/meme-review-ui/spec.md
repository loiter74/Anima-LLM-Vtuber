# meme-review-ui Specification

## Purpose
Vue 3 梗筛选卡片页面，逐个展示待筛选梗，支持好/坏投票和 AI 吐槽展示。

Defines the accepted behavior and requirements for the meme-review-ui capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.
## Requirements

### Requirement: 梗筛选页面路由
系统 SHALL 在 Anima 前端新增 `/meme-review` 路由，加载 `MemeReview.vue` 视图组件。

#### Scenario: 路由访问
- **WHEN** 用户导航到 `/meme-review`
- **THEN** 系统 SHALL 显示梗筛选页面
- **AND** 自动从后端获取待筛选梗列表

### Requirement: 梗卡片展示
系统 SHALL 以卡片形式逐个展示待筛选的梗。

#### Scenario: 卡片内容展示
- **WHEN** 页面加载梗列表
- **THEN** 每张卡片 SHALL 显示：梗文本（text）、来源平台（source_platform）、标签（tags）、认知分析（humor_mechanism、emotional_tone）
- **AND** 如果有 source_url，SHALL 显示可点击的 B 站视频链接

#### Scenario: 逐个展示
- **WHEN** 页面有多个待筛选梗
- **THEN** 系统 SHALL 一次只展示一个梗
- **AND** 用户做出选择后自动切换到下一个

#### Scenario: 空列表状态
- **WHEN** 后端返回空梗列表
- **THEN** 页面 SHALL 显示 "暂无待筛选梗，去采集一些吧" 提示

### Requirement: 好/坏投票
系统 SHALL 提供「好」和「烂」两个按钮用于梗质量投票。

#### Scenario: 标记为「好」
- **WHEN** 用户点击「好」按钮
- **THEN** 系统 SHALL 调用 `POST /api/memes/review` 提交 `status: "good"`
- **AND** 卡片 SHALL 以绿色动画过渡到下一个梗
- **AND** 更新进度计数（已筛选 N/M）

#### Scenario: 标记为「烂」
- **WHEN** 用户点击「烂」按钮
- **THEN** 系统 SHALL 调用 `POST /api/memes/review` 提交 `status: "bad"`
- **AND** 卡片 SHALL 以红色动画过渡
- **AND** 如果后端返回 AI 吐槽内容，SHALL 在过渡前展示吐槽

### Requirement: AI 吐槽展示
系统 SHALL 在标记烂梗后展示 AI 生成的吐槽。

#### Scenario: 吐槽展示
- **WHEN** 后端返回 AI 吐槽内容
- **THEN** 页面 SHALL 在卡片下方以气泡或 toast 形式展示吐槽文本
- **AND** 吐槽展示 2 秒后自动消失并切换到下一个梗

#### Scenario: 吐槽加载中
- **WHEN** AI 吐槽正在生成中
- **THEN** 系统 SHALL 显示加载动画（如 "AI 正在吐槽..."）

### Requirement: 进度追踪
系统 SHALL 展示当前筛选进度。

#### Scenario: 进度显示
- **WHEN** 页面展示梗列表
- **THEN** 系统 SHALL 显示 "第 N 个 / 共 M 个" 的进度指示器
- **AND** 好/坏计数分别显示

### Requirement: 数据集导出
系统 SHALL 提供导出已筛选高质量梗的功能。

#### Scenario: 导出按钮
- **WHEN** 用户点击「导出数据集」按钮
- **THEN** 系统 SHALL 调用 `GET /api/memes/dataset`
- **AND** 下载包含高质量梗的 JSON 文件
