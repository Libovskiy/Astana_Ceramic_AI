#!/usr/bin/env python3
"""
Миграция 2: связь пункта обхода с заявкой главному инженеру.

    cd /Users/champ_01/Documents/FactoryAssistant
    python3 migrate_checklist_tasks.py

Идемпотентна.
"""
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_NAME = str(BASE_DIR / "factory.db")


def main():
    if not Path(DB_NAME).exists():
        print("✗ factory.db не найдена — запускай из корня проекта")
        sys.exit(1)

    conn = sqlite3.connect(DB_NAME, timeout=15)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(checklist_items)")]
        if not cols:
            print("✗ таблицы checklist_items нет — сначала migrate_checklist_photos.py")
            sys.exit(1)

        if "task_id" in cols:
            print("✓ task_id уже есть")
        else:
            conn.execute("ALTER TABLE checklist_items ADD COLUMN task_id INTEGER")
            conn.commit()
            print("✓ task_id добавлен")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_cl_items_task ON checklist_items(task_id)")
        conn.commit()
        print("✓ индекс на месте")
    finally:
        conn.close()

    print("\nГотово.")


if __name__ == "__main__":
    main()
