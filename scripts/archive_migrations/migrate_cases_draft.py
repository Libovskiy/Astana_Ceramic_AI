"""
Миграция: добавляет в таблицу cases поля для двухэтапного закрытия
обращения (черновик начальника смены + финал главного инженера).

Запуск один раз: python migrate_cases_draft.py
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
        ("draft_closed_by", "TEXT"),
        ("draft_resolution_comment", "TEXT"),
        ("draft_closed_at", "TEXT"),
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
