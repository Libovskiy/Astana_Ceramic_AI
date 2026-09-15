"""
Журнал расчётов состава смеси для технолога/лаборанта.

Расширенная модель партии (по запросу пользователя, для лаборантов):
    - Партия: дата/время, смена, ответственный, вес партии
    - Глина: источник/карьер, номер партии сырья, влажность до/после
    - Песок: источник, номер партии, влажность
    - Рецептура: % глины/песка, фактический вес каждого компонента
    - Результат: качество смеси (outcome), примечание

Похожие партии ищутся по точному совпадению источника глины и
источника песка — это единственный способ надёжно сравнить "похожие"
партии без гадания на нечётких текстовых полях. ИИ (suggest_mix_proportion
в ai_service.py) использует эту историю как подсказку, но НИКОГДА не
решает сам — только показывает, что было раньше, лаборант решает сам.
"""

import sqlite3
from datetime import datetime

from backend.config import DB_NAME


def get_connection():

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row

    return conn


def init_mix_table():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mix_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_by TEXT NOT NULL,
            shift TEXT,
            batch_weight_kg REAL NOT NULL,

            clay_source TEXT,
            clay_batch_number TEXT,
            clay_moisture_before REAL,
            clay_moisture_after REAL,

            sand_source TEXT,
            sand_batch_number TEXT,
            sand_moisture REAL,

            clay_percent REAL NOT NULL,
            sand_percent REAL NOT NULL,
            clay_weight_kg REAL NOT NULL,
            sand_weight_kg REAL NOT NULL,

            note TEXT,
            outcome TEXT,
            created_at TEXT NOT NULL
        )
    """)

    # -----------------------------------------
    # Миграция для уже существующей таблицы —
    # добавляем новые поля партии, если их ещё нет
    # (таблица могла быть создана до этого расширения).
    # -----------------------------------------

    existing_columns = {
        row["name"]
        for row in cursor.execute("PRAGMA table_info(mix_log)").fetchall()
    }

    new_columns = {
        "outcome": "TEXT",
        "shift": "TEXT",
        "clay_source": "TEXT",
        "clay_batch_number": "TEXT",
        "clay_moisture_before": "REAL",
        "clay_moisture_after": "REAL",
        "sand_source": "TEXT",
        "sand_batch_number": "TEXT",
        "sand_moisture": "REAL"
    }

    for column_name, column_type in new_columns.items():

        if column_name not in existing_columns:
            cursor.execute(f"ALTER TABLE mix_log ADD COLUMN {column_name} {column_type}")

    conn.commit()
    conn.close()


def create_mix_entry(
    created_by,
    batch_weight_kg,
    clay_percent,
    note=None,
    shift=None,
    clay_source=None,
    clay_batch_number=None,
    clay_moisture_before=None,
    clay_moisture_after=None,
    sand_source=None,
    sand_batch_number=None,
    sand_moisture=None
):

    if batch_weight_kg <= 0:
        raise ValueError("Вес партии должен быть больше нуля.")

    if not (0 <= clay_percent <= 100):
        raise ValueError("Процент глины должен быть от 0 до 100.")

    sand_percent = 100 - clay_percent

    clay_weight_kg = round(batch_weight_kg * clay_percent / 100, 1)
    sand_weight_kg = round(batch_weight_kg * sand_percent / 100, 1)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO mix_log (
            created_by, shift, batch_weight_kg,
            clay_source, clay_batch_number, clay_moisture_before, clay_moisture_after,
            sand_source, sand_batch_number, sand_moisture,
            clay_percent, sand_percent, clay_weight_kg, sand_weight_kg,
            note, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            created_by, shift, batch_weight_kg,
            clay_source, clay_batch_number, clay_moisture_before, clay_moisture_after,
            sand_source, sand_batch_number, sand_moisture,
            clay_percent, sand_percent, clay_weight_kg, sand_weight_kg,
            note, datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
    )

    entry_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return {
        "id": entry_id,
        "created_by": created_by,
        "shift": shift,
        "batch_weight_kg": batch_weight_kg,
        "clay_source": clay_source,
        "clay_batch_number": clay_batch_number,
        "clay_moisture_before": clay_moisture_before,
        "clay_moisture_after": clay_moisture_after,
        "sand_source": sand_source,
        "sand_batch_number": sand_batch_number,
        "sand_moisture": sand_moisture,
        "clay_percent": clay_percent,
        "sand_percent": sand_percent,
        "clay_weight_kg": clay_weight_kg,
        "sand_weight_kg": sand_weight_kg,
        "note": note
    }


def get_mix_entries(limit=50):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM mix_log
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,)
    )

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def update_outcome(entry_id, outcome):
    """
    Результат замеса (хорошо / брак / трещины и т.п.) — то, на чём
    в будущем учится ИИ-подсказка (suggest_mix_proportion). Без этого
    поля вся история — просто цифры без обратной связи.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE mix_log SET outcome = ? WHERE id = ?",
        (outcome, entry_id)
    )

    updated = cursor.rowcount > 0

    conn.commit()
    conn.close()

    return updated


def find_similar_batches(clay_source, sand_source, limit=20):
    """
    "Похожие партии" — точное совпадение источника глины И источника
    песка (единственный надёжный способ сравнивать без нечёткого
    сопоставления текста). Возвращает историю + статистику для
    честной ИИ-подсказки (без "делай X", только "было раньше так").
    """

    if not clay_source or not sand_source:
        return {"entries": [], "stats": None}

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM mix_log
        WHERE clay_source = ? AND sand_source = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (clay_source, sand_source, limit)
    )

    rows = [dict(row) for row in cursor.fetchall()]

    conn.close()

    if not rows:
        return {"entries": [], "stats": None}

    good_entries = [row for row in rows if row["outcome"] == "Хорошо"]

    stats = None

    if good_entries:

        avg_clay_percent = round(
            sum(row["clay_percent"] for row in good_entries) / len(good_entries),
            1
        )

        moistures = [
            row["clay_moisture_after"]
            for row in good_entries
            if row["clay_moisture_after"] is not None
        ]

        avg_moisture_after = (
            round(sum(moistures) / len(moistures), 1)
            if moistures
            else None
        )

        stats = {
            "total_batches": len(rows),
            "good_batches": len(good_entries),
            "recommended_clay_percent": avg_clay_percent,
            "avg_moisture_after": avg_moisture_after
        }

    return {
        "entries": rows,
        "stats": stats
    }
