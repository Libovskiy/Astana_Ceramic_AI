#!/usr/bin/env python3
"""
Миграция 4: обход связывается с обращениями (cases), а не с задачами.

    cd /Users/champ_01/Documents/FactoryAssistant
    python3 migrate_checklist_cases.py

Колонка task_id остаётся на месте — в ней лежат уже созданные заявки,
удалять историю незачем. Новые обходы будут писать case_id.
Идемпотентна.
"""
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_NAME = str(BASE_DIR / "factory.db")


def add_column(conn, table, column, decl):
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    if not cols:
        print(f"✗ таблицы {table} нет — сначала migrate_checklist_photos.py")
        sys.exit(1)
    if column in cols:
        print(f"✓ {table}.{column} уже есть")
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    print(f"✓ {table}.{column} добавлен")


def main():
    if not Path(DB_NAME).exists():
        print("✗ factory.db не найдена — запускай из корня проекта")
        sys.exit(1)

    conn = sqlite3.connect(DB_NAME, timeout=15)
    try:
        add_column(conn, "checklist_items", "case_id", "INTEGER")
        add_column(conn, "checklist_photos", "case_id", "INTEGER")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cl_items_case ON checklist_items(case_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cl_photos_case ON checklist_photos(case_id)")
        conn.commit()
        print("✓ индексы на месте")
    finally:
        conn.close()

    print("\nГотово.")


if __name__ == "__main__":
    main()
