"""
Миграция: досчитывает duration_minutes для уже завершённых
простоев, у которых колонка осталась пустой.

Зачем: end_downtime() раньше писал только ended_at/ended_by, а
duration_minutes оставался NULL. Аналитика трактует NULL как
"простой ещё идёт" и считает время до текущего момента — цифры
простоя росли сами по себе каждый день.

Запуск один раз: python migrate_downtime_duration.py
Разместить в корне проекта.
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))


import sqlite3
from datetime import datetime

from backend.config import DB_NAME


def migrate():

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    existing_columns = {
        row[1]
        for row in cursor.execute("PRAGMA table_info(downtime_log)").fetchall()
    }

    if "duration_minutes" not in existing_columns:
        cursor.execute("ALTER TABLE downtime_log ADD COLUMN duration_minutes INTEGER")
        print("Добавлена колонка duration_minutes.")

    cursor.execute(
        """
        SELECT id, started_at, ended_at
        FROM downtime_log
        WHERE ended_at IS NOT NULL AND duration_minutes IS NULL
        """
    )

    rows = cursor.fetchall()

    if not rows:
        print("Незаполненных завершённых простоев нет — чинить нечего.")
        conn.commit()
        conn.close()
        return

    fixed = 0
    skipped = 0

    for row in rows:

        try:
            started = datetime.strptime(row["started_at"], "%Y-%m-%d %H:%M:%S")
            ended = datetime.strptime(row["ended_at"], "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            print(f"  id={row['id']}: не удалось разобрать даты, пропускаю")
            skipped += 1
            continue

        minutes = max(round((ended - started).total_seconds() / 60), 0)

        cursor.execute(
            "UPDATE downtime_log SET duration_minutes = ? WHERE id = ?",
            (minutes, row["id"])
        )

        print(f"  id={row['id']}: {minutes} мин")

        fixed += 1

    conn.commit()
    conn.close()

    print(f"\nИсправлено записей: {fixed}")

    if skipped:
        print(f"Пропущено (битые даты): {skipped}")


if __name__ == "__main__":
    migrate()
