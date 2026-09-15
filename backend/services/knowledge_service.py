"""
База знаний подтверждённых решений.

Пополняется ТОЛЬКО когда главный инженер подтверждает закрытие
обращения (approve_close_case) — то есть только "ручные" решения
специалиста, которых не было в документации/прошлых подсказках ИИ.
Решения, которые нашёл сам ИИ и рабочий подтвердил "Помогло",
сюда не попадают — это уже было известно системе из документации,
переучивать её на этом не нужно.

Используется как дополнительный контекст для ai_service.suggest_next_action —
чем больше подтверждённых решений накопится, тем точнее будущие подсказки.
"""

import sqlite3
from datetime import datetime

from backend.config import DB_NAME


def get_connection():

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row

    return conn


def init_knowledge_base():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS resolution_knowledge_base (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine TEXT NOT NULL,
            symptom_text TEXT,
            resolution_comment TEXT NOT NULL,
            case_id INTEGER,
            confirmed_by TEXT,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
        )
    """)

    # Миграция старой БД: у существующих записей статус становится active.
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(resolution_knowledge_base)").fetchall()}
    if "status" not in columns:
        cursor.execute("ALTER TABLE resolution_knowledge_base ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
    conn.commit()
    conn.close()


def add_resolution(machine, symptom_text, resolution_comment, case_id, confirmed_by):

    if not resolution_comment:
        return

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO resolution_knowledge_base (
            machine, symptom_text, resolution_comment,
            case_id, confirmed_by, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            machine,
            symptom_text,
            resolution_comment,
            case_id,
            confirmed_by,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
    )

    conn.commit()
    conn.close()


def get_relevant_resolutions(machine, question, limit=3):
    """
    Простой поиск по ключевым словам (без векторного поиска —
    для объёма записей на старте этого достаточно; если база знаний
    вырастет до тысяч записей, стоит перенести в ChromaDB как отдельную
    коллекцию, инфраструктура для этого уже есть в vector_service.py).
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT resolution_comment, symptom_text
        FROM resolution_knowledge_base
        WHERE machine = ? AND COALESCE(status, 'active') = 'active'
        ORDER BY id DESC
        LIMIT 50
        """,
        (machine,)
    )

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return []

    question_words = set(question.lower().replace("ё", "е").split())

    scored = []

    for row in rows:

        symptom_words = set(
            (row["symptom_text"] or "").lower().replace("ё", "е").split()
        )

        overlap = len(question_words & symptom_words)

        scored.append((overlap, row["resolution_comment"]))

    scored.sort(key=lambda item: item[0], reverse=True)

    return [
        comment
        for score, comment in scored[:limit]
        if score > 0
    ]


def get_all_resolutions(limit=100):
    """Для страницы "База знаний" — все подтверждённые решения,
    сгруппированные по станку, для просмотра/поиска глазами."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, machine, symptom_text, resolution_comment, confirmed_by, created_at, status
        FROM resolution_knowledge_base
        WHERE COALESCE(status, 'active') = 'active'
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,)
    )

    rows = [dict(row) for row in cursor.fetchall()]

    conn.close()

    grouped = {}

    for row in rows:

        grouped.setdefault(row["machine"], []).append(row)

    return grouped
