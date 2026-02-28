# 部署指南

> 将 Anima 部署到生产环境的完整指南

---

## 目录

1. [部署架构](#部署架构)
2. [环境准备](#环境准备)
3. [后端部署](#后端部署)
4. [前端部署](#前端部署)
5. [生产优化](#生产优化)

---

## 部署架构

### 推荐架构

```
┌─────────────────────────────────────────────────────────────┐
│                        用户                                 │
└─────────────────────────────────────────────────────────────┘
                          ↓ HTTPS
┌─────────────────────────────────────────────────────────────┐
│                   Nginx / Caddy                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ - 反向代理                                             │  │
│  │ - SSL/TLS 终止                                        │  │
│  │ - 静态文件服务                                         │  │
│  │ - 负载均衡（可选）                                     │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
           ↕                          ↕
    WebSocket (12394)         HTTP (3000)
┌─────────────────────┐   ┌─────────────────────┐
│  后端服务            │   │  前端服务            │
│  (Python/FastAPI)   │   │  (Next.js)           │
│  - Socket.IO Server │   │  - 静态导出          │
│  - LLM/ASR/TTS      │   │  - 或 Node.js Server │
│  - Live2D 后端      │   │  - Live2D 前端       │
└─────────────────────┘   └─────────────────────┘
```

### 端口规划

| 服务 | 端口 | 说明 |
|------|------|------|
| Nginx/Caddy | 80, 443 | 对外服务端口 |
| 后端 Socket.IO | 12394 | WebSocket 服务端口 |
| 前端 Next.js | 3000 | HTTP 服务端口（可选） |

---

## 环境准备

### 服务器要求

**最低配置**：
- CPU: 2 核
- 内存: 2GB
- 存储: 20GB
- 操作系统: Ubuntu 20.04+ / CentOS 8+ / Debian 11+

**推荐配置**：
- CPU: 4 核
- 内存: 4GB
- 存储: 40GB SSD
- 操作系统: Ubuntu 22.04 LTS

### 依赖安装

```bash
# 更新系统
sudo apt update && sudo apt upgrade -y

# 安装 Python 3.8+
sudo apt install -y python3 python3-pip python3-venv

# 安装 Node.js 18+
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs

# 安装 Nginx
sudo apt install -y nginx

# 安装 Supervisor（进程管理）
sudo apt install -y supervisor

# 安装 Git
sudo apt install -y git
```

---

## 后端部署

### 步骤 1: 克隆代码

```bash
# 克隆仓库
cd /opt
sudo git clone https://github.com/your-username/anima.git
cd anima

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 步骤 2: 配置环境变量

```bash
# 创建 .env 文件
cat > .env << EOF
# GLM API Key（必需）
GLM_API_KEY=your_glm_api_key_here

# 其他 API Keys（可选）
# OPENAI_API_KEY=your_openai_api_key
EOF

# 设置权限
chmod 600 .env
```

### 步骤 3: 配置生产环境

```yaml
# config/config.yaml
system:
  host: "0.0.0.0"        # 监听所有接口
  port: 12394
  log_level: "INFO"       # 生产环境使用 INFO
  cors_origins:
    - "https://your-domain.com"  # 生产域名
    - "https://www.your-domain.com"

services:
  agent: glm              # 生产推荐使用 GLM
  asr: faster_whisper    # 免费且离线
  tts: edge              # 免费无配额
  vad: silero            # 生产级 VAD

features:
  live2d:
    enabled: true
    model:
      path: "/live2d/hiyori/Hiyori.model3.json"
```

### 步骤 4: 使用 Supervisor 管理进程

```bash
# 创建 Supervisor 配置
sudo cat > /etc/supervisor/conf.d/anima-backend.conf << EOF
[program:anima-backend]
command=/opt/anima/venv/bin/python -m anima.socketio_server
directory=/opt/anima
user=www-data
autostart=true
autorestart=true
stderr_logfile=/var/log/anima/backend.err.log
stdout_logfile=/var/log/anima/backend.out.log
environment=PYTHONUNBUFFERED="1"
EOF

# 创建日志目录
sudo mkdir -p /var/log/anima
sudo chown www-data:www-data /var/log/anima

# 启动服务
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start anima-backend

# 查看状态
sudo supervisorctl status anima-backend
```

---

## 前端部署

### 方案 1: 静态导出（推荐）

**优势**：简单、性能好、成本低

```bash
cd frontend

# 构建静态文件
pnpm build

# 生成的文件在 frontend/out/ 目录
```

**Nginx 配置**：

```nginx
# /etc/nginx/sites-available/anima
server {
    listen 80;
    server_name your-domain.com;

    # 强制 HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    # SSL 证书配置
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    # 前端静态文件
    location / {
        root /opt/anima/frontend/out;
        try_files $uri $uri/ /index.html;
    }

    # Live2D 模型文件
    location /live2d/ {
        alias /opt/anima/public/live2d/;
        add_header Cache-Control "public, max-age=31536000";
    }

    # 配置文件
    location /config/ {
        alias /opt/anima/frontend/public/config/;
        add_header Cache-Control "public, max-age=3600";
    }

    # WebSocket 反向代理
    location /socket.io/ {
        proxy_pass http://localhost:12394;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_read_timeout 86400;
    }
}
```

**启用配置**：

```bash
# 创建符号链接
sudo ln -s /etc/nginx/sites-available/anima /etc/nginx/sites-enabled/

# 测试配置
sudo nginx -t

# 重启 Nginx
sudo systemctl restart nginx
```

### 方案 2: Node.js 服务

**优势**：支持 SSR、动态路由

```bash
cd frontend

# 构建
pnpm build

# 使用 PM2 管理
sudo npm install -g pm2

# 启动服务
cd /opt/anima/frontend
pm2 start npm --name "anima-frontend" -- run start

# 保存 PM2 配置
pm2 save
pm2 startup
```

**Nginx 反向代理**：

```nginx
location / {
    proxy_pass http://localhost:3000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection 'upgrade';
    proxy_set_header Host $host;
    proxy_cache_bypass $http_upgrade;
}
```

---

## SSL/TLS 配置

### 使用 Let's Encrypt 免费证书

```bash
# 安装 Certbot
sudo apt install -y certbot python3-certbot-nginx

# 获取证书（自动配置 Nginx）
sudo certbot --nginx -d your-domain.com -d www.your-domain.com

# 自动续期
sudo certbot renew --dry-run
```

### 或使用自签名证书（开发环境）

```bash
# 生成自签名证书
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /etc/ssl/private/anima-selfsigned.key \
  -out /etc/ssl/certs/anima-selfsigned.crt
```

---

## 生产优化

### 后端优化

**1. 使用 Gunicorn + Uvicorn**

```bash
# 安装 Gunicorn
pip install gunicorn

# 启动（4 个 worker）
gunicorn anima.socketio_server:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:12394 \
  --access-logfile /var/log/anima/access.log \
  --error-logfile /var/log/anima/error.log
```

**2. 配置日志轮转**

```bash
# /etc/logrotate.d/anima
/var/log/anima/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 www-data www-data
    sharedscripts
    postrotate
        sudo supervisorctl restart anima-backend
    endscript
}
```

**3. 启用缓存（可选）**

```python
# 使用 Redis 缓存音量包络
import redis

redis_client = redis.Redis(host='localhost', port=6379, db=0)

@lru_cache(maxsize=128)
def calculate_volume_envelope(self, audio_path: str) -> List[float]:
    # 先检查 Redis
    cached = redis_client.get(f"volume:{audio_path}")
    if cached:
        return json.loads(cached)

    # 计算并缓存
    volumes = self._calculate(audio_path)
    redis_client.setex(f"volume:{audio_path}", 3600, json.dumps(volumes))
    return volumes
```

### 前端优化

**1. 启用 CDN**

```javascript
// next.config.js
module.exports = {
  assetPrefix: 'https://cdn.your-domain.com',
  publicRuntimeConfig: {
    staticFolder: '/public',
  },
}
```

**2. 启用 Gzip 压缩**

```javascript
// next.config.js
module.exports = {
  compress: true,  // Next.js 默认启用
}
```

**3. 图片优化**

```typescript
// 使用 Next.js Image 组件
import Image from 'next/image'

<Image
  src="/live2d/preview.png"
  width={800}
  height={600}
  priority  // 首屏图片
  alt="Live2D Preview"
/>
```

### 监控和日志

**1. 使用 PM2 Monitor**

```bash
# 安装 PM2 Plus（可选）
pm2 install pm2-logrotate

# 查看实时日志
pm2 logs anima-backend

# 查看监控
pm2 monit
```

**2. 使用 Grafana + Prometheus**

```bash
# 安装 Prometheus
sudo apt install -y prometheus

# 配置 Prometheus
cat > /etc/prometheus/prometheus.yml << EOF
scrape_configs:
  - job_name: 'anima'
    static_configs:
      - targets: ['localhost:12394']
EOF

# 启动 Prometheus
sudo systemctl start prometheus
```

---

## 安全加固

### 1. 防火墙配置

```bash
# 安装 UFW
sudo apt install -y ufw

# 允许 SSH
sudo ufw allow 22/tcp

# 允许 HTTP/HTTPS
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# 启用防火墙
sudo ufw enable

# 查看状态
sudo ufw status
```

### 2. 限制 API 访问

```python
# src/anima/socketio_server.py
from fastapi import Header, HTTPException

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response
```

### 3. 速率限制

```python
# 使用 slowapi 限制速率
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.post("/api/chat")
@limiter.limit("10/minute")  # 每分钟最多 10 次
async def chat(request: Request):
    ...
```

---

## 故障排查

### 常见问题

**1. WebSocket 连接失败**

```bash
# 检查后端是否运行
sudo supervisorctl status anima-backend

# 检查端口是否监听
sudo netstat -tlnp | grep 12394

# 检查 Nginx 配置
sudo nginx -t
```

**2. Live2D 模型加载失败**

```bash
# 检查文件权限
ls -la /opt/anima/public/live2d/

# 修复权限
sudo chown -R www-data:www-data /opt/anima/public/live2d/
```

**3. 内存不足**

```bash
# 检查内存使用
free -h

# 检查进程内存
ps aux --sort=-%mem | head -n 10

# 添加 Swap（临时）
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

---

## 总结

### 部署检查清单

**后端**：
- ✅ Python 3.8+ 虚拟环境
- ✅ 依赖安装完成
- ✅ .env 配置正确
- ✅ Supervisor 进程管理
- ✅ 日志轮转配置

**前端**：
- ✅ Next.js 构建成功
- ✅ Nginx 配置正确
- ✅ SSL/TLS 证书
- ✅ WebSocket 反向代理

**安全**：
- ✅ 防火墙启用
- ✅ API 密钥保护
- ✅ 速率限制
- ✅ 安全响应头

**监控**：
- ✅ 日志收集
- ✅ 进程监控
- ✅ 性能监控

### 成本估算

**单服务器部署**：
- 服务器（4核4GB）: ~$20/月
- 域名: ~$10/年
- SSL证书: 免费（Let's Encrypt）

**总成本**: ~$20/月

---

**最后更新**: 2026-02-28
