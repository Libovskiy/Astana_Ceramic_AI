"""
Миграция: добавляет в cases отслеживание шага ИИ-диагностики.

current_step  — на каком шаге предложений находится обращение (0 = ещё не начато)
resolved_by   — 'ai' (закрыто автоматически по ответу "Помогло")
                или 'specialist' (закрыто через черновик/подтверждение)

Запуск один раз: python migrate_cases_ai_steps.py
Разместить в корне проекта.
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))


import sqlite3
from backend.config import DB_NAME


def migrate():

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    existing_columns = {
        row[1]
        for row in cursor.execute("PRAGMA table_info(cases)").fetchall()
    }

    new_columns = [
        ("current_step", "INTEGER DEFAULT 0"),
        ("resolved_by", "TEXT"),
    ]

    for column_name, column_type in new_columns:

        if column_name not in existing_columns:
            cursor.execute(
                f"ALTER TABLE cases ADD COLUMN {column_name} {column_type}"
            )
            print(f"Добавлена колонка {column_name}")

    conn.commit()
    conn.close()

    print("Миграция завершена.")


if __name__ == "__main__":
    migrate()
