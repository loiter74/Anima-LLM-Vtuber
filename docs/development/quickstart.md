# 快速开始

> 5 分钟运行 Anima 项目

---

## 环境要求

- **Python**: 3.8+
- **Node.js**: 18+
- **pnpm**: 8+ (推荐) 或 npm
- **系统**: Windows / macOS / Linux

---

## 方法 1：使用启动脚本（推荐）

### Windows (PowerShell)

```powershell
# 克隆项目
git clone https://github.com/yourusername/anima.git
cd anima

# 一键启动（自动安装依赖并运行）
.\scripts\start.ps1
```

### Unix / macOS

```bash
# 克隆项目
git clone https://github.com/yourusername/anima.git
cd anima

# 一键启动（自动安装依赖并运行）
./scripts/start.sh
```

启动脚本会自动：
1. ✅ 安装 Python 依赖（`pip install -r requirements.txt`）
2. ✅ 安装前端依赖（`cd frontend && pnpm install`）
3. ✅ 启动后端服务（端口 12394）
4. ✅ 启动前端服务（端口 3000）
5. ✅ 自动打开浏览器访问 `http://localhost:3000`

---

## 方法 2：手动启动

### 步骤 1：安装 Python 依赖

```bash
pip install -r requirements.txt
```

### 步骤 2：配置 API Key

创建 `.env` 文件：

```bash
# .env
GLM_API_KEY=your_glm_api_key_here
```

或直接设置环境变量：

```bash
export GLM_API_KEY=your_glm_api_key_here
```

### 步骤 3：启动后端

```bash
python -m anima.socketio_server
```

后端会启动在 `http://localhost:12394`

### 步骤 4：启动前端（新终端）

```bash
cd frontend
pnpm install  # 首次运行需要安装依赖
pnpm dev
```

前端会启动在 `http://localhost:3000`

---

## 验证安装

### 1. 检查后端

访问 `http://localhost:12394`，应该看到：

```json
{"status": "ok", "message": "Anima Socket.IO Server"}
```

### 2. 检查前端

访问 `http://localhost:3000`，应该看到聊天界面。

### 3. 测试对话

1. 在输入框输入："你好"
2. 点击发送
3. 应该看到 AI 回复和 Live2D 模型的表情变化

---

## 配置服务商

### 切换 LLM 服务商

编辑 `config/config.yaml`：

```yaml
services:
  agent: glm  # 可选: openai, glm, ollama, mock
```

### 切换 ASR 服务商

```yaml
services:
  asr: faster_whisper  # 可选: openai, glm, faster_whisper, mock
```

### 切换 TTS 服务商

```yaml
services:
  tts: edge  # 可选: openai, glm, edge, mock
```

---

## 下载 Live2D 模型

### 自动下载（推荐）

```bash
# Windows PowerShell
.\scripts\download_live2d.ps1

# Unix/macOS
python scripts/download_live2d_model.py
```

### 手动下载

1. 访问 [Live2D 官网](https://www.live2d.com/)
2. 下载免费模型（推荐 Hiyori）
3. 解压到 `frontend/public/live2d/` 目录

---

## 常见问题

### Q: 端口被占用？

**A**: 修改端口配置

```yaml
# config/config.yaml
system:
  port: 12395  # 修改后端端口
```

```bash
# 前端端口
cd frontend
pnpm dev --port 3001
```

### Q: API Key 无效？

**A**: 检查 `.env` 文件是否存在，确保 `GLM_API_KEY` 已设置。

### Q: Live2D 模型不显示？

**A**:
1. 检查控制台是否有错误
2. 确认模型文件已正确下载到 `frontend/public/live2d/`
3. 检查 `config/features/live2d.yaml` 中的 `model.path` 配置

### Q: 前端无法连接后端？

**A**:
1. 确认后端已启动（`http://localhost:12394`）
2. 检查 CORS 配置（默认允许 `localhost:3000`）
3. 查看浏览器控制台的连接错误

---

## 下一步

- 📖 [项目介绍](../overview/intro.md) - 了解项目背景和特性
- 🏗️ [架构设计](../architecture/design-patterns.md) - 学习设计模式应用
- 🚀 [添加新服务](./adding-services.md) - 扩展 LLM/ASR/TTS 服务
- 🎭 [Live2D 设置](../overview/intro.md#live2d-情感系统) - 配置虚拟形象

---

## 停止服务

### Windows

```powershell
.\scripts\stop.ps1
```

### Unix / macOS

```bash
./scripts/stop.sh
```

或手动 `Ctrl+C` 停止服务。

---

**最后更新**: 2026-02-28
