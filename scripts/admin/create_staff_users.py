"""
Учётные записи для всех, кроме сменного персонала.

Операторов и начальников смен создал create_pilot_users.py — они
привязаны к бригадам. Здесь остальные: руководство, ремонтники,
технологи. К смене они не привязаны и видят обращения всех смен.

Логины осмысленные, пароли читаемые и пригодные для того, чтобы
продиктовать по телефону.

Старые технические учётки (q, w, a, s, z и подобные односимвольные)
скрипт находит и предлагает удалить — они мешают: в журнале
действий вместо фамилии видно "az", и через месяц никто не вспомнит,
кто это был.

Запуск:
    python create_staff_users.py                — показать план
    python create_staff_users.py --create        — создать
    python create_staff_users.py --create --remove-old
                                                 — создать и убрать старые
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))


import sys
import secrets
import sqlite3

from backend.config import DB_NAME
from backend.services.auth_service import (
    init_auth_tables,
    create_user,
    get_user_by_username
)


# (логин, роль, должность, сколько таких)
STAFF = [

    # -----------------------------------------
    # Руководство
    # -----------------------------------------
    ("director",      "director",          "Директор", 1),
    ("deputy",        "chief_engineer",    "Заместитель директора", 1),
    ("engineer",      "engineer",          "Инженер", 1),

    # -----------------------------------------
    # Механическая служба
    # -----------------------------------------
    ("chief-mech",    "chief_mechanic",    "Главный механик", 1),
    ("mech",          "mechanic",          "Слесарь", 4),

    # -----------------------------------------
    # Электрическая служба
    # -----------------------------------------
    ("chief-elec",    "chief_electrician", "Главный электрик", 1),
    ("elec",          "electrician",       "Электрик", 4),

    # -----------------------------------------
    # Технология и лаборатория
    # -----------------------------------------
    ("technolog",     "technologist",      "Технолог", 1),
    ("lab",           "lab_technician",    "Лаборант", 2),

    # -----------------------------------------
    # Аналитика
    # -----------------------------------------
    ("analyst",       "analyst",           "Аналитик", 1),
]


PASSWORD_WORD = {
    "director": "Director",
    "deputy": "Deputy",
    "engineer": "Engineer",
    "chief-mech": "ChiefMech",
    "mech": "Mech",
    "chief-elec": "ChiefElec",
    "elec": "Elec",
    "technolog": "Tehnolog",
    "lab": "Lab",
    "analyst": "Analyst",
}


def connect():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def make_password(base, number=None):
    """AcaiDirector47, AcaiMech2-71 — читается и диктуется."""

    word = PASSWORD_WORD.get(base, "User")
    tail = secrets.randbelow(90) + 10

    if number:
        return f"Acai{word}{number}{tail}"

    return f"Acai{word}{tail}"


def build_plan():

    plan = []

    for base, role, title, count in STAFF:

        if count == 1:
            plan.append({
                "username": base,
                "role": role,
                "full_name": title,
                "password": make_password(base)
            })
            continue

        for number in range(1, count + 1):
            plan.append({
                "username": f"{base}-{number}",
                "role": role,
                "full_name": f"{title} №{number}",
                "password": make_password(base, number)
            })

    return plan


def find_junk_users():
    """
    Старые технические учётки: короткий логин и не из пилотного
    набора. Именно они портят журнал действий.
    """

    conn = connect()

    rows = conn.execute(
        """
        SELECT id, username, full_name, role
        FROM users
        WHERE COALESCE(hidden, 0) = 0
        ORDER BY id
        """
    ).fetchall()

    conn.close()

    junk = []

    for row in rows:

        name = row["username"]

        # Пилотные логины трогать нельзя
        if name.startswith(("a-", "b-", "v-", "g-", "master-")):
            continue

        # Логины, которые мы сейчас создаём
        if name in {item["username"] for item in build_plan()}:
            continue

        # Админов не трогаем никогда — иначе останетесь без доступа
        if row["role"] == "admin":
            continue

        if len(name) <= 4:
            junk.append(dict(row))

    return junk


def main():

    create_mode = "--create" in sys.argv
    remove_old = "--remove-old" in sys.argv

    init_auth_tables()

    plan = build_plan()

    existing = [item for item in plan if get_user_by_username(item["username"])]

    print(f"\nУЧЁТНЫЕ ЗАПИСИ ПЕРСОНАЛА: {len(plan)}")
    print("=" * 70)
    print(f"{'логин':<18}{'роль':<20}должность")
    print("-" * 70)

    for item in plan:
        mark = "  уже есть" if item in existing else ""
        print(f"{item['username']:<18}{item['role']:<20}{item['full_name']}{mark}")

    junk = find_junk_users()

    if junk:
        print(f"\n\nСТАРЫЕ ТЕХНИЧЕСКИЕ УЧЁТКИ: {len(junk)}")
        print("=" * 70)
        for item in junk:
            print(f"  {item['username']:<10}{item['role']:<20}{item['full_name'] or ''}")
        print("\n  Из-за них в журнале действий вместо фамилии видно 'az'.")
        print("  Удалить вместе с созданием: --remove-old")
        print("  История обращений при удалении НЕ пропадёт: имена в")
        print("  переписке и журнале хранятся текстом, не ссылкой.")

    if not create_mode:
        print("\nЭто ПРОСМОТР — ничего не создано.")
        print("Создать: python create_staff_users.py --create\n")
        return

    # -----------------------------------------
    # Создание
    # -----------------------------------------

    print("\n\nСОЗДАНИЕ")
    print("=" * 70)

    created = []

    for item in plan:

        if get_user_by_username(item["username"]):
            print(f"  пропуск (уже есть): {item['username']}")
            continue

        try:
            create_user(
                item["username"],
                item["password"],
                item["full_name"],
                item["role"]
            )
            created.append(item)
            print(f"  создан: {item['username']}")

        except Exception as error:
            print(f"  ОШИБКА {item['username']}: {error}")

    # -----------------------------------------
    # Удаление старых
    # -----------------------------------------

    if remove_old and junk:

        conn = connect()
        cursor = conn.cursor()

        for item in junk:
            cursor.execute("DELETE FROM sessions WHERE user_id = ?", (item["id"],))
            cursor.execute("DELETE FROM worker_equipment WHERE user_id = ?", (item["id"],))
            cursor.execute("DELETE FROM users WHERE id = ?", (item["id"],))
            print(f"  удалён старый: {item['username']}")

        conn.commit()
        conn.close()

    # -----------------------------------------
    # Файл для раздачи
    # -----------------------------------------

    if not created:
        print("\nНовых учёток не появилось.")
        return

    lines = [
        "ACAI — доступ для персонала",
        "",
        "Адрес: http://192.168.0.47:8000",
        "",
        "РАЗДАЙТЕ И УДАЛИТЕ ЭТОТ ФАЙЛ.",
        "Пароль нигде больше не хранится. Забыл — сбрасывается:",
        "    python manage_admin.py reset ЛОГИН",
        "",
        "=" * 66,
        f"{'логин':<18}{'пароль':<20}должность",
        "=" * 66,
    ]

    for item in created:
        lines.append(f"{item['username']:<18}{item['password']:<20}{item['full_name']}")

    lines += [
        "",
        "Эти сотрудники не привязаны к смене и видят обращения",
        "всех бригад. Механик видит только механические задачи,",
        "электрик — только электрические: распределяет ИИ по сути",
        "неисправности.",
        "",
    ]

    text = "\n".join(lines)

    with open("ДОСТУП_ПЕРСОНАЛ.txt", "w", encoding="utf-8") as f:
        f.write(text)

    print("\n" + text)
    print(f"Создано: {len(created)}")
    print("Файл: ДОСТУП_ПЕРСОНАЛ.txt")
    print("После раздачи: rm ДОСТУП_ПЕРСОНАЛ.txt\n")


if __name__ == "__main__":
    main()
