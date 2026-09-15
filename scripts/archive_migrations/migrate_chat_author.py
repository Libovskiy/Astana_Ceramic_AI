"""
Миграция: добавляет в chat_history поле author.

Зачем: раньше в переписке хранилась только роль ("worker" /
"assistant"), без имени. Для диалога, в котором участвуют рабочий,
ИИ, начальник смены и слесарь, этого мало — рабочий должен видеть,
кто именно ему ответил, а не безликое "worker".

Запуск один раз: python migrate_chat_author.py
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))


import sqlite3

from backend.config import DB_NAME


def migrate():

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    existing = {
        row[1]
        for row in cursor.execute("PRAGMA table_info(chat_history)").fetchall()
    }

    added = []

    if "author" not in existing:
        cursor.execute("ALTER TABLE chat_history ADD COLUMN author TEXT")
        added.append("author")

    if "author_role" not in existing:
        cursor.execute("ALTER TABLE chat_history ADD COLUMN author_role TEXT")
        added.append("author_role")

    conn.commit()
    conn.close()

    if added:
        print(f"Добавлены колонки: {', '.join(added)}")
    else:
        print("Колонки уже есть — ничего не менял.")


if __name__ == "__main__":
    migrate()
