"""
测试服务器启动和向量搜索初始化
"""

import asyncio
import socketio
import time

# 创建Socket.IO客户端
sio = socketio.AsyncClient()

@sio.event
async def connect():
    print("OK - Connected to server")

    # 发送测试消息以触发session初始化
    test_data = {
        "text": "你好，我是测试用户",
        "metadata": {},
        "from_name": "test_user"
    }

    print("\n[Step 1] Sending test message to trigger initialization")
    print("-" * 80)
    await sio.emit('text_input', test_data)

    # 等待响应
    await asyncio.sleep(3)

    # 断开连接
    print("\n[Step 2] Test completed, disconnecting...")
    print("-" * 80)
    await sio.disconnect()

@sio.event
async def disconnect():
    print("OK - Disconnected from server")

@sio.event
async def text(data):
    """接收文本响应"""
    print(f"\n[Server Response]")
    print("-" * 80)
    print(f"Text: {data.get('text', '')[:100]}...")
    print(f"Seq: {data.get('seq', 0)}")
    print(f"Complete: {data.get('is_complete', False)}")

@sio.event
async def transcript(data):
    """接收转录文本（ASR结果）"""
    print(f"\n[Transcript]")
    print("-" * 80)
    print(f"Text: {data.get('text', '')}")

@sio.event
async def audio(data):
    """接收音频数据"""
    print(f"\n[Audio]")
    print("-" * 80)
    print(f"Format: {data.get('format', 'unknown')}")
    print(f"Seq: {data.get('seq', 0)}")

@sio.event
async def error(data):
    """接收错误"""
    print(f"\n[ERROR]")
    print("-" * 80)
    print(f"Message: {data.get('message', '')}")

async def test_server():
    """测试服务器连接和向量搜索"""
    print("=" * 80)
    print("Testing Server with Vector Search")
    print("=" * 80)

    try:
        print("\n[Connecting to server]")
        print("-" * 80)
        await sio.connect('http://localhost:12394')

        # 等待事件处理
        await sio.wait()

    except Exception as e:
        print(f"\nERROR - {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_server())
