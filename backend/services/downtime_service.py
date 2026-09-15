"""
Учёт простоев оборудования — "начать простой" / "завершить простой",
с хранением причины, длительности и того, кто зафиксировал/устранил.

Одновременно на одном станке может идти только ОДИН активный простой —
start_downtime() проверяет это и отказывает, если уже есть незакрытый.
"""

import sqlite3
from datetime import datetime

from backend.config import DB_NAME


def get_connection():

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row

    return conn


def init_downtime_table():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS downtime_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipment_id INTEGER NOT NULL,
            reason TEXT,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            started_by TEXT,
            ended_by TEXT
        )
    """)

    # -----------------------------------------
    # Миграция для уже существующей таблицы — duration_minutes и
    # case_id были добавлены в код позже (для очереди работ и
    # аналитики), но CREATE TABLE IF NOT EXISTS не досоздаёт
    # колонки в таблице, которая уже была создана раньше по
    # старой схеме. Без этого — OperationalError на реальных
    # установках, где downtime_log завели ещё до этих полей.
    # -----------------------------------------

    existing_columns = {
        row[1]
        for row in cursor.execute("PRAGMA table_info(downtime_log)").fetchall()
    }

    if "duration_minutes" not in existing_columns:
        cursor.execute("ALTER TABLE downtime_log ADD COLUMN duration_minutes INTEGER")

    if "case_id" not in existing_columns:
        cursor.execute("ALTER TABLE downtime_log ADD COLUMN case_id INTEGER")

    conn.commit()
    conn.close()


def get_active_downtime_for_equipment(equipment_id):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT * FROM downtime_log
        WHERE equipment_id = ? AND ended_at IS NULL
        ORDER BY id DESC
        LIMIT 1
        """,
        (equipment_id,)
    )

    row = cursor.fetchone()
    conn.close()

    return dict(row) if row else None


def start_downtime(equipment_id, reason, started_by, case_id=None):

    existing = get_active_downtime_for_equipment(equipment_id)

    if existing:
        raise ValueError("Для этого станка уже зафиксирован незавершённый простой.")

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO downtime_log (equipment_id, reason, started_at, started_by, case_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            equipment_id,
            reason,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            started_by,
            case_id
        )
    )

    downtime_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return downtime_id


def end_downtime(downtime_id, ended_by):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM downtime_log WHERE id = ?",
        (downtime_id,)
    )

    row = cursor.fetchone()

    if not row:
        conn.close()
        raise ValueError("Запись о простое не найдена.")

    if row["ended_at"]:
        conn.close()
        raise ValueError("Этот простой уже завершён.")

    ended_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    started_at = datetime.strptime(row["started_at"], "%Y-%m-%d %H:%M:%S")
    ended_at_dt = datetime.strptime(ended_at, "%Y-%m-%d %H:%M:%S")

    duration_minutes = round((ended_at_dt - started_at).total_seconds() / 60)

    # -----------------------------------------
    # duration_minutes ОБЯЗАТЕЛЬНО пишем в базу.
    # Раньше он только возвращался наружу, а колонка оставалась
    # NULL. При этом analytics_service.get_downtime_by_period()
    # трактует NULL как "простой ещё идёт" и досчитывает время
    # до текущего момента — то есть завершённый вчера 10-минутный
    # простой на дашборде директора превращался в многочасовой,
    # и цифры росли каждый день сами по себе.
    # -----------------------------------------

    cursor.execute(
        """
        UPDATE downtime_log
        SET ended_at = ?, ended_by = ?, duration_minutes = ?
        WHERE id = ?
        """,
        (ended_at, ended_by, duration_minutes, downtime_id)
    )

    conn.commit()
    conn.close()

    return duration_minutes


def get_active_downtimes():
    """Все сейчас идущие простои по всему заводу — для дашборда/производства."""

    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            downtime_log.*,
            equipment.name AS equipment_name,
            equipment.stage AS equipment_stage,
            equipment.discipline AS equipment_discipline
        FROM downtime_log
        LEFT JOIN equipment ON equipment.id = downtime_log.equipment_id
        WHERE downtime_log.ended_at IS NULL
        ORDER BY downtime_log.started_at ASC
        """
    )

    rows = cursor.fetchall()
    conn.close()

    now = datetime.now()

    result = []

    for row in rows:

        item = dict(row)

        started_at = datetime.strptime(item["started_at"], "%Y-%m-%d %H:%M:%S")

        item["duration_minutes"] = round((now - started_at).total_seconds() / 60)

        result.append(item)

    return result


def get_downtime_history(equipment_id=None, limit=50):

    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = """
        SELECT
            downtime_log.*,
            equipment.name AS equipment_name
        FROM downtime_log
        LEFT JOIN equipment ON equipment.id = downtime_log.equipment_id
        WHERE 1 = 1
    """

    params = []

    if equipment_id:
        query += " AND downtime_log.equipment_id = ?"
        params.append(equipment_id)

    query += " ORDER BY downtime_log.id DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)

    rows = cursor.fetchall()
    conn.close()

    result = []

    for row in rows:

        item = dict(row)

        if item["ended_at"]:

            started_at = datetime.strptime(item["started_at"], "%Y-%m-%d %H:%M:%S")
            ended_at = datetime.strptime(item["ended_at"], "%Y-%m-%d %H:%M:%S")

            item["duration_minutes"] = round((ended_at - started_at).total_seconds() / 60)

        else:

            item["duration_minutes"] = None

        result.append(item)

    return result


def get_total_downtime_today():
    """
    Суммарный простой за сегодня в минутах — для карточки "Простой"
    на дашборде (сейчас всегда показывает "—", это её реальные данные).
    Считает и завершённые за сегодня простои, и текущие активные
    (по состоянию на сейчас).
    """

    today = datetime.now().strftime("%Y-%m-%d")

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM downtime_log WHERE started_at >= ?",
        (f"{today} 00:00:00",)
    )

    rows = cursor.fetchall()
    conn.close()

    now = datetime.now()
    total_minutes = 0

    for row in rows:

        started_at = datetime.strptime(row["started_at"], "%Y-%m-%d %H:%M:%S")

        if row["ended_at"]:
            ended_at = datetime.strptime(row["ended_at"], "%Y-%m-%d %H:%M:%S")
        else:
            ended_at = now

        total_minutes += (ended_at - started_at).total_seconds() / 60

    return round(total_minutes)


def try_auto_start_downtime(equipment_id, reason, started_by, case_id=None):
    """
    Автостарт простоя при создании/привязке обращения к станку —
    по решению пользователя, простой теперь связан с обращением
    автоматически, не требует отдельного ручного "Начать простой".

    Безопасно вызывать многократно (например, на каждое сообщение
    в чате диагностики для одного и того же обращения) — если у
    станка уже идёт простой (свой или от другого обращения), тихо
    ничего не делает, не поднимает ошибку. Обрыв цепочки создания
    обращения из-за этого недопустим — простой второстепенен.
    """

    if not equipment_id:
        return

    try:
        start_downtime(equipment_id, reason=reason, started_by=started_by, case_id=case_id)
    except ValueError:
        # Уже есть активный простой для этого станка — ожидаемо,
        # не ошибка.
        pass


def try_auto_end_downtime_for_case(case_id, ended_by):
    """
    Автозавершение простоя при "Завершить ремонт" — находит
    активный простой, привязанный к этому обращению (case_id в
    downtime_log), и завершает его. Если простоя не было (например,
    завели вручную раньше или вообще не было) — тихо ничего не
    делает.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id FROM downtime_log WHERE case_id = ? AND ended_at IS NULL",
        (case_id,)
    )

    row = cursor.fetchone()

    conn.close()

    if not row:
        return

    try:
        end_downtime(row["id"], ended_by=ended_by)
    except ValueError:
        pass
