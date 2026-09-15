"""
Миграция: бригада у пользователя и у обращения.

Зачем: у каждой смены должен быть свой архив. Начальник смены А
видит обращения смены А и не видит смену Б — иначе четыре
начальника смотрят в одну кучу и не понимают, что из этого их.

Что добавляется:
    users.brigade   — А / Б / В / Г (у кого есть смена)
    cases.brigade   — чья смена завела обращение
    cases.shift     — День / Ночь

Бригада пользователей проставляется по логину, который задал
create_pilot_users.py:
    a-massa-1, master-a  -> А
    b-kiln-2,  master-b  -> Б
    v-pack-1,  master-v  -> В
    g-massa-2, master-g  -> Г

У кого логин другой (админ, директор, механики) бригада остаётся
пустой — они не привязаны к смене и видят всё.

Обращениям, созданным ДО этой миграции, бригада проставляется по
графику: считаем, какая смена работала в момент создания.

Запуск один раз: python migrate_brigades.py
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))


import sqlite3
from datetime import datetime

from backend.config import DB_NAME
from backend.services.shift_schedule_service import get_shift_at


BRIGADE_BY_CODE = {"a": "А", "b": "Б", "v": "В", "g": "Г"}


def brigade_from_username(username: str):
    """a-massa-1 -> А, master-b -> Б"""

    if not username:
        return None

    name = username.strip().lower()

    if name.startswith("master-"):
        return BRIGADE_BY_CODE.get(name.split("-", 1)[1][:1])

    parts = name.split("-")

    if len(parts) >= 2 and parts[0] in BRIGADE_BY_CODE:
        return BRIGADE_BY_CODE[parts[0]]

    return None


def migrate():

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # -----------------------------------------
    # Колонки
    # -----------------------------------------

    user_columns = {row[1] for row in cursor.execute("PRAGMA table_info(users)").fetchall()}

    if "brigade" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN brigade TEXT")
        print("users.brigade добавлена")

    case_columns = {row[1] for row in cursor.execute("PRAGMA table_info(cases)").fetchall()}

    if "brigade" not in case_columns:
        cursor.execute("ALTER TABLE cases ADD COLUMN brigade TEXT")
        print("cases.brigade добавлена")

    if "shift" not in case_columns:
        cursor.execute("ALTER TABLE cases ADD COLUMN shift TEXT")
        print("cases.shift добавлена")

    # Кого звать по этому обращению: mechanical / electrical.
    # Определяет ИИ по описанию неисправности, а не по станку —
    # у станка дисциплина часто "both", и тогда обращение видят
    # и механик, и электрик сразу.
    if "required_discipline" not in case_columns:
        cursor.execute("ALTER TABLE cases ADD COLUMN required_discipline TEXT")
        print("cases.required_discipline добавлена")

    # -----------------------------------------
    # Бригады пользователей
    # -----------------------------------------

    updated = 0
    without = []

    for row in cursor.execute("SELECT id, username, role FROM users").fetchall():

        brigade = brigade_from_username(row["username"])

        if brigade:
            cursor.execute("UPDATE users SET brigade = ? WHERE id = ?", (brigade, row["id"]))
            updated += 1
        else:
            without.append(f"{row['username']} ({row['role']})")

    print(f"\nБригада проставлена: {updated} пользователей")

    if without:
        print(f"Без бригады ({len(without)}) — видят все смены:")
        for name in without:
            print(f"  {name}")

    # -----------------------------------------
    # Бригады старых обращений — по графику
    # -----------------------------------------

    rows = cursor.execute(
        "SELECT id, created_at FROM cases WHERE brigade IS NULL"
    ).fetchall()

    filled = 0

    for row in rows:

        try:
            moment = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            continue

        info = get_shift_at(moment)

        cursor.execute(
            "UPDATE cases SET brigade = ?, shift = ? WHERE id = ?",
            (info["brigade"], info["shift"], row["id"])
        )

        filled += 1

    print(f"\nСтарых обращений размечено по графику: {filled}")

    conn.commit()
    conn.close()

    print("\nГотово.")


if __name__ == "__main__":
    migrate()
