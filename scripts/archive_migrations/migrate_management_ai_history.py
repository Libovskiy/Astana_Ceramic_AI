
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))

import sqlite3
from backend.config import DB_NAME

def migrate():
    conn=sqlite3.connect(DB_NAME)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS management_ai_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            full_name TEXT,
            role TEXT,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_management_ai_history_created_at ON management_ai_history(created_at)")
    conn.commit()
    conn.close()
    print("OK: management_ai_history готова.")

if __name__ == "__main__":
    migrate()
