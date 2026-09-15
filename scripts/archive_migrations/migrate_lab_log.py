"""
Миграция: лабораторный журнал по образцу вашего отчёта в Битриксе.

Существующая таблица mix_log остаётся — она про разовый расчёт
"сколько глины и песка на замес". Здесь другое: полная суточная
карта от шихты до обожжённого кирпича, та самая, которую лаборант
ведёт в "ЛАБОРАТОРИЯ ОТЧЕТ 2026.xlsx".

Зачем в базе, а не в Excel: в таблице связь "состав 85/15 при
влажности 14,0 дал марку М125" видна только если пролистать
полгода строк глазами. В базе это запрос, а ИИ может ответить
"при таком составе марка выходила М125 в 12 случаях из 14".

Колонки повторяют ваш отчёт, включая парные значения по каналам
сушилки — там где в Excel две цифры в одной ячейке, здесь два
поля.

Запуск один раз: python migrate_lab_log.py
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))


import sqlite3

from backend.config import DB_NAME


SCHEMA = """
CREATE TABLE IF NOT EXISTS lab_log (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    log_date TEXT NOT NULL,
    shift TEXT,
    brigade TEXT,

    -- =========================================
    -- ВИД ПРОДУКЦИИ (в производстве / сушилке / печи)
    -- =========================================
    product_production TEXT,
    product_dryer TEXT,
    product_kiln TEXT,

    -- Производительность тепловых процессов: вагонеток в сутки
    -- и температура обжига
    wagons_per_day REAL,
    kiln_temperature REAL,

    -- =========================================
    -- ФОРМОВАНИЕ
    -- =========================================
    -- Состав шихты глина/песок в процентах: 85/15
    clay_percent REAL,
    sand_percent REAL,

    sand_gate TEXT,              -- шибер песок, см
    feed_clay_hz REAL,           -- шихта глина, Гц
    feed_sand_hz REAL,           -- шихта песок, Гц

    -- Влажность шихты по точкам замера
    moisture_optima REAL,
    moisture_smk126 REAL,

    raw_geometry TEXT,           -- геометрия сырца, мм
    raw_weight REAL,             -- вес сырца, кг

    -- Зазоры на вальцах, мм (в отчёте диапазоны — храним текстом)
    gap_smk102 TEXT,
    gap_usm40 TEXT,
    gap_optima TEXT,

    -- =========================================
    -- ТОПЛИВО (влажность угля, %)
    -- =========================================
    coal_moisture_delivery REAL,   -- завоз
    coal_moisture_mill REAL,       -- мельница
    coal_moisture_right REAL,      -- отсев, запас правый
    coal_moisture_left REAL,       -- отсев, запас левый

    -- =========================================
    -- СУШИЛКА
    -- =========================================
    dried_weight_1 REAL,           -- вес высушенных, 1 канал
    dried_weight_2 REAL,           -- вес высушенных, 2 канал
    dried_moisture_1 REAL,         -- остаточная влажность, 1 канал
    dried_moisture_2 REAL,         -- остаточная влажность, 2 канал

    -- =========================================
    -- ОБЖИГ И ГОТОВАЯ ПРОДУКЦИЯ
    -- =========================================
    fired_weight REAL,             -- вес готовых изделий, кг
    fired_geometry TEXT,           -- геометрия готовой продукции, мм
    voidness REAL,                 -- пустотность, %
    water_absorption REAL,         -- водопоглощение, %

    -- Марка по прочности: Д-125 / Н-100 и дата протокола
    strength_d TEXT,
    strength_n TEXT,
    strength_value REAL,           -- число для расчётов: 125, 100, 150

    protocols TEXT,                -- номера протоколов
    note TEXT,

    -- Отметка "отчёт закончен". Запись живёт несколько суток:
    -- утром шихта, через день сушка, ещё через двое обжиг и марка.
    -- Пока отметки нет — строка подсвечена как незавершённая, чтобы
    -- лаборант не забыл вернуться и дописать.
    -- Править завершённый отчёт можно: протокол приходит позже,
    -- цифру уточняют. Запрещать это значит заставить вести
    -- параллельно бумажку.
    is_complete INTEGER DEFAULT 0,
    completed_at TEXT,
    completed_by TEXT,

    created_by TEXT,
    created_at TEXT NOT NULL
);
"""

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_lab_date ON lab_log(log_date)",
    "CREATE INDEX IF NOT EXISTS idx_lab_mix ON lab_log(clay_percent, sand_percent)",
    "CREATE INDEX IF NOT EXISTS idx_lab_strength ON lab_log(strength_value)",
]



CHAT_SCHEMA = """
CREATE TABLE IF NOT EXISTS lab_chat (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    question TEXT NOT NULL,
    answer TEXT,

    -- На каких цифрах journal был построен ответ. Храним, потому
    -- что через месяц статистика изменится, а ответ останется —
    -- и надо понимать, из чего он тогда исходил.
    context TEXT,

    author TEXT,
    author_role TEXT,
    created_at TEXT NOT NULL
);
"""


def migrate_chat(cursor):

    cursor.execute(CHAT_SCHEMA)

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_lab_chat_date ON lab_chat(created_at)"
    )



PRODUCT_SCHEMA = """
CREATE TABLE IF NOT EXISTS product_types (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    name TEXT NOT NULL UNIQUE,

    -- Порядок в списке: полнотелый, пустотелый, блок — как на заводе
    sort_order INTEGER DEFAULT 100,

    -- Убранный вид не удаляем: к нему привязаны записи журнала за
    -- прошлые месяцы. Просто перестаём предлагать в новых.
    is_active INTEGER DEFAULT 1,

    created_by TEXT,
    created_at TEXT
);
"""

# Три основных вида. Остальные завод добавит сам через интерфейс —
# зашивать их в код нельзя: номенклатура меняется, а править исходники
# ради нового кирпича никто не будет.
BASE_PRODUCTS = [
    ("Полнотелый", 10),
    ("Пустотелый", 20),
    ("Блок", 30),
]


def migrate_products(cursor):

    cursor.execute(PRODUCT_SCHEMA)

    from datetime import datetime

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for name, order in BASE_PRODUCTS:
        cursor.execute(
            """
            INSERT OR IGNORE INTO product_types (name, sort_order, created_by, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (name, order, "система", now)
        )


def migrate():

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(SCHEMA)

    # Таблица могла быть создана раньше, без полей завершения
    existing = {
        row[1]
        for row in cursor.execute("PRAGMA table_info(lab_log)").fetchall()
    }

    for column, definition in [
        ("is_complete", "INTEGER DEFAULT 0"),
        ("completed_at", "TEXT"),
        ("completed_by", "TEXT"),
    ]:
        if column not in existing:
            cursor.execute(f"ALTER TABLE lab_log ADD COLUMN {column} {definition}")
            print(f"Добавлена колонка {column}")

    for statement in INDEXES:
        cursor.execute(statement)

    migrate_chat(cursor)
    migrate_products(cursor)

    # Вид продукции в журнале: раньше это было свободное поле,
    # и "1.4 НФ полнотелый" с "1,4 НФ Полнотелый" считались бы
    # разными видами. Теперь ссылка на справочник.
    lab_columns = {
        row[1]
        for row in cursor.execute("PRAGMA table_info(lab_log)").fetchall()
    }

    if "product_type" not in lab_columns:
        cursor.execute("ALTER TABLE lab_log ADD COLUMN product_type TEXT")
        print("Добавлена колонка lab_log.product_type")

    conn.commit()

    count = cursor.execute("SELECT COUNT(*) FROM lab_log").fetchone()[0]

    conn.close()

    products = cursor.execute("SELECT COUNT(*) FROM product_types").fetchone()[0]

    print("Таблицы lab_log, lab_chat и product_types готовы.")
    print(f"Видов продукции: {products}")
    print(f"Записей: {count}")
    print()
    print("Дальше: лаборант заполняет карту за сутки в разделе")
    print("'Лаборатория', а ИИ по накопленным записям отвечает,")
    print("какой состав давал лучшую марку.")


if __name__ == "__main__":
    migrate()
