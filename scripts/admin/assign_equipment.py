"""
Назначить (или переназначить) станки существующему рабочему,
без пересоздания пользователя.

Запуск: python assign_equipment.py
Разместить в корне проекта.
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))


import sqlite3

from backend.config import DB_NAME
from backend.services.auth_service import assign_equipment
from backend.services.equipment_service import init_equipment, get_all_equipment


def find_user_by_username(username: str):

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, username, full_name, role FROM users WHERE username = ?",
        (username,)
    )

    row = cursor.fetchone()
    conn.close()

    return dict(row) if row else None


def main():

    init_equipment()

    username = input("Логин рабочего: ").strip()

    user = find_user_by_username(username)

    if not user:
        print(f"Пользователь '{username}' не найден.")
        return

    if user["role"] != "worker":
        print(f"У пользователя '{username}' роль '{user['role']}', а не worker — станки назначаются только рабочим.")
        return

    equipment = get_all_equipment()

    print("\nДоступное оборудование:")

    for item in equipment:
        print(f"  {item['id']}: {item['name']} ({item['type']}, {item['location']})")

    raw_ids = input(
        "\nВведите ID станков через запятую (полностью заменит текущий список, "
        "пустая строка = снять все назначения): "
    ).strip()

    ids = [
        int(piece.strip())
        for piece in raw_ids.split(",")
        if piece.strip()
    ] if raw_ids else []

    assign_equipment(user["id"], ids)

    print(f"\nГотово. Рабочему '{username}' назначены станки: {ids}")


if __name__ == "__main__":
    main()
