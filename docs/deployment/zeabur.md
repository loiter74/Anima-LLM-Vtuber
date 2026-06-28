# Zeabur 部署指南

本指南介绍如何将 Animetta 部署到 Zeabur 平台。

## 目录

- [前置要求](#前置要求)
- [注册 Zeabur 账号](#注册-zeabur-账号)
- [部署后端服务](#部署后端服务)
- [GPU 支持](#gpu-支持)
- [环境变量配置](#环境变量配置)
- [域名绑定](#域名绑定)
- [前端部署](#前端部署)
- [本地 Docker Compose 部署](#本地-docker-compose-部署)
- [GitHub Actions 自动部署](#github-actions-自动部署)
- [故障排除](#故障排除)

## 前置要求

- GitHub 账号（用于登录 Zeabur 和托管代码）
- Animetta 项目已推送到 GitHub
- LLM API Key（GLM、DeepSeek 或 OpenAI）

## 注册 Zeabur 账号

1. 访问 [zeabur.com](https://zeabur.com)
2. 点击 **Get Started** 或 **Sign Up**
3. 使用 GitHub 账号登录
4. 授权 Zeabur 访问你的 GitHub 仓库

## 部署后端服务

### 方式一：从 GitHub 部署（推荐）

1. 登录 [Zeabur Dashboard](https://dash.zeabur.com)
2. 点击 **Create Project**，选择区域（推荐 `hkg` 香港）
3. 点击 **Add Service** → **Deploy from GitHub**
4. 选择 `animetta` 仓库
5. Zeabur 会自动检测 `Dockerfile.cuda` 并开始构建
6. 等待构建完成（约 3-5 分钟）

> **注意**: 项目使用 `Dockerfile.cuda` 构建，包含 CUDA 12.4 运行时和 Kokoro TTS 引擎。需要在 Zeabur 开启 GPU 实例支持（见下方）。

## GPU 支持

Animetta 使用 Kokoro TTS 和 Whisper ASR，两者均支持 GPU 加速。在 Zeabur 部署时：

1. 在服务详情页进入 **Settings**
2. 在 **Instance Type** 中选择带 GPU 的实例（推荐 NVIDIA A10G）
3. 确保环境变量 `ANIMETTA_DEVICE=cuda` 已设置

> **无 GPU 也能运行**：设置 `ANIMETTA_DEVICE=cpu` 即可回退到 CPU 模式，TTS 和 ASR 会自动使用 CPU 推理，性能较低但功能完整。

### 方式二：使用 zeabur.json 配置

项目根目录的 `zeabur.json` 文件已预配置：

```json
{
  "$schema": "https://schema.zeabur.app/latest.json",
  "name": "animetta",
  "description": "AI Virtual Companion / VTuber Framework",
  "services": {
    "backend": {
      "dockerfile": "Dockerfile.cuda",
      "rootDir": ".",
      "env": {
        "ANIMETTA_HOST": "0.0.0.0",
        "ANIMETTA_PORT": "12394",
        "ANIMETTA_LOG_LEVEL": "INFO",
        "ANIMETTA_TTS": "kokoro",
        "ANIMETTA_DEVICE": "cuda",
        "PYTHONPATH": "/app/src"
      },
      "ports": [
        {
          "containerPort": 12394,
          "protocol": "TCP"
        }
      ],
      "healthCheck": {
        "path": "/health",
        "port": 12394,
        "interval": 30,
        "timeout": 5,
        "retries": 3
      }
    }
  }
}
```

## 环境变量配置

在 Zeabur Dashboard 的服务设置中配置以下环境变量：

### 必需变量

| 变量名 | 说明 | 示例值 |
|--------|------|--------|
| `GLM_API_KEY` | 智谱 AI API Key | `your_glm_api_key` |
| `OPENAI_API_KEY` | OpenAI/DeepSeek API Key | `sk-xxx` |
| `OPENAI_BASE_URL` | OpenAI 兼容 API 地址 | `https://api.deepseek.com/v1` |

### 可选变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `ANIMETTA_LLM` | LLM 服务商 | `deepseek` |
| `ANIMETTA_TTS` | TTS 服务商 | `kokoro` |
| `ANIMETTA_ASR` | ASR 服务商 | `faster_whisper` |
| `ANIMETTA_VAD` | VAD 服务商 | `silero` |
| `ANIMETTA_LOG_LEVEL` | 日志级别 | `INFO` |
| `LANGFUSE_PUBLIC_KEY` | LangFuse 追踪 | - |
| `LANGFUSE_SECRET_KEY` | LangFuse 追踪 | - |

### 配置步骤

1. 在 Zeabur Dashboard 点击你的服务
2. 进入 **Variables** 标签
3. 点击 **Add Variable** 添加环境变量
4. 或者点击 **Bulk Edit** 批量导入 `.env` 文件内容

## 域名绑定

### 使用 Zeabur 提供的域名

1. 在服务详情页点击 **Networking**
2. Zeabur 会自动分配一个 `*.zeabur.app` 域名
3. 点击域名即可访问服务

### 绑定自定义域名

1. 在 **Networking** 页面点击 **Custom Domain**
2. 输入你的域名（如 `animetta.yourdomain.com`）
3. 按照提示在你的 DNS 服务商添加 CNAME 记录：
   ```
   animetta.yourdomain.com → cname.zeabur.com
   ```
4. 等待 DNS 生效（通常 5-30 分钟）
5. Zeabur 会自动配置 SSL 证书

## 前端部署

前端（Vue 3 + Vite）可以选择部署到 Vercel 或 Zeabur。

### 方案一：部署到 Vercel（推荐）

1. 访问 [vercel.com](https://vercel.com) 并登录
2. 点击 **New Project** → 导入 `animetta` 仓库
3. 配置：
   - **Framework Preset**: Vite
   - **Root Directory**: `frontend`
   - **Build Command**: `pnpm build`
   - **Output Directory**: `dist`
4. 添加环境变量：
   ```
   VITE_API_URL=https://your-backend.zeabur.app
   VITE_WS_URL=wss://your-backend.zeabur.app
   ```
5. 点击 **Deploy**

### 方案二：部署到 Zeabur

1. 在同一项目中添加新服务
2. 选择 **Deploy from GitHub**
3. 配置：
   - **Root Directory**: `frontend`
   - **Build Command**: `pnpm build`
   - **Output Directory**: `dist`
4. 添加环境变量指向后端服务

### 前端环境变量

创建 `frontend/.env.production` 文件：

```env
VITE_API_URL=https://your-backend.zeabur.app
VITE_WS_URL=wss://your-backend.zeabur.app
```

## 本地 Docker Compose 部署

在部署到 Zeabur 之前，建议先用 Docker Compose 在本地测试。

### GPU 模式（推荐）

需要 NVIDIA GPU + Docker Desktop 的 GPU 支持：

```bash
# 复制环境变量
cp .env.example .env
# 编辑 .env 填入 API Key

# 启动（GPU 模式）
docker compose up -d

# 查看日志
docker compose logs -f
```

### CPU 模式

无 GPU 环境使用 CPU 备用配置：

```bash
docker compose -f docker-compose.cpu.yml up -d
```

### 验证

```bash
# 健康检查
curl http://localhost:12394/health

# 前端访问
open http://localhost
```

> 详细说明参见 [Docker 部署指南](docker.md)。

## GitHub Actions 自动部署

项目已配置 GitHub Actions 工作流，推送到 main 分支时自动部署。

### 工作流配置

文件位置：`.github/workflows/deploy-zeabur.yml`

```yaml
name: Deploy to Zeabur

on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Deploy to Zeabur
        uses: zeabur/deploy-action@v1
        with:
          service-id: ${{ secrets.ZEABUR_SERVICE_ID }}
          server-token: ${{ secrets.ZEABUR_SERVER_TOKEN }}
```

### 配置 GitHub Secrets

1. 在 GitHub 仓库的 **Settings** → **Secrets and variables** → **Actions**
2. 添加以下 Secrets：

| Secret 名称 | 获取方式 |
|-------------|---------|
| `ZEABUR_SERVICE_ID` | Zeabur Dashboard → 服务详情 → Settings → Service ID |
| `ZEABUR_SERVER_TOKEN` | Zeabur Dashboard → Settings → Server Token |

## 故障排除

### 构建失败

**问题**: `pip install` 超时或失败
**解决**: Zeabur 默认使用海外节点，网络应该正常。如果仍然失败，检查 `requirements.txt` 中是否有不兼容的包。

**问题**: 内存不足
**解决**: 在 Zeabur Dashboard 增加服务的内存配额（推荐 1GB+）。

### 服务无法访问

**问题**: 健康检查失败
**解决**: 
1. 检查环境变量是否正确配置
2. 查看服务日志排查错误
3. 确保 `ANIMETTA_HOST=0.0.0.0`

**问题**: WebSocket 连接失败
**解决**: 
1. 确保前端 `VITE_WS_URL` 使用 `wss://` 协议
2. 检查 Zeabur 的 WebSocket 支持（默认支持）

### 数据持久化

Zeabur 的容器是无状态的，重启后数据会丢失。如需持久化：

1. 使用 Zeabur 的 **Persistent Storage** 功能
2. 或将数据存储到外部服务（如 Supabase、PlanetScale）

### 查看日志

1. 在 Zeabur Dashboard 点击服务
2. 进入 **Logs** 标签
3. 实时查看服务日志

## 费用说明

Zeabur 提供免费额度：
- 每月 5GB 流量
- 512MB 内存
- 共享 CPU

超出后按量计费，详见 [Zeabur 定价](https://zeabur.com/pricing)。

## 相关链接

- [Zeabur 官方文档](https://zeabur.com/docs)
- [Zeabur Discord](https://discord.gg/zeabur)
- [Animetta GitHub](https://github.com/loiter74/animetta)
- [Animetta 文档](../)
