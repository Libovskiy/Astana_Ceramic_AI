import sqlite3
from datetime import datetime

from backend.config import DB_NAME


def save_message(case_id: int, role: str, message: str):

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO chat_history (
            case_id,
            role,
            message,
            created_at
        )
        VALUES (?, ?, ?, ?)
    """, (
        case_id,
        role,
        message,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))

    conn.commit()
    conn.close()


def get_history(case_id: int):

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT role, message
        FROM chat_history
        WHERE case_id=?
        ORDER BY id
    """, (case_id,))

    rows = cursor.fetchall()

    conn.close()

    return rows
