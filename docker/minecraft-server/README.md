# Animetta MC Server (Docker)

Minecraft 服务器，用于 Animetta MC Bot 测试。

## 快速启动

```bash
cd docker/minecraft-server
./start.sh
```

## 手动操作

```bash
# 启动
docker compose up -d

# 查看日志
docker compose logs -f

# 停止
docker compose down

# 重启
docker compose restart
```

## 配置

编辑 `docker-compose.yml` 修改服务器设置：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `DIFFICULTY` | normal | 难度 |
| `GAMEMODE` | survival | 游戏模式 |
| `ONLINE_MODE` | false | 在线验证 |
| `MEMORY` | 4G | JVM 内存 |
| `VIEW_DISTANCE` | 10 | 视距 |

## 数据

服务器数据存储在 `./data` 目录，包括：
- 世界存档
- 配置文件
- 日志

## Animetta Bot 连接

Bot 配置在 `config/tools.yaml`：
```yaml
minecraft:
  enabled: true
  bot:
    host: "localhost"
    port: 25565
    username: "AnimettaBot"
```
