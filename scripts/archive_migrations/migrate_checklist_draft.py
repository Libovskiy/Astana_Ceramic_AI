#!/usr/bin/env python3
"""
Миграция 5: черновик незавершённого обхода.

Один черновик на пользователя — он физически не может обходить цех
дважды одновременно. Само содержимое лежит JSON-строкой: состав пунктов
меняется вместе с парком оборудования, и городить под это колонки
бессмысленно.

    cd /Users/champ_01/Documents/FactoryAssistant
    python3 migrate_checklist_draft.py

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
        conn.execute("""CREATE TABLE IF NOT EXISTS checklist_drafts (
            username    TEXT PRIMARY KEY,
            started_at  TEXT,
            updated_at  TEXT,
            payload     TEXT NOT NULL
        )""")
        conn.commit()
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='checklist_drafts'"
        )]
        print("✓ checklist_drafts" if names else "✗ таблица не создалась")
    finally:
        conn.close()

    print("\nГотово.")


if __name__ == "__main__":
    main()
