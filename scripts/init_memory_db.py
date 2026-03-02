"""
初始化记忆数据库
"""
import sqlite3
from pathlib import Path

def init_database():
    # 确保 data 目录存在
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)

    db_path = data_dir / "memories.db"

    print(f"Initializing database: {db_path}")

    conn = sqlite3.connect(db_path)

    # 创建表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            turn_id TEXT NOT NULL UNIQUE,
            session_id TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            user_input TEXT NOT NULL,
            agent_response TEXT NOT NULL,
            emotions TEXT,
            metadata TEXT,
            importance REAL DEFAULT 0.5
        )
    """)

    # 创建索引
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_session_timestamp "
        "ON memories(session_id, timestamp DESC)"
    )

    # 创建全文搜索
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
        USING fts5(user_input, agent_response, content=memories, content_rowid=id)
    """)

    conn.commit()
    conn.close()

    print("OK - Memory database initialized")

if __name__ == "__main__":
    init_database()
