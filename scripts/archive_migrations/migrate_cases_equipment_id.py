"""
Миграция: добавляет equipment_id в таблицу cases.

До этого обращения привязывались к станку только по строке
"machine" (например "messersi"), а после последней правки для
пошагового /diagnose это же поле стало хранить полное название
станка ("упаковочная машина") — то есть одно и то же оборудование
могло иметь два РАЗНЫХ значения "machine" в разных обращениях.
Для журнала жизни оборудования нужна точная привязка — по ID,
а не по шаткому совпадению строки.

Запуск один раз: python migrate_cases_equipment_id.py
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

    if "equipment_id" not in existing_columns:

        cursor.execute("ALTER TABLE cases ADD COLUMN equipment_id INTEGER")

        print("Добавлена колонка equipment_id в cases.")

    else:

        print("Колонка equipment_id уже существует — пропускаю.")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    migrate()
