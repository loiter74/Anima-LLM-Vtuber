# Live2D Cubism Core 设置指南

## 问题描述

`pixi-live2d-display` 的 cubism4 模块需要 `live2dcubismcore.js` 核心库才能运行。这是一个 Live2D 官方的专有文件，不包含在 npm 包中，需要手动下载。

## 下载步骤

### 1. 访问 Live2D 官网

访问：https://www.live2d.com/download/cubism-sdk/download-native/

### 2. 注册账号

- 点击 "Download" 按钮
- 使用邮箱注册 Live2D 账号（免费）
- 验证邮箱

### 3. 下载 Cubism SDK

- 登录后找到 **Cubism SDK for Web**
- 下载最新版本（推荐 Cubism 4 SDK for Web）
- 文件名类似：`CubismSdkForWeb-4-r.1.zip`

### 4. 解压并提取核心库

解压下载的 zip 文件，找到以下文件：

```
CubismSdkForWeb-4-r.1/
└── src/
    └── live2dcubismcore.js  ← 这是需要的文件
```

### 5. 放置到项目中

将 `live2dcubismcore.js` 复制到：

```
frontend/public/live2dcubismcore.js
```

## 验证安装

1. 确保文件已放置在 `frontend/public/live2dcubismcore.js`
2. 重启前端开发服务器：`pnpm dev`
3. 打开浏览器控制台，应该看到：`[Live2DService] ✅ All libraries loaded`
4. 不应该再看到 "Could not find Cubism 4 runtime" 错误

## 常见问题

### Q: 为什么要注册账号？
A: Live2D Cubism Core 是 Live2D 官方的专有库，虽然免费使用，但需要同意许可协议。

### Q: 可以跳过这一步吗？
A: 可以尝试使用 cubism5 版本（修改 `Live2DService.ts` 中的导入路径），但 cubism5 可能还不够稳定。

### Q: 文件很大吗？
A: `live2dcubismcore.js` 大约 300-500KB，不会影响太多性能。

## 许可证

Live2D Cubism Core 遵循 Live2D Proprietary License：
- 免费用于个人和非商业项目
- 商业使用需要购买许可证
- 详情：https://www.live2d.com/eula/live2d-free-license-agreement/
