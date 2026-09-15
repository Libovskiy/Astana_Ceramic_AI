"""
Миграция: добавляет поле discipline в таблицу equipment —
"mechanical" / "electrical" / "both". Нужно для разделения
станков на страницах "Механика"/"Электрика" (гл. механик/слесарь
видят только механическую часть, гл. электрик/электрик — только
электрическую).

Классификация составлена по инженерной логике (не идеальна,
пользователь подтвердил "пойдёт для старта, поправим потом
в базе") — там, где станок явно программируемый/с электронным
управлением, стоит "both".

Запуск один раз: python migrate_equipment_discipline.py
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))


import sqlite3

from backend.config import DB_NAME


MECHANICAL = [
    "Дробилка DTE 117",
    "Дезинтегратор PL 601",
    "Камневыделительные вальцы PL 194",
    "Вальцы тонкого помола СМК 102",
    "Вальцы УСМ 40",
    "Смеситель лопастной СМК 126",
    "Бункер хранения шихты №1",
    "Бункер хранения шихты №2",
    "Бункер хранения шихты №3",
    "Вальцы супертонкого помола OPTIMA 800",
    "Экструдер шнековый MAGNA 575",
    "Конвейерный ленточный стол резчика мерного бруса",
    "Стол вертикального резчика бруса",
    "Откидной ленточный стол",
    "Столик скоростной ленты",
    "Резчик с толкателем (многострунный)",
    "Стол приёма обрезков",
    "Туннельная сушилка LLEVANT",
    "Вентилятор нагнетания QB-54",
    "Вентилятор нагнетания QB-44",
    "Вытяжные вентиляторы GAT-125 (2 шт)",
    "Вентиляторы рециркуляции зона 3 GAT-63 (16 шт)",
    "Вентиляторы рециркуляции зоны 1-2 GAT-80 (32 шт)",
    "Генератор тепла 1500 CSD + теплообменник GB/1500",
    "Туннельная печь PRESTHERMIC",
    "Центробежный вентилятор QB-44 (дымосос печи)",
    "Центробежный вентилятор QB-40 (контравек)",
    "Осевой вентилятор GAT-80 (герметизация ямы)",
    "Центробежный вентилятор QB-54 (охлаждение печи)",
    "Оборудование PROMATIC для обжига углём",
    "Цепной стол группировки и опрокидывания",
    "Тросо-волочильный механизм перемещения вагонеток",
    "Транспортер для поддонов (5 рядов)",
    "Транспортер формования пакетов",
    "Транспортер упакованных пакетов",
]

ELECTRICAL = [
    "Датчики заполнения бункеров массаподготовки",
    "Система контроля MICROSEC (датчики давления/температуры/влажности)",
    "Система контроля печи MICROBER-1",
    "Электрооборудование SCHNEIDER MODICON M340",
]

BOTH = [
    "Ленточный стол программирования рядов",
    "Ленточный стол программирования",
    "Программируемый ленточный стол с пластиной-гребёнкой",
    "Робот-садчик сырца на вагонетки",
    "Регистры моторизованные сушилки (13 шт)",
    "Система быстрого охлаждения GERIM 200/2/14",
    "Система нагнетания преднагрева INYECTAIR (8+8)",
    "Робот-разгрузчик FANUC M-410iB/700 (с печных вагонеток)",
    "Робот-укладчик FANUC M-410iB/700 (на поддон)",
    "Упаковочная машина",
]


def migrate():

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    existing_columns = {
        row[1]
        for row in cursor.execute("PRAGMA table_info(equipment)").fetchall()
    }

    if "discipline" not in existing_columns:

        cursor.execute("ALTER TABLE equipment ADD COLUMN discipline TEXT")

        print("Добавлена колонка discipline в equipment.")

    else:

        print("Колонка discipline уже существует — продолжаю заполнение значений.")

    updated_count = 0

    for name in MECHANICAL:

        cursor.execute(
            "UPDATE equipment SET discipline = 'mechanical' WHERE name = ?",
            (name,)
        )

        updated_count += cursor.rowcount

    for name in ELECTRICAL:

        cursor.execute(
            "UPDATE equipment SET discipline = 'electrical' WHERE name = ?",
            (name,)
        )

        updated_count += cursor.rowcount

    for name in BOTH:

        cursor.execute(
            "UPDATE equipment SET discipline = 'both' WHERE name = ?",
            (name,)
        )

        updated_count += cursor.rowcount

    conn.commit()

    cursor.execute("SELECT COUNT(*) FROM equipment WHERE discipline IS NULL")
    unmatched = cursor.fetchone()[0]

    conn.close()

    print(f"Проставлено discipline у {updated_count} станков.")

    if unmatched:
        print(
            f"⚠️  {unmatched} станков остались БЕЗ discipline (название не "
            f"совпало ни с одним в списке — проверьте вручную, скорее всего "
            f"это 'Упаковочная линия' или новые станки, добавленные позже)."
        )


if __name__ == "__main__":
    migrate()
