#!/usr/bin/env python3
"""
Миграция: хранение обходов смены и фото на диске.

Запускать ДО замены кода:
    cd /Users/champ_01/Documents/FactoryAssistant
    python3 migrate_checklist_photos.py

Идемпотентна — можно гонять повторно.
"""
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_NAME = str(BASE_DIR / "factory.db")
PHOTOS_DIR = BASE_DIR / "data" / "checklist_photos"


DDL = [
    # ── сам обход ──────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS checklist_rounds (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at   TEXT,
        finished_at  TEXT DEFAULT CURRENT_TIMESTAMP,
        shift        TEXT,
        username     TEXT,
        full_name    TEXT,
        total_count  INTEGER DEFAULT 0,
        ok_count     INTEGER DEFAULT 0,
        warn_count   INTEGER DEFAULT 0,
        bad_count    INTEGER DEFAULT 0
    )""",

    # ── пункты обхода (по одному на единицу оборудования) ──
    """CREATE TABLE IF NOT EXISTS checklist_items (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        round_id     INTEGER NOT NULL,
        equipment_id INTEGER,
        status       TEXT,
        note         TEXT,
        created_at   TEXT DEFAULT CURRENT_TIMESTAMP
    )""",

    # ── фото ───────────────────────────────────────────────
    # rel_path — путь ОТНОСИТЕЛЬНО data/checklist_photos,
    # чтобы папку можно было перенести при переезде на сервер.
    """CREATE TABLE IF NOT EXISTS checklist_photos (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        round_id     INTEGER,
        equipment_id INTEGER,
        file_hash    TEXT NOT NULL,
        rel_path     TEXT NOT NULL,
        mime         TEXT,
        size_bytes   INTEGER,
        width        INTEGER,
        height       INTEGER,
        uploaded_by  TEXT,
        created_at   TEXT DEFAULT CURRENT_TIMESTAMP
    )""",

    "CREATE INDEX IF NOT EXISTS idx_cl_items_round  ON checklist_items(round_id)",
    "CREATE INDEX IF NOT EXISTS idx_cl_items_eq     ON checklist_items(equipment_id)",
    "CREATE INDEX IF NOT EXISTS idx_cl_photos_round ON checklist_photos(round_id)",
    "CREATE INDEX IF NOT EXISTS idx_cl_photos_hash  ON checklist_photos(file_hash)",
    "CREATE INDEX IF NOT EXISTS idx_cl_rounds_fin   ON checklist_rounds(finished_at)",
]


def main():
    print(f"БД:    {DB_NAME}")
    print(f"Фото:  {PHOTOS_DIR}")

    if not Path(DB_NAME).exists():
        print("✗ factory.db не найдена — запускай из корня проекта")
        sys.exit(1)

    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    # папка не должна попасть в git
    gitignore = BASE_DIR / ".gitignore"
    try:
        current = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
        if "data/checklist_photos" not in current:
            with gitignore.open("a", encoding="utf-8") as f:
                f.write("\n# фото обходов смены — не в репозиторий\ndata/checklist_photos/\n")
            print("✓ data/checklist_photos/ добавлено в .gitignore")
    except Exception as e:
        print(f"! .gitignore не тронут: {e}")

    conn = sqlite3.connect(DB_NAME, timeout=15)
    try:
        for stmt in DDL:
            conn.execute(stmt)
        conn.commit()
    finally:
        conn.close()

    # проверка
    conn = sqlite3.connect(DB_NAME, timeout=15)
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'checklist_%'"
    )]
    conn.close()

    for t in ("checklist_rounds", "checklist_items", "checklist_photos"):
        print(f"{'✓' if t in names else '✗'} {t}")

    print("\nГотово. Теперь можно менять код.")


if __name__ == "__main__":
    main()
