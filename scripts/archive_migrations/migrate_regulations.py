"""
Регламенты: что должно быть, а не что случилось.

До сих пор система хранила события — обращения, простои, замеры.
Регламент это норма, относительно которой событие считается
отклонением. Без неё "68 °C" просто число, а с ней — "в допуске
55-70, всё в порядке".

ЧЕТЫРЕ РЕШЕНИЯ, КОТОРЫЕ ОПРЕДЕЛЯЮТ ВСЁ ОСТАЛЬНОЕ

1. Замер намертво привязан к версии регламента, действовавшей в
   момент замера, и хранит её границы копией.

   15 июня: факт 68 °C, регламент v1.2, допуск 55-70 -> OK.
   1 июля технолог сузил до 50-65 (v1.3).
   Замер от 15 июня ОСТАЁТСЯ "OK по версии 1.2".

   Если пересчитывать историю по новой норме, вчерашняя нормальная
   работа задним числом станет браком, а отчёты перестанут
   сходиться сами с собой. Поэтому границы копируются в строку
   замера, а не читаются по ссылке.

2. Параметр не обязан иметь минимум-максимум-оптимум.
   Бывает целевое значение с допуском (1,5 ±0,5), бывает только
   верхняя граница (влажность не выше 8%), бывает текстовое
   правило ("без сколов и трещин"), бывает да/нет. Тип параметра
   задаётся явно, лишние поля остаются пустыми.

3. У нормы есть источник: утверждённый регламент, паспорт
   изготовителя, ГОСТ или опыт технолога. Разница существенная:
   значение "по опыту" технолог меняет сам, а число из паспорта
   станка менять без основания нельзя.

4. PLC-теги заведены как пустое поле. Заполнять их выдуманными
   именами до получения карты от поставщика бессмысленно — потом
   всё равно переписывать.

Запуск один раз: python migrate_regulations.py
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))


import sqlite3

from backend.config import DB_NAME


SCHEMA = """

-- =========================================================
-- РЕГЛАМЕНТ ПРОДУКТА
-- =========================================================

CREATE TABLE IF NOT EXISTS regulations (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    product_type TEXT NOT NULL,

    name TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,

    -- draft    — черновик, по нему не работают
    -- active   — действует сейчас
    -- archived — заменён новой версией, сохранён навсегда
    status TEXT NOT NULL DEFAULT 'draft',

    photo_path TEXT,
    description TEXT,

    replaced_by INTEGER,

    created_by TEXT,
    created_at TEXT NOT NULL,
    activated_at TEXT,
    activated_by TEXT,

    UNIQUE (product_type, version)
);


-- =========================================================
-- ЭТАПЫ
-- =========================================================

CREATE TABLE IF NOT EXISTS regulation_stages (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    regulation_id INTEGER NOT NULL,

    -- Совпадает со stage у оборудования: mass, forming,
    -- drying, kiln, packaging
    stage_key TEXT,
    name TEXT NOT NULL,

    description TEXT,
    sort_order INTEGER DEFAULT 100,

    FOREIGN KEY (regulation_id) REFERENCES regulations(id)
);


-- =========================================================
-- ПАРАМЕТРЫ
-- =========================================================
-- param_type определяет, какие поля осмысленны:
--
--   range    зазор 1,0-2,5 мм        min_value, max_value, optimal_value
--   target   1,5 мм ±0,5             target_value, tolerance_abs
--   max      влажность не выше 8%    max_value
--   min      прочность не ниже 125   min_value
--   text     "без сколов и трещин"   text_rule
--   boolean  наличие маркировки      ожидается да/нет
--
-- Заставлять технолога придумывать минимум для параметра
-- "внешний вид" — верный способ получить мусор в базе.

CREATE TABLE IF NOT EXISTS regulation_parameters (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    regulation_id INTEGER NOT NULL,
    stage_id INTEGER,

    -- К какому станку относится. NULL — параметр этапа целиком.
    -- Именно эта связь даст цифровой паспорт станка: нажали на
    -- Optima 800H — увидели её параметры для текущего продукта.
    equipment_id INTEGER,

    name TEXT NOT NULL,
    unit TEXT,

    param_type TEXT NOT NULL DEFAULT 'range',

    min_value REAL,
    max_value REAL,
    optimal_value REAL,
    target_value REAL,

    -- Допуск от целевого: ±0,5 мм или ±5%
    tolerance_abs REAL,
    tolerance_percent REAL,

    -- Для param_type = text / boolean
    text_rule TEXT,

    -- =====================================================
    -- ОТКУДА НОРМА
    -- =====================================================
    -- regulation   утверждённый технологический регламент
    -- manufacturer паспорт изготовителя оборудования
    -- gost         ГОСТ или другой стандарт
    -- experience   опыт технолога, не подтверждён документом
    --
    -- Разница не формальная: значение "по опыту" технолог меняет
    -- сам, а число из паспорта станка без основания менять нельзя.
    norm_source TEXT DEFAULT 'regulation',
    norm_reference TEXT,

    -- =====================================================
    -- ОТКУДА ФАКТ
    -- =====================================================
    -- plc / scada / sensor / lab / manual / none
    --
    -- none означает "пока ничем не меряем" — это честное
    -- состояние, а не пропуск. Такие параметры сразу видно
    -- в отчёте "что мы не контролируем".
    fact_source TEXT DEFAULT 'manual',

    -- Имя тега в PLC. Пустое до получения карты от поставщика:
    -- выдуманные имена придётся переписывать целиком.
    plc_tag TEXT,

    is_critical INTEGER DEFAULT 0,

    -- shift / hour / continuous / daily / batch
    check_interval TEXT,

    note TEXT,
    sort_order INTEGER DEFAULT 100,

    FOREIGN KEY (regulation_id) REFERENCES regulations(id),
    FOREIGN KEY (stage_id) REFERENCES regulation_stages(id)
);


-- =========================================================
-- ИСТОРИЯ ИЗМЕНЕНИЙ
-- =========================================================
-- Причина обязательна. Технолог меняет норму сам, без чужого
-- утверждения — но объясняет, зачем. Через полгода при разборе
-- брака это единственный способ понять, что имелось в виду.

CREATE TABLE IF NOT EXISTS regulation_changes (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    regulation_id INTEGER NOT NULL,

    version_from INTEGER,
    version_to INTEGER,

    reason TEXT NOT NULL,
    changes TEXT,

    changed_by TEXT NOT NULL,
    changed_role TEXT,
    created_at TEXT NOT NULL,

    FOREIGN KEY (regulation_id) REFERENCES regulations(id)
);


-- =========================================================
-- ОЗНАКОМЛЕНИЕ
-- =========================================================

CREATE TABLE IF NOT EXISTS regulation_ack (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    regulation_id INTEGER NOT NULL,
    version INTEGER NOT NULL,

    user_id INTEGER,
    username TEXT,
    full_name TEXT,
    role TEXT,

    acknowledged_at TEXT NOT NULL,

    UNIQUE (regulation_id, version, user_id)
);


-- =========================================================
-- ЗАМЕРЫ
-- =========================================================
-- Границы копируются в строку замера, а не читаются по ссылке.
-- Регламент изменится — этот замер останется правильным по своей
-- версии. Иначе вчерашняя нормальная работа задним числом станет
-- браком.

CREATE TABLE IF NOT EXISTS measurements (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    parameter_id INTEGER NOT NULL,
    equipment_id INTEGER,

    -- Версия, действовавшая В МОМЕНТ ЗАМЕРА
    regulation_id INTEGER,
    regulation_version INTEGER,

    -- Копия нормы на тот момент
    norm_min REAL,
    norm_max REAL,
    norm_optimal REAL,
    norm_target REAL,
    norm_text TEXT,
    param_type TEXT,

    value REAL,
    text_value TEXT,

    -- ok / low / high / critical / unknown
    -- Считается при записи по нормам ТОГО момента и больше не
    -- пересчитывается никогда.
    status TEXT,

    source TEXT DEFAULT 'manual',

    measured_by TEXT,
    measured_at TEXT NOT NULL,

    -- Партия, вагонетка, смена — к чему относится замер
    batch_ref TEXT,

    note TEXT,

    FOREIGN KEY (parameter_id) REFERENCES regulation_parameters(id)
);


-- =========================================================
-- ПЛАНОВОЕ ОБСЛУЖИВАНИЕ
-- =========================================================

CREATE TABLE IF NOT EXISTS maintenance_plans (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    equipment_id INTEGER NOT NULL,

    name TEXT NOT NULL,
    description TEXT,

    -- Периодичность в днях: 30 — раз в месяц (свиллерезы),
    -- 7 — еженедельно, 180 — раз в полгода
    interval_days INTEGER NOT NULL,

    responsible_role TEXT,
    procedure_id INTEGER,

    last_done_at TEXT,
    next_due_at TEXT,

    is_active INTEGER DEFAULT 1,

    created_by TEXT,
    created_at TEXT NOT NULL,

    FOREIGN KEY (equipment_id) REFERENCES equipment(id)
);


CREATE TABLE IF NOT EXISTS maintenance_log (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    plan_id INTEGER NOT NULL,
    equipment_id INTEGER,

    done_at TEXT NOT NULL,
    done_by TEXT,

    note TEXT,

    -- К какому сроку было запланировано — чтобы видеть опоздания
    was_due_at TEXT,

    FOREIGN KEY (plan_id) REFERENCES maintenance_plans(id)
);


-- =========================================================
-- ДОКУМЕНТЫ ОБОРУДОВАНИЯ
-- =========================================================

CREATE TABLE IF NOT EXISTS equipment_documents (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    equipment_id INTEGER NOT NULL,

    title TEXT NOT NULL,
    file_path TEXT,

    -- manual / scheme / passport / instruction / certificate
    doc_type TEXT DEFAULT 'manual',

    page_from INTEGER,
    note TEXT,

    added_by TEXT,
    added_at TEXT NOT NULL,

    FOREIGN KEY (equipment_id) REFERENCES equipment(id)
);
"""


INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_reg_product ON regulations(product_type, status)",
    "CREATE INDEX IF NOT EXISTS idx_reg_param ON regulation_parameters(regulation_id, stage_id)",
    "CREATE INDEX IF NOT EXISTS idx_reg_param_eq ON regulation_parameters(equipment_id)",
    "CREATE INDEX IF NOT EXISTS idx_meas_param ON measurements(parameter_id, measured_at)",
    "CREATE INDEX IF NOT EXISTS idx_meas_eq ON measurements(equipment_id, measured_at)",
    "CREATE INDEX IF NOT EXISTS idx_meas_ver ON measurements(regulation_id, regulation_version)",
    "CREATE INDEX IF NOT EXISTS idx_maint_due ON maintenance_plans(next_due_at, is_active)",
    "CREATE INDEX IF NOT EXISTS idx_docs_eq ON equipment_documents(equipment_id)",
    "CREATE INDEX IF NOT EXISTS idx_param_group ON regulation_parameters(regulation_id, param_group)",
]


def migrate():

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.executescript(SCHEMA)

    # Для тех, у кого таблицы созданы предыдущей версией скрипта
    existing = {
        row[1]
        for row in cursor.execute("PRAGMA table_info(measurements)").fetchall()
    }

    for column, definition in [
        ("regulation_id", "INTEGER"),
        ("regulation_version", "INTEGER"),
        ("norm_min", "REAL"),
        ("norm_max", "REAL"),
        ("norm_optimal", "REAL"),
        ("norm_target", "REAL"),
        ("norm_text", "TEXT"),
        ("param_type", "TEXT"),
        ("batch_ref", "TEXT"),
    ]:
        if column not in existing:
            cursor.execute(f"ALTER TABLE measurements ADD COLUMN {column} {definition}")
            print(f"  measurements.{column} добавлена")

    params_existing = {
        row[1]
        for row in cursor.execute("PRAGMA table_info(regulation_parameters)").fetchall()
    }

    for column, definition in [
        ("param_type", "TEXT DEFAULT 'range'"),

        # Требование и допуск — как они записаны в бумажном
        # регламенте. Это официальный документ, и сводить его
        # строку к min/max нельзя: при разборе с директором нужно
        # показать то, что написано в регламенте, а не то, во что
        # мы это пересчитали.
        ("requirement_text", "TEXT"),
        ("requirement_value", "REAL"),
        ("tolerance_text", "TEXT"),

        # process — технологический параметр
        # mix     — компонент шихты (ГЦ, глина, песок)
        ("param_group", "TEXT DEFAULT 'process'"),

        # Для шихты: gc / clay / sand — чтобы считать соотношение
        ("component_key", "TEXT"),
        ("target_value", "REAL"),
        ("tolerance_abs", "REAL"),
        ("tolerance_percent", "REAL"),
        ("text_rule", "TEXT"),
        ("norm_source", "TEXT DEFAULT 'regulation'"),
        ("norm_reference", "TEXT"),
        ("fact_source", "TEXT DEFAULT 'manual'"),
        ("plc_tag", "TEXT"),
    ]:
        if column not in params_existing:
            cursor.execute(f"ALTER TABLE regulation_parameters ADD COLUMN {column} {definition}")
            print(f"  regulation_parameters.{column} добавлена")

    # Задел под будущее 3D: связь станка с объектом сцены.
    # Сейчас пустая — 3D не делаем, но добавить колонку потом
    # к таблице с историей дороже, чем сейчас.
    equipment_columns = {
        row[1]
        for row in cursor.execute("PRAGMA table_info(equipment)").fetchall()
    }

    if "object_3d_id" not in equipment_columns:
        cursor.execute("ALTER TABLE equipment ADD COLUMN object_3d_id TEXT")
        print("  equipment.object_3d_id добавлена (задел под 3D)")

    # Снимок требования и допуска в замере — рядом с границами
    measure_columns = {
        row[1]
        for row in cursor.execute("PRAGMA table_info(measurements)").fetchall()
    }

    for column, definition in [
        ("norm_requirement", "TEXT"),
        ("norm_tolerance", "TEXT"),
        ("norm_requirement_value", "REAL"),
    ]:
        if column not in measure_columns:
            cursor.execute(f"ALTER TABLE measurements ADD COLUMN {column} {definition}")
            print(f"  measurements.{column} добавлена")

    for statement in INDEXES:
        cursor.execute(statement)

    conn.commit()

    tables = [
        "regulations", "regulation_stages", "regulation_parameters",
        "regulation_changes", "regulation_ack", "measurements",
        "maintenance_plans", "maintenance_log", "equipment_documents"
    ]

    print("\nТАБЛИЦЫ РЕГЛАМЕНТОВ")
    print("=" * 52)

    for table in tables:
        count = cursor.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:<26} записей: {count}")

    conn.close()

    print("\nЗамер хранит копию нормы на момент замера — история не")
    print("пересчитывается при смене регламента.\n")


if __name__ == "__main__":
    migrate()
