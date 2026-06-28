# Animetta 容器化部署设计

**日期**: 2026-06-06
**状态**: 已批准
**作者**: Sisyphus

---

## 概述

将 Animetta 项目容器化，支持 Docker Compose 自托管部署，并为后续 Kubernetes 扩展预留路径。

### 关键决策

1. **单容器架构**: 前后端打包在同一镜像中
2. **GPU 支持**: 使用 NVIDIA CUDA 基础镜像
3. **替换 edge-tts**: 因 Microsoft 封锁数据中心 IP，改用本地 TTS
4. **数据持久化**: 使用 Docker Volume 挂载 memory_db/ 和 data/

---

## 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Container                          │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Base: nvidia/cuda:12.4.1-runtime-ubuntu22.04        │  │
│  │  + Python 3.13 + Node.js 22 (Minecraft bot)          │  │
│  └───────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Application Layer                                    │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌──────────────┐ │  │
│  │  │   Backend   │  │  Frontend   │  │    nginx     │ │  │
│  │  │  (FastAPI)  │  │  (Vue/Vite) │  │  (reverse    │ │  │
│  │  │  :12394     │  │  (static)   │  │   proxy)     │ │  │
│  │  └─────────────┘  └─────────────┘  └──────────────┘ │  │
│  └───────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Services Layer                                       │  │
│  │  • LLM: DeepSeek (API)                               │  │
│  │  • TTS: Kokoro (GPU) + Qwen3 (GPU)                  │  │
│  │  • ASR: Faster-Whisper (GPU)                         │  │
│  │  • Memory: ChromaDB + SQLite (Volume)                │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
         │                              │
         ▼                              ▼
   ┌──────────┐                  ┌──────────┐
   │  Volume  │                  │  Volume  │
   │memory_db │                  │   data   │
   └──────────┘                  └──────────┘
```

---

## Dockerfile 设计

```dockerfile
# Stage 1: Builder - 安装依赖
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04 AS builder

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.13 python3.13-venv python3-pip \
    gcc g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Runtime - 最小化镜像
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

# 运行时依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.13 \
    ffmpeg \
    nginx \
    nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# 前端构建
COPY frontend/ /tmp/frontend/
RUN cd /tmp/frontend && npm install && npm run build \
    && cp -r dist /app/frontend \
    && rm -rf /tmp/frontend

# 复制后端代码
COPY --from=builder /usr/local/lib/python3.13 /usr/local/lib/python3.13
COPY src/ /app/src/
COPY config/ /app/config/
COPY scripts/ /app/scripts/

# nginx 配置
COPY docker/nginx.conf /etc/nginx/nginx.conf

# 环境变量
ENV PYTHONPATH=/app/src
ENV ANIMETTA_HOST=0.0.0.0
ENV ANIMETTA_PORT=12394

EXPOSE 80 12394

# 启动脚本
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
```

---

## Docker Compose 配置

```yaml
version: "3.8"

services:
  animetta:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "${ANIMETTA_PORT:-80}:80"
      - "12394:12394"
    environment:
      - ANIMETTA_HOST=0.0.0.0
      - ANIMETTA_PORT=12394
      - ANIMETTA_LOG_LEVEL=${ANIMETTA_LOG_LEVEL:-INFO}
      - DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY:-}
      - ANIMETTA_TTS=${ANIMETTA_TTS:-kokoro}
      - NVIDIA_VISIBLE_DEVICES=all
    volumes:
      - animetta-memory-db:/app/memory_db
      - animetta-data:/app/data
      - ./.env:/app/.env:ro
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:80/health"]
      interval: 30s
      timeout: 5s
      retries: 3

volumes:
  animetta-memory-db:
    driver: local
  animetta-data:
    driver: local
```

---

## TTS 迁移计划

### 问题

edge-tts 在容器中会被 Microsoft 封锁 WebSocket 连接，导致 `NoAudioReceived` 错误。

### 解决方案

替换为本地 GPU TTS：

| 优先级 | TTS 引擎 | 类型 | 说明 |
|--------|----------|------|------|
| 1️⃣ | Kokoro TTS | 本地 GPU | 默认推荐，82M 参数 |
| 2️⃣ | Qwen3 TTS | 本地 GPU | Voice clone 场景 |

### 依赖修改

**移除**:
- `edge-tts>=6.1.0`
- `zhipuai>=2.0.0` (GLM)

**保留**:
- `kokoro>=0.9.4`
- `qwen-tts>=0.1.1`

---

## 数据持久化

### 目录结构

```
/app/memory_db/                # ← Volume 挂载
├── chroma_v2/                 # ChromaDB V2 向量数据库
├── living_memory.sqlite       # SQLite FTS5 索引
├── wiki/                      # Markdown 知识库
└── raw/                       # 原始记忆数据

/app/data/                     # ← Volume 挂载
├── models/                    # TTS/ASR 模型缓存
│   ├── kokoro/                # Kokoro 模型 (~300MB)
│   ├── qwen3/                 # Qwen3 模型 (~3.4GB)
│   └── whisper/               # Whisper 模型 (~3GB)
├── chroma_db/                 # ChromaDB (待迁移统一)
└── stats.db                   # 统计数据
```

### 待办

- [ ] 迁移 `data/chroma_db/` 到 `memory_db/` 统一管理

---

## 健康检查

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:80/health"]
  interval: 30s
  timeout: 5s
  retries: 3
  start_period: 60s  # 首次启动等待模型加载
```

---

## Kubernetes 迁移路径

使用 `kompose` 工具自动转换：

```bash
kompose convert -f docker-compose.yml
```

添加 GPU 资源请求：

```yaml
resources:
  limits:
    nvidia.com/gpu: 1
```

---

## 实施步骤

1. 修改 Dockerfile (CUDA 基础镜像 + 多阶段构建)
2. 更新 docker-compose.yml (GPU 透传 + Volume)
3. 添加 nginx 配置和启动脚本
4. 修改 requirements.txt (移除 edge-tts)
5. 更新 TTS 配置 (默认使用 Kokoro)
6. 迁移 ChromaDB 目录
7. 测试部署流程
8. 更新文档

---

## 参考资料

- [edge-tts 容器化问题](https://github.com/rany2/edge-tts/issues/432)
- [openai-edge-tts Docker 配置](https://github.com/travisvn/openai-edge-tts)
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/)
