"""
Миграция: добавляет в таблицу cases поля closed_by и resolution_comment,
нужные для сценария "начальник смены подтверждает, как устранили проблему".

Запуск один раз: python migrate_cases_closure.py
Разместить в корне проекта (рядом с factory.db) или указать путь через config.
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

    if "closed_by" not in existing_columns:
        cursor.execute("ALTER TABLE cases ADD COLUMN closed_by TEXT")
        print("Добавлена колонка closed_by")

    if "resolution_comment" not in existing_columns:
        cursor.execute("ALTER TABLE cases ADD COLUMN resolution_comment TEXT")
        print("Добавлена колонка resolution_comment")

    conn.commit()
    conn.close()

    print("Миграция завершена.")


if __name__ == "__main__":
    migrate()
