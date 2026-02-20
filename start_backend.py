#!/usr/bin/env python
"""启动脚本 - 设置正确的 Python 路径"""
import sys
import os

# 添加 src 目录到 Python 路径
src_path = os.path.join(os.path.dirname(__file__), 'src')
sys.path.insert(0, src_path)

# 导入并运行服务器
if __name__ == '__main__':
    from anima.config import AppConfig
    import uvicorn

    # 加载配置
    config = AppConfig.load()

    print(f"启动 Socket.IO 服务器...")
    print(f"访问 http://{config.system.host}:{config.system.port} 测试")

    uvicorn.run(
        'anima.socketio_server:socket_app',
        host=config.system.host,
        port=config.system.port,
        reload=True
    )
