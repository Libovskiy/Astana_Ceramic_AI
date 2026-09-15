#!/usr/bin/env python3
"""
Миграция 3: привести время в таблицах обхода к местному.

Первая версия роутера писала CURRENT_TIMESTAMP (это UTC), остальной ACAI
пишет datetime.now() (местное). Сдвигаем записи обхода на смещение часового
пояса, чтобы всё лежало в одном формате.

    cd /Users/champ_01/Documents/FactoryAssistant
    python3 migrate_checklist_time.py

Запускать ОДИН раз — повторный запуск сдвинет ещё раз. Скрипт это отслеживает
через таблицу applied_migrations.
"""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_NAME = str(BASE_DIR / "factory.db")
TAG = "checklist_time_to_local"


def offset_hours() -> float:
    """Смещение местного времени от UTC прямо сейчас (для Астаны +5)."""
    delta = datetime.now() - datetime.utcnow()
    return round(delta.total_seconds() / 3600)


def main():
    if not Path(DB_NAME).exists():
        print("✗ factory.db не найдена — запускай из корня проекта")
        sys.exit(1)

    off = offset_hours()
    print(f"Смещение часового пояса: {off:+d} ч")

    if off == 0:
        print("Смещения нет — сдвигать нечего.")
        return

    conn = sqlite3.connect(DB_NAME, timeout=15)
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS applied_migrations (
            tag TEXT PRIMARY KEY, applied_at TEXT)""")

        already = conn.execute(
            "SELECT applied_at FROM applied_migrations WHERE tag = ?", (TAG,)
        ).fetchone()
        if already:
            print(f"✓ уже применялась {already[0]} — пропускаю")
            return

        shift = f"+{off} hours"
        moved = 0

        for table, cols in (
            ("checklist_rounds", ("finished_at",)),
            ("checklist_items", ("created_at",)),
            ("checklist_photos", ("created_at",)),
        ):
            existing = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
            if not existing:
                continue
            for col in cols:
                if col not in existing:
                    continue
                cur = conn.execute(
                    f"UPDATE {table} SET {col} = datetime({col}, ?) WHERE {col} IS NOT NULL",
                    (shift,),
                )
                moved += cur.rowcount
                print(f"  {table}.{col}: {cur.rowcount}")

        conn.execute(
            "INSERT INTO applied_migrations (tag, applied_at) VALUES (?, ?)",
            (TAG, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
        print(f"\n✓ сдвинуто записей: {moved}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
