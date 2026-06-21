# vertical-background Specification

## Purpose
TBD - created by archiving change live-stream-page. Update Purpose after archive.
## Requirements
### Requirement: 9:16 背景图片文件夹
系统 SHALL 提供 `frontend/public/backgrounds/vertical/` 文件夹存放 9:16 竖屏背景图片。

#### Scenario: 文件夹存在
- **WHEN** 用户访问 `frontend/public/backgrounds/vertical/` 路径
- **THEN** 文件夹 SHALL 存在且可访问

### Requirement: 背景图片分辨率
9:16 背景图片 SHALL 使用 1080 × 1920px 分辨率，与直播页面尺寸一致。

#### Scenario: 图片尺寸验证
- **WHEN** 用户放置背景图片到 vertical 文件夹
- **THEN** 图片 SHALL 为 1080 × 1920px 或等比例缩放

### Requirement: 背景图片格式支持
系统 SHALL 支持 JPG、PNG、WebP 格式的背景图片。

#### Scenario: 格式支持
- **WHEN** 用户上传 JPG/PNG/WebP 格式的图片
- **THEN** 系统 SHALL 正确加载并显示该图片

### Requirement: 背景图片选择机制
系统 SHALL 提供机制让用户选择使用哪张背景图片。

#### Scenario: URL 参数选择
- **WHEN** 直播页面 URL 包含 `?bg=xxx.jpg` 参数
- **THEN** 系统 SHALL 使用 `backgrounds/vertical/xxx.jpg` 作为背景

#### Scenario: 默认背景
- **WHEN** URL 不包含 `?bg` 参数
- **THEN** 系统 SHALL 使用默认背景图片或渐变色

