# live-stream-page Specification

## Purpose
TBD - created by archiving change live-stream-page. Update Purpose after archive.
## Requirements
### Requirement: 页面可被 OBS 浏览器源捕获
直播页面 SHALL 作为独立 HTML 文件部署，可通过 HTTP URL 直接访问，无需 Vue Router 或其他前端框架。

#### Scenario: OBS 浏览器源访问
- **WHEN** 用户在 OBS 中添加浏览器源并输入页面 URL
- **THEN** 页面 SHALL 正常加载并显示 Live2D 形象和弹幕

### Requirement: 页面尺寸为 9:16 竖屏
直播页面 SHALL 使用 1080 × 1920px 的固定尺寸，适配竖屏直播场景。

#### Scenario: 页面尺寸验证
- **WHEN** 页面加载完成
- **THEN** 页面尺寸 SHALL 为 1080 × 1920px

### Requirement: Live2D 形象全屏居中渲染
直播页面 SHALL 在全屏 canvas 中居中渲染 Live2D 虚拟形象，形象 SHALL 占据大部分画面。

#### Scenario: Live2D 渲染
- **WHEN** 页面加载完成
- **THEN** Live2D 形象 SHALL 在画面中心显示，占据约 80% 的画面高度

### Requirement: 弹幕悬浮窗显示在左上角
直播页面 SHALL 在左上角显示弹幕悬浮窗，悬浮窗 SHALL 具有半透明毛玻璃背景。

#### Scenario: 弹幕悬浮窗初始状态
- **WHEN** 页面加载完成
- **THEN** 弹幕悬浮窗 SHALL 显示在左上角（top: 40px, left: 40px）

#### Scenario: 毛玻璃效果
- **WHEN** 弹幕悬浮窗显示
- **THEN** 背景 SHALL 使用 backdrop-filter: blur(20px) 实现毛玻璃效果

### Requirement: 弹幕悬浮窗可收纳
弹幕悬浮窗 SHALL 支持点击展开/收起，收起时仅显示小图标。

#### Scenario: 展开状态
- **WHEN** 用户点击弹幕头部或展开按钮
- **THEN** 弹幕列表 SHALL 展开显示，最多显示最近 500 条弹幕

#### Scenario: 收起状态
- **WHEN** 用户点击收起按钮
- **THEN** 弹幕列表 SHALL 收起，仅显示弹幕图标和未读数量

### Requirement: 弹幕实时更新
直播页面 SHALL 通过 WebSocket 连接接收实时弹幕数据。

#### Scenario: 接收弹幕
- **WHEN** WebSocket 连接正常且有新弹幕到达
- **THEN** 弹幕 SHALL 添加到列表底部，旧弹幕 SHALL 被移除（超过 500 条时）

#### Scenario: 连接断开
- **WHEN** WebSocket 连接断开
- **THEN** 页面 SHALL 显示连接断开状态，并尝试自动重连

### Requirement: 背景图片可配置
直播页面 SHALL 支持通过 URL 参数配置背景图片。

#### Scenario: 自定义背景
- **WHEN** URL 包含 `?bg=xxx.jpg` 参数
- **THEN** 页面 SHALL 使用指定的背景图片，否则使用默认背景

