import sqlite3
from datetime import datetime

from backend.config import DB_NAME


def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_equipment():

    conn = get_connection()
    cursor = conn.cursor()

    # =========================================
    # EQUIPMENT TABLE
    # =========================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            type TEXT,
            status TEXT NOT NULL DEFAULT 'Работает',
            health INTEGER DEFAULT 100,
            readiness INTEGER DEFAULT 100,
            location TEXT,
            parent_id INTEGER,
            level TEXT DEFAULT 'machine',
            maintenance_required INTEGER DEFAULT 0,
            last_issue TEXT,
            last_check TEXT,
            updated_at TEXT
        )
    """)

    # =========================================
    # MIGRATION FOR OLD DATABASE
    # =========================================

    columns = [
        ("readiness", "INTEGER DEFAULT 100"),
        ("parent_id", "INTEGER"),
        ("level", "TEXT DEFAULT 'machine'"),
        ("maintenance_required", "INTEGER DEFAULT 0"),
        ("last_issue", "TEXT"),
        ("updated_at", "TEXT"),
        ("stage", "TEXT"),
        ("discipline", "TEXT DEFAULT 'both'"),
        ("description", "TEXT"),
        ("photo_path", "TEXT"),
        ("inventory_number", "TEXT"),
        ("is_active", "INTEGER NOT NULL DEFAULT 1"),
    ]

    existing_columns = {
        row["name"]
        for row in cursor.execute(
            "PRAGMA table_info(equipment)"
        ).fetchall()
    }

    for column_name, column_type in columns:

        if column_name not in existing_columns:

            cursor.execute(
                f"""
                ALTER TABLE equipment
                ADD COLUMN {column_name} {column_type}
                """
            )

    # =========================================
    # СИД ОБОРУДОВАНИЯ УБРАН
    # =========================================
    # Раньше здесь при КАЖДОМ старте сервера делался
    # INSERT OR IGNORE для "Упаковочной линии" и "Упаковочной
    # машины". Из-за этого cleanup_upakovochnaya_liniya.py
    # удалял дубль, а следующий перезапуск возвращал его обратно —
    # запись невозможно было убрать насовсем.
    #
    # Реальное оборудование заводится через seed_real_equipment.py
    # (разово) и через "Настройки -> Оборудование" в вебе.
    # init_equipment() теперь занимается ТОЛЬКО миграциями схемы.

    # =========================================
    # FIX STAGE FOR EXISTING RECORDS
    # (созданы до появления колонки stage)
    # =========================================

    cursor.execute(
        """
        UPDATE equipment
        SET stage = 'packaging'
        WHERE name = 'Упаковочная машина'
          AND (stage IS NULL OR stage = '')
        """
    )

    # =========================================
    # FIX DEFAULT VALUES FOR OLD RECORDS
    # =========================================

    cursor.execute(
        """
        UPDATE equipment
        SET health = 100
        WHERE health IS NULL
        """
    )

    cursor.execute(
        """
        UPDATE equipment
        SET readiness = 100
        WHERE readiness IS NULL
        """
    )

    cursor.execute(
        """
        UPDATE equipment
        SET maintenance_required = 0
        WHERE maintenance_required IS NULL
        """
    )

    conn.commit()
    conn.close()


# =========================================================
# GET ALL EQUIPMENT
# =========================================================

def get_all_equipment():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            name,
            type,
            status,
            health,
            readiness,
            location,
            parent_id,
            level,
            maintenance_required,
            last_issue,
            last_check,
            updated_at,
            stage,
            discipline
        FROM equipment
        ORDER BY
            CASE
                WHEN level = 'line' THEN 0
                ELSE 1
            END,
            id
    """)

    rows = cursor.fetchall()

    conn.close()

    return [
        dict(row)
        for row in rows
    ]


# =========================================================
# GET ONE EQUIPMENT
# =========================================================

def get_equipment(equipment_id: int):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            name,
            type,
            status,
            health,
            readiness,
            location,
            parent_id,
            level,
            maintenance_required,
            last_issue,
            last_check,
            updated_at,
            stage,
            discipline
        FROM equipment
        WHERE id = ?
    """, (equipment_id,))

    row = cursor.fetchone()

    conn.close()

    if row:
        return dict(row)

    return None


# =========================================================
# FIND EQUIPMENT BY MACHINE NAME
# =========================================================

def find_equipment_by_machine(machine: str):

    if not machine:
        return None

    value = machine.strip().lower()

    conn = get_connection()
    cursor = conn.cursor()

    # -----------------------------------------
    # Direct aliases
    # -----------------------------------------

    aliases = {

        "messersi":
            "Упаковочная машина",

        "packer":
            "Упаковочная машина",

        "упаковочная машина":
            "Упаковочная машина",

        "упаковочная линия":
            "Упаковочная линия"

    }

    equipment_name = aliases.get(
        value
    )

    # -----------------------------------------
    # Search by alias
    # -----------------------------------------

    if equipment_name:

        cursor.execute(
            """
            SELECT *
            FROM equipment
            WHERE name = ?
            """,
            (equipment_name,)
        )

        row = cursor.fetchone()

        conn.close()

        return dict(row) if row else None

    # -----------------------------------------
    # Search by substring — сделано в Python, а не в SQL.
    # У SQLite встроенная LOWER() не умеет в кириллицу (только
    # ASCII), поэтому "WHERE LOWER(name) LIKE ..." молча не
    # находил ни одного из 48 станков с русскими названиями —
    # они просто никогда не получали обновление статуса/readiness
    # при создании обращения. Python .lower() кириллицу приводит
    # правильно, поэтому сравнение делаем здесь.
    # -----------------------------------------

    cursor.execute("SELECT * FROM equipment")

    rows = cursor.fetchall()

    conn.close()

    for row in rows:

        item = dict(row)

        if value in (item["name"] or "").lower():
            return item

        if value in (item["type"] or "").lower():
            return item

    return None


# =========================================================
# UPDATE EQUIPMENT STATUS
# =========================================================

def update_equipment_status(
    equipment_id: int,
    status: str,
    health: int | None = None,
    readiness: int | None = None
):

    conn = get_connection()
    cursor = conn.cursor()

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    cursor.execute(
        """
        UPDATE equipment
        SET
            status = ?,
            health = COALESCE(?, health),
            readiness = COALESCE(?, readiness),
            last_check = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            status,
            health,
            readiness,
            now,
            now,
            equipment_id
        )
    )

    conn.commit()
    conn.close()

def create_equipment(name, type_, stage, discipline, location=None):
    """Для "Настройки → Оборудование" — добавление станка через веб
    вместо seed_real_equipment.py в терминале."""

    if not name or not name.strip():
        raise ValueError("Название станка не может быть пустым.")

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            INSERT INTO equipment (name, type, stage, discipline, location, status, updated_at)
            VALUES (?, ?, ?, ?, ?, 'Работает', ?)
            """,
            (name.strip(), type_, stage, discipline, location, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )

    except sqlite3.IntegrityError:

        conn.close()
        raise ValueError(f"Станок с названием «{name}» уже существует.")

    equipment_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return equipment_id


def update_equipment_details(equipment_id, name, type_, stage, discipline, location):
    """Редактирование данных станка (не статуса — для этого есть
    update_equipment_status, отдельная более узкая функция)."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM equipment WHERE id = ?", (equipment_id,))

    if not cursor.fetchone():
        conn.close()
        raise ValueError("Станок не найден.")

    try:

        cursor.execute(
            """
            UPDATE equipment
            SET name = ?, type = ?, stage = ?, discipline = ?, location = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                name.strip(), type_, stage, discipline, location,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), equipment_id
            )
        )

    except sqlite3.IntegrityError:

        conn.close()
        raise ValueError(f"Станок с названием «{name}» уже существует.")

    conn.commit()
    conn.close()
