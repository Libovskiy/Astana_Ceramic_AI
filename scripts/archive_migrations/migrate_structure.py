"""
Структура производства: этапы, части оборудования, документы.

ЧТО ДОБАВЛЯЕТСЯ И ПОЧЕМУ ИМЕННО ТАК

    production_stages   Этапы больше не зашиты в код. Сейчас
                        mass/forming/drying/kiln/packaging живут
                        строками в equipment.stage и в списках
                        внутри модулей. Технолог не может добавить
                        шестой этап, не позвав разработчика.
                        Таблица заполняется пятью существующими —
                        ничего не ломается, но появляется место,
                        куда добавлять новые.

    equipment_parts     Части станка: валок, подшипниковый узел,
                        привод. Конкретных названий не заводим —
                        их знает механик, а не я.

    equipment_documents Существующая таблица расширяется: документ
                        теперь можно привязать не только к станку,
                        но и к части или к этапу. Отдельную таблицу
                        документов заводить не стали — поля те же,
                        а два хранилища документов означали бы, что
                        человек не знает, где искать.

Удаления нет нигде. Вместо него is_active = 0: у станка есть
история простоев и обращений, у части — история замены, и стереть
их вместе с записью значило бы потерять то, ради чего система
собирается.

Запуск: python migrate_structure.py
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))


import sqlite3

from backend.config import DB_NAME


SCHEMA = """

-- =========================================================
-- ЭТАПЫ ПРОИЗВОДСТВА
-- =========================================================

CREATE TABLE IF NOT EXISTS production_stages (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Совпадает с equipment.stage: mass, forming, drying,
    -- kiln, packaging. Новые этапы получают свой ключ.
    stage_key TEXT NOT NULL UNIQUE,

    name TEXT NOT NULL,
    description TEXT,

    sort_order INTEGER DEFAULT 100,

    is_active INTEGER DEFAULT 1,

    created_by TEXT,
    created_at TEXT
);


-- =========================================================
-- ЧАСТИ ОБОРУДОВАНИЯ
-- =========================================================

CREATE TABLE IF NOT EXISTS equipment_parts (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    equipment_id INTEGER NOT NULL,

    name TEXT NOT NULL,
    description TEXT,

    -- Инвентарный или каталожный номер, если завод его ведёт
    part_number TEXT,

    photo_path TEXT,

    -- Свободный статус: работает / под замену / заменена.
    -- Жёсткого списка нет намеренно: у валка и у датчика
    -- состояния описываются по-разному.
    status TEXT,

    note TEXT,

    is_active INTEGER DEFAULT 1,

    created_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT,

    FOREIGN KEY (equipment_id) REFERENCES equipment(id)
);
"""


INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_stage_order ON production_stages(sort_order)",
    "CREATE INDEX IF NOT EXISTS idx_parts_eq ON equipment_parts(equipment_id, is_active)",
    "CREATE INDEX IF NOT EXISTS idx_docs_part ON equipment_documents(part_id)",
]


# Пять существующих этапов. Ключи — те же, что уже стоят в
# equipment.stage, иначе связь оборудования с этапом порвётся.
BASE_STAGES = [
    ("mass", "Массоподготовка", 10),
    ("forming", "Формовка", 20),
    ("drying", "Сушка", 30),
    ("kiln", "Обжиг", 40),
    ("packaging", "Упаковка", 50),
]


def migrate():

    from datetime import datetime

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.executescript(SCHEMA)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for key, name, order in BASE_STAGES:
        cursor.execute(
            """
            INSERT OR IGNORE INTO production_stages
                (stage_key, name, sort_order, created_by, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (key, name, order, "система", now)
        )

    # -----------------------------------------
    # Документы: привязка к части и к этапу
    # -----------------------------------------

    doc_columns = {
        row[1]
        for row in cursor.execute("PRAGMA table_info(equipment_documents)").fetchall()
    }

    for column, definition in [
        ("part_id", "INTEGER"),
        ("stage_key", "TEXT"),
        # Документ может устареть — убираем из списка, но файл и
        # запись остаются: на него могли ссылаться в переписке
        ("is_active", "INTEGER DEFAULT 1"),
    ]:
        if column not in doc_columns:
            cursor.execute(f"ALTER TABLE equipment_documents ADD COLUMN {column} {definition}")
            print(f"  equipment_documents.{column} добавлена")

    # -----------------------------------------
    # Оборудование: архивирование вместо удаления
    # -----------------------------------------

    equipment_columns = {
        row[1]
        for row in cursor.execute("PRAGMA table_info(equipment)").fetchall()
    }

    if "is_active" not in equipment_columns:
        cursor.execute("ALTER TABLE equipment ADD COLUMN is_active INTEGER DEFAULT 1")
        print("  equipment.is_active добавлена")

    if "description" not in equipment_columns:
        cursor.execute("ALTER TABLE equipment ADD COLUMN description TEXT")
        print("  equipment.description добавлена")

    if "photo_path" not in equipment_columns:
        cursor.execute("ALTER TABLE equipment ADD COLUMN photo_path TEXT")
        print("  equipment.photo_path добавлена")

    if "inventory_number" not in equipment_columns:
        cursor.execute("ALTER TABLE equipment ADD COLUMN inventory_number TEXT")
        print("  equipment.inventory_number добавлена")

    for statement in INDEXES:
        cursor.execute(statement)

    conn.commit()

    stages = cursor.execute("SELECT COUNT(*) FROM production_stages").fetchone()[0]
    parts = cursor.execute("SELECT COUNT(*) FROM equipment_parts").fetchone()[0]
    equipment = cursor.execute("SELECT COUNT(*) FROM equipment").fetchone()[0]

    conn.close()

    print("\nСТРУКТУРА ПРОИЗВОДСТВА")
    print("=" * 50)
    print(f"  Этапов:      {stages}")
    print(f"  Оборудования:{equipment:>4}")
    print(f"  Частей:      {parts}")
    print("\nЭтапы заведены в таблицу — технолог может добавлять свои.")
    print("Существующие пять не тронуты, ключи прежние.\n")


if __name__ == "__main__":
    migrate()
