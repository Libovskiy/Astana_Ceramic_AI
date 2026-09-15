"""
Создание всех учётных записей пилота одной командой.

Структура (по вашей производственной карте):

    3 участка, на каждом по 2 оператора в смену:
        massa    — Массаподготовка и формовка (шнеки, экструдер, резка)
        kiln     — Сушка, печь и углеподготовка
        pack     — Упаковка и толкатель

    4 бригады: А, Б, В, Г — работают по графику
    shift_schedule_service (2 дня / 2 ночи / 4 выходных).

    Итого: 4 бригады x 3 участка x 2 оператора = 24 оператора
           + 4 начальника смены = 28 учётных записей.

Логины по шаблону:
    a-massa-1     оператор, бригада А, массаподготовка, первый
    b-kiln-2      оператор, бригада Б, печь, второй
    master-a      начальник смены бригады А

Имена сотрудников не задаются: люди всё равно представляются в
переписке, а вписать настоящие ФИО можно позже через
"Настройки -> Пользователи". В поле "Имя" пишется участок и бригада,
чтобы в журнале действий было понятно, кто это.

Пароли генерируются случайно и сохраняются в файл users_passwords.txt
в корне проекта. Раздайте и УДАЛИТЕ файл.

Запуск:
    python create_pilot_users.py            — показать, что будет создано
    python create_pilot_users.py --create    — создать
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
    assign_equipment,
    get_user_by_username
)
from backend.services.equipment_service import get_all_equipment


BRIGADES = ("А", "Б", "В", "Г")

BRIGADE_CODE = {"А": "a", "Б": "b", "В": "v", "Г": "g"}

# Участок -> какие этапы производства к нему относятся
ZONES = {
    "massa": {
        "title": "Массаподготовка и формовка",
        "stages": ("mass", "forming"),
        "operators": 2
    },
    "kiln": {
        "title": "Сушка, печь и углеподготовка",
        "stages": ("drying", "kiln"),
        "operators": 2
    },
    "pack": {
        "title": "Упаковка",
        "stages": ("packaging",),
        "operators": 2
    },
}


def generate_password():
    """10+ символов, заглавная, строчная, цифра — как требует
    validate_password_strength."""

    return "Acai" + secrets.token_hex(3) + str(secrets.randbelow(90) + 10)


def equipment_by_zone():

    equipment = get_all_equipment()

    result = {}

    for code, zone in ZONES.items():

        result[code] = [
            item["id"]
            for item in equipment
            if item.get("stage") in zone["stages"]
        ]

    unassigned = [
        item["name"]
        for item in equipment
        if not item.get("stage")
    ]

    return result, unassigned


def build_plan():

    plan = []

    for brigade in BRIGADES:

        code = BRIGADE_CODE[brigade]

        plan.append({
            "username": f"master-{code}",
            "full_name": f"Начальник смены, бригада {brigade}",
            "role": "shift_supervisor",
            "zone": None
        })

        for zone_code, zone in ZONES.items():

            for number in range(1, zone["operators"] + 1):

                plan.append({
                    "username": f"{code}-{zone_code}-{number}",
                    "full_name": f"Оператор {number}, {zone['title']}, бригада {brigade}",
                    "role": "worker",
                    "zone": zone_code
                })

    return plan


def main():

    create_mode = "--create" in sys.argv

    init_auth_tables()

    zones, unassigned = equipment_by_zone()

    print("\nОБОРУДОВАНИЕ ПО УЧАСТКАМ")
    print("=" * 60)

    for code, zone in ZONES.items():
        print(f"  {zone['title']:<38} {len(zones[code])} станков")

    if unassigned:
        print(f"\n  Без этапа производства ({len(unassigned)}) — никому не достанутся:")
        for name in unassigned:
            print(f"    - {name}")

    plan = build_plan()

    print(f"\nУЧЁТНЫЕ ЗАПИСИ: {len(plan)}")
    print("=" * 60)

    existing = []

    for item in plan:
        if get_user_by_username(item["username"]):
            existing.append(item["username"])

    for item in plan:
        mark = "уже есть" if item["username"] in existing else ""
        print(f"  {item['username']:<16} {item['role']:<16} {item['full_name'][:44]:<46}{mark}")

    if not create_mode:
        print("\nЭто ПРОСМОТР — ничего не создано.")
        print("Создать: python create_pilot_users.py --create")
        return

    print("\nСОЗДАНИЕ")
    print("=" * 60)

    credentials = []
    created = 0
    skipped = 0

    for item in plan:

        if item["username"] in existing:
            print(f"  пропуск (уже есть): {item['username']}")
            skipped += 1
            continue

        password = generate_password()

        try:

            user_id = create_user(
                item["username"],
                password,
                item["full_name"],
                item["role"]
            )

        except Exception as error:
            print(f"  ОШИБКА {item['username']}: {error}")
            continue

        if item["zone"]:
            assign_equipment(user_id, zones[item["zone"]])

        credentials.append((item["username"], password, item["full_name"]))

        print(f"  создан: {item['username']}")

        created += 1

    if credentials:

        with open("users_passwords.txt", "w", encoding="utf-8") as f:

            f.write("ACAI — учётные записи пилота\n")
            f.write("РАЗДАЙТЕ СОТРУДНИКАМ И УДАЛИТЕ ЭТОТ ФАЙЛ\n\n")

            for username, password, full_name in credentials:
                f.write(f"{username:<16} {password:<16} {full_name}\n")

        print(f"\n  Пароли записаны в users_passwords.txt")
        print("  Раздайте сотрудникам и удалите файл.")

    print(f"\nСоздано: {created} | Пропущено: {skipped}")


if __name__ == "__main__":
    main()
