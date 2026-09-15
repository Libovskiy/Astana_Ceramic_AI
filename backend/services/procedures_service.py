"""
Инструкции по станкам — реальные пошаговые процедуры, вводимые
теми, кто их знает (гл. инженер/гл. механик/гл. электрик/админ).
Содержание НЕ выдумывается системой — пустой список, пока кто-то
реально не добавит процедуру.

Пример из документа пользователя:
    Упаковочная машина → "Плёнка рвётся"
    ⏱ ~5 минут, 👤 Для рабочего, ⚠️ Требуется остановка
    [Начать инструкцию] → шаги показываются по одному.
"""

import sqlite3
from datetime import datetime

from backend.config import DB_NAME


def get_connection():

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row

    return conn


def init_procedures_tables():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS procedures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipment_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            duration_minutes INTEGER,
            target_role TEXT,
            requires_stop INTEGER NOT NULL DEFAULT 0,
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS procedure_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            procedure_id INTEGER NOT NULL,
            step_number INTEGER NOT NULL,
            text TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def create_procedure(equipment_id, title, duration_minutes, target_role, requires_stop, steps, created_by):

    if not title or not title.strip():
        raise ValueError("Название процедуры не может быть пустым.")

    if not steps or not any(step.strip() for step in steps):
        raise ValueError("Нужен хотя бы один шаг.")

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO procedures
            (equipment_id, title, duration_minutes, target_role, requires_stop, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            equipment_id,
            title.strip(),
            duration_minutes,
            target_role,
            1 if requires_stop else 0,
            created_by,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
    )

    procedure_id = cursor.lastrowid

    for i, step_text in enumerate(steps, start=1):

        if not step_text.strip():
            continue

        cursor.execute(
            "INSERT INTO procedure_steps (procedure_id, step_number, text) VALUES (?, ?, ?)",
            (procedure_id, i, step_text.strip())
        )

    conn.commit()
    conn.close()

    return procedure_id


def get_procedures_by_equipment():
    """Все процедуры, сгруппированные по станку — для главного
    списка страницы "Инструкции" (без самих шагов, только заголовки —
    шаги подгружаются отдельно при открытии конкретной инструкции)."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            procedures.id,
            procedures.equipment_id,
            procedures.title,
            procedures.duration_minutes,
            procedures.target_role,
            procedures.requires_stop,
            equipment.name AS equipment_name
        FROM procedures
        LEFT JOIN equipment ON equipment.id = procedures.equipment_id
        ORDER BY equipment.name, procedures.title
        """
    )

    rows = [dict(row) for row in cursor.fetchall()]

    conn.close()

    grouped = {}

    for row in rows:

        key = row["equipment_name"] or "Без станка"

        grouped.setdefault(key, []).append(row)

    return grouped


def get_procedure_with_steps(procedure_id):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            procedures.*,
            equipment.name AS equipment_name
        FROM procedures
        LEFT JOIN equipment ON equipment.id = procedures.equipment_id
        WHERE procedures.id = ?
        """,
        (procedure_id,)
    )

    procedure_row = cursor.fetchone()

    if not procedure_row:
        conn.close()
        return None

    cursor.execute(
        "SELECT step_number, text FROM procedure_steps WHERE procedure_id = ? ORDER BY step_number",
        (procedure_id,)
    )

    steps = [dict(row) for row in cursor.fetchall()]

    conn.close()

    procedure = dict(procedure_row)
    procedure["steps"] = steps

    return procedure


def delete_procedure(procedure_id):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM procedure_steps WHERE procedure_id = ?", (procedure_id,))
    cursor.execute("DELETE FROM procedures WHERE id = ?", (procedure_id,))

    conn.commit()
    conn.close()


def find_matching_procedure(equipment_id, question_text):
    """
    Ищет инструкцию для этого станка, название которой упоминается
    в тексте вопроса (простое совпадение по словам, без ИИ —
    честно и предсказуемо). Возвращает первую подходящую с шагами,
    или None, если ничего не совпало.

    "ё"/"е" приводятся к одному виду — тот же принцип, что и в
    остальном проекте (machine_service.py/symptom_service.py).
    """

    if not equipment_id or not question_text:
        return None

    question_normalized = question_text.lower().replace("ё", "е")

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, title FROM procedures WHERE equipment_id = ?",
        (equipment_id,)
    )

    candidates = cursor.fetchall()

    conn.close()

    for row in candidates:

        title_normalized = row["title"].lower().replace("ё", "е")

        # Совпадение, если хотя бы одно значимое слово из названия
        # инструкции (длиннее 3 символов) встречается в вопросе.
        title_words = [w for w in title_normalized.split() if len(w) > 3]

        if any(word in question_normalized for word in title_words):
            return get_procedure_with_steps(row["id"])

    return None
