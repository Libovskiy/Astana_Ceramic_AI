import sqlite3
from datetime import datetime, timedelta

from backend.config import DB_NAME, ACTIVE_CASE_WINDOW_HOURS


STATUS_OPEN = "Открыто"
STATUS_DRAFT_CLOSED = "Черновик закрытия"
STATUS_CLOSED = "Закрыто"
STATUS_ESCALATED = "Требует специалиста"
STATUS_IN_PROGRESS = "В работе"


def create_case(machine, symptom, worker_question, equipment_id=None):

    # Чья это смена. Берём из графика: обращение заводит тот, кто
    # сейчас у станка, а сейчас у станка работает бригада по табелю.
    # Нужно для раздельных архивов — начальник смены А не должен
    # видеть обращения смены Б.
    try:
        from backend.services.shift_schedule_service import get_shift_at
        current = get_shift_at()
        brigade = current["brigade"]
        shift = current["shift"]
    except Exception as error:
        print(f"[case_service] Не удалось определить смену: {error}")
        brigade = None
        shift = None

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO cases (
            machine,
            symptom,
            worker_question,
            status,
            created_at,
            closed_at,
            closed_by,
            resolution_comment,
            draft_closed_by,
            draft_resolution_comment,
            draft_closed_at,
            equipment_id,
            brigade,
            shift
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        machine,
        symptom,
        worker_question,
        STATUS_OPEN,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        None,
        None,
        None,
        None,
        None,
        None,
        equipment_id,
        brigade,
        shift
    ))

    case_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return case_id


def get_active_case(equipment_id=None, machine=None):
    """
    Ищет уже открытое обращение ПО ЭТОМУ ЖЕ станку, чтобы новое
    сообщение продолжало его, а не плодило дубли.

    Было: брал последнее обращение со статусом "Открыто" по ВСЕМУ
    заводу и без ограничения по времени. На практике это значит,
    что рабочий, написавший про печь, дописывался в чужое открытое
    обращение по дробилке — вся переписка, простой и статистика
    уходили не тому станку. В две смены на 50 станков это ломается
    в первый же день.

    Стало:
    - обязательна привязка к станку (equipment_id, иначе — по полю
      machine для /chat, где ID ещё неизвестен);
    - обращение считается "тем же самым" только в пределах
      ACTIVE_CASE_WINDOW_HOURS (по умолчанию 12 часов), иначе
      вчерашняя незакрытая проблема будет вечно поглощать все
      новые жалобы по этому станку;
    - если станок не определён вообще — возвращаем None
      (создастся новое обращение). Это безопаснее, чем приклеиться
      к случайному чужому.
    """

    if equipment_id is None and not machine:
        return None

    cutoff = (
        datetime.now() - timedelta(hours=ACTIVE_CASE_WINDOW_HOURS)
    ).strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    if equipment_id is not None:

        cursor.execute("""
            SELECT id
            FROM cases
            WHERE status = ?
              AND equipment_id = ?
              AND created_at >= ?
            ORDER BY id DESC
            LIMIT 1
        """, (STATUS_OPEN, equipment_id, cutoff))

    else:

        cursor.execute("""
            SELECT id
            FROM cases
            WHERE status = ?
              AND equipment_id IS NULL
              AND LOWER(machine) = LOWER(?)
              AND created_at >= ?
            ORDER BY id DESC
            LIMIT 1
        """, (STATUS_OPEN, machine, cutoff))

    row = cursor.fetchone()

    conn.close()

    if row:
        return row[0]

    return None


def get_known_symptoms(equipment_id=None, limit=60):
    """
    Названия симптомов, которые УЖЕ встречались на заводе, — по
    убыванию частоты.

    Это и есть справочник неисправностей, только его никто не
    пишет руками: он складывается сам из закрытых и открытых
    обращений. ИИ получает этот список и старается переиспользовать
    существующую формулировку, а не плодить синонимы — иначе
    "подшипник греется" и "горячий подшипник" стали бы двумя
    разными строками, и аналитика никогда бы не показала, что узел
    ломается пятый раз.

    Симптомы этого же станка идут первыми (они вероятнее всего
    подойдут снова), дальше — самые частые по всему заводу.
    """

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    names = []
    seen = set()

    def collect(rows):
        for row in rows:
            name = (row["symptom"] or "").strip()
            key = name.lower()
            if name and key not in seen:
                seen.add(key)
                names.append(name)

    if equipment_id is not None:

        cursor.execute(
            """
            SELECT symptom, COUNT(*) AS n
            FROM cases
            WHERE equipment_id = ? AND symptom IS NOT NULL AND symptom != ''
            GROUP BY LOWER(symptom)
            ORDER BY n DESC
            LIMIT ?
            """,
            (equipment_id, limit)
        )

        collect(cursor.fetchall())

    if len(names) < limit:

        cursor.execute(
            """
            SELECT symptom, COUNT(*) AS n
            FROM cases
            WHERE symptom IS NOT NULL AND symptom != ''
            GROUP BY LOWER(symptom)
            ORDER BY n DESC
            LIMIT ?
            """,
            (limit,)
        )

        collect(cursor.fetchall())

    conn.close()

    return names[:limit]


def _restore_equipment_state(case_id):
    """
    Вернуть станку readiness, снятый этим обращением.

    Импорт локальный — equipment_state_service тянет за собой
    equipment_service, и держать это на уровне модуля незачем:
    case_service импортируется почти отовсюду.

    Ошибка здесь не должна ломать закрытие обращения: закрытие
    важнее пересчёта индикатора.
    """

    try:

        from backend.services.equipment_state_service import resolve_case_state

        case = get_case(case_id)

        if case and case.get("equipment_id"):
            resolve_case_state(case["equipment_id"], case_id)

    except Exception as error:
        print(f"[case_service] Не удалось восстановить состояние станка: {error}")


def draft_close_case(case_id, drafted_by, draft_comment=None):
    """
    Черновик закрытия — составляет начальник смены. Обращение
    переходит в статус "Черновик закрытия" и ждёт подтверждения
    главным инженером (approve_close_case).
    """

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE cases
        SET
            status = ?,
            draft_closed_by = ?,
            draft_resolution_comment = ?,
            draft_closed_at = ?
        WHERE id = ?
    """, (
        STATUS_DRAFT_CLOSED,
        drafted_by,
        draft_comment,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        case_id
    ))

    conn.commit()
    conn.close()


def approve_close_case(case_id, approved_by, final_comment=None):
    """
    Финальное закрытие — только главный инженер (или админ).
    Если final_comment не передан, используется черновой комментарий
    начальника смены как есть (главный инженер согласился без правок).
    """

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE cases
        SET
            status = ?,
            closed_at = ?,
            closed_by = ?,
            resolution_comment = COALESCE(?, draft_resolution_comment),
            resolved_by = ?
        WHERE id = ?
    """, (
        STATUS_CLOSED,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        approved_by,
        final_comment,
        "specialist",
        case_id
    ))

    conn.commit()
    conn.close()

    # Обращение закрыто специалистом — снимаем с индикатора станка
    # то, что было списано этим обращением (см. resolve_case_state).
    _restore_equipment_state(case_id)


def get_case(case_id):

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM cases
        WHERE id = ?
    """, (case_id,))

    row = cursor.fetchone()

    conn.close()

    if row:
        return dict(row)

    return None


def get_cases_by_equipment(equipment_id, limit=100):
    """
    Для журнала жизни оборудования — все обращения, привязанные
    к конкретному станку по ID (а не по шаткому совпадению строки
    "machine"). Работает только для обращений, созданных ПОСЛЕ
    миграции equipment_id — более старые обращения (equipment_id
    NULL) в журнал не попадут, это ожидаемый разрыв в истории.
    """

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM cases
        WHERE equipment_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (equipment_id, limit)
    )

    rows = cursor.fetchall()

    conn.close()

    return [dict(row) for row in rows]


def set_case_equipment(case_id, equipment_id):
    """
    Проставляет equipment_id уже созданному обращению — нужно для
    /chat, где оборудование определяется только ПОСЛЕ того, как
    search() уже создал обращение (машина распознаётся по ключевым
    словам внутри search(), а не передаётся заранее, как в /diagnose).
    """

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE cases SET equipment_id = ? WHERE id = ?",
        (equipment_id, case_id)
    )

    conn.commit()
    conn.close()


def get_cases_pending_approval():
    """Обращения с черновиком, ожидающие подтверждения главного инженера."""

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM cases
        WHERE status = ?
        ORDER BY draft_closed_at DESC
    """, (STATUS_DRAFT_CLOSED,))

    rows = cursor.fetchall()

    conn.close()

    return [dict(row) for row in rows]


def set_step(case_id, step):

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE cases SET current_step = ? WHERE id = ?",
        (step, case_id)
    )

    conn.commit()
    conn.close()


def close_case_by_ai(case_id, resolution_comment):
    """
    Закрытие БЕЗ участия людей — рабочий подтвердил, что подсказка
    ИИ помогла. Не идёт через черновик/подтверждение и НЕ попадает
    в базу знаний (см. knowledge_service.py — там уже пояснено, почему).
    """

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE cases
        SET
            status = ?,
            closed_at = ?,
            closed_by = ?,
            resolution_comment = ?,
            resolved_by = ?
        WHERE id = ?
    """, (
        STATUS_CLOSED,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ACAI (автоматически)",
        resolution_comment,
        "ai",
        case_id
    ))

    conn.commit()
    conn.close()

    # Рабочий подтвердил, что подсказка помогла — станок исправен,
    # возвращаем снятый readiness.
    _restore_equipment_state(case_id)


def escalate_case(case_id):
    """ИИ исчерпал попытки — нужен специалист. Обращение остаётся
    в базе, ждёт, пока кто-то решит проблему вручную и это пройдёт
    через draft_close_case -> approve_close_case."""

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE cases SET status = ? WHERE id = ?",
        (STATUS_ESCALATED, case_id)
    )

    conn.commit()
    conn.close()


def search_case_events(
    date_from=None,
    date_to=None,
    equipment_id=None,
    stage=None,
    status=None,
    limit=200
):
    """
    Для страницы "Журнал событий" — обращения с фильтрами.
    В отличие от audit_log (кто что сделал), это про сами
    неисправности/обращения по оборудованию.

    stage требует JOIN с equipment (обращение само по себе не
    хранит этап — этап есть только у станка).

    Известное ограничение: у обращения нет поля "кто открыл" —
    сообщения от рабочих не привязаны к конкретному аккаунту при
    создании. Фильтр по пользователю поэтому смотрит только на
    closed_by/draft_closed_by (кто закрывал/подтверждал), а не
    на того, кто изначально пожаловался.
    """

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = """
        SELECT
            cases.*,
            equipment.stage AS equipment_stage,
            equipment.name AS equipment_name,
            equipment.discipline AS equipment_discipline
        FROM cases
        LEFT JOIN equipment ON equipment.id = cases.equipment_id
        WHERE 1 = 1
    """

    params = []

    if date_from:
        query += " AND cases.created_at >= ?"
        params.append(date_from)

    if date_to:
        query += " AND cases.created_at <= ?"
        params.append(date_to)

    if equipment_id:
        query += " AND cases.equipment_id = ?"
        params.append(equipment_id)

    if stage:
        query += " AND equipment.stage = ?"
        params.append(stage)

    if status:
        query += " AND cases.status = ?"
        params.append(status)

    query += " ORDER BY cases.id DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)

    rows = cursor.fetchall()

    conn.close()

    return [dict(row) for row in rows]


def get_recurring_issues(days=14, min_occurrences=3, limit=10):
    """
    Ищет повторяющиеся неисправности — один и тот же станок с
    похожей симптомой несколько раз за последние `days` дней.

    Группировка идёт по (equipment_id, symptom) — по названию
    распознанного симптома, а не по свободному тексту вопроса
    рабочего (тексты почти никогда не совпадают дословно, а
    симптом — уже категоризированное значение, надёжнее).

    Обращения без equipment_id или без symptom в группировку не
    попадают — для них невозможно надёжно определить "тот же самый"
    случай.
    """

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            cases.equipment_id,
            cases.symptom,
            cases.created_at,
            equipment.name AS equipment_name,
            equipment.discipline AS equipment_discipline
        FROM cases
        LEFT JOIN equipment ON equipment.id = cases.equipment_id
        WHERE
            cases.equipment_id IS NOT NULL
            AND cases.symptom IS NOT NULL
            AND cases.symptom != ''
            AND cases.created_at >= datetime('now', ?)
        ORDER BY cases.created_at DESC
        """,
        (f"-{days} days",)
    )

    rows = cursor.fetchall()

    conn.close()

    groups = {}

    for row in rows:

        key = (row["equipment_id"], row["symptom"])

        if key not in groups:

            groups[key] = {
                "equipment_id": row["equipment_id"],
                "equipment_name": row["equipment_name"],
                "equipment_discipline": row["equipment_discipline"],
                "symptom": row["symptom"],
                "dates": []
            }

        groups[key]["dates"].append(row["created_at"])

    recurring = [
        {
            **group,
            "count": len(group["dates"])
        }
        for group in groups.values()
        if len(group["dates"]) >= min_occurrences
    ]

    recurring.sort(key=lambda item: item["count"], reverse=True)

    return recurring[:limit]


def init_cases_tables():
    """
    Создаёт cases и chat_history "с нуля" (на новом сервере эти
    таблицы раньше никак не создавались — только backend/database/
    database.py, который никто не вызывал и в котором схема сильно
    отстала от реальной: не было даже assigned_to/assigned_at,
    не говоря об equipment_id/brigade/shift/required_discipline
    и author/author_role в chat_history).

    Функция описывает БАЗОВУЮ схему (CREATE TABLE IF NOT EXISTS —
    на старой базе ничего не тронет) и следом добавляет ЧЕРЕЗ
    ALTER TABLE все колонки, которые раньше появлялись только
    вручную на сервере, а в коде никак не создавались. Так что
    даже на уже работающей базе повторный запуск безопасен —
    PRAGMA table_info проверяет, что уже есть, и добавляет только
    недостающее.

    Заменяет старую init_work_queue_columns() (она добавляла
    только assigned_to/assigned_at — этого было мало).
    """

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine TEXT,
            symptom TEXT,
            worker_question TEXT,
            status TEXT,
            created_at TEXT,
            closed_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER,
            role TEXT,
            message TEXT,
            created_at TEXT
        )
    """)

    conn.commit()

    # -----------------------------------------
    # cases — колонки, добавленные после первой версии
    # -----------------------------------------

    cases_columns = {
        row[1]
        for row in cursor.execute("PRAGMA table_info(cases)").fetchall()
    }

    cases_migrations = [
        ("closed_by", "TEXT"),
        ("resolution_comment", "TEXT"),
        ("draft_closed_by", "TEXT"),
        ("draft_resolution_comment", "TEXT"),
        ("draft_closed_at", "TEXT"),
        ("current_step", "INTEGER DEFAULT 0"),
        ("resolved_by", "TEXT"),
        ("equipment_id", "INTEGER"),
        ("assigned_to", "TEXT"),
        ("assigned_at", "TEXT"),
        ("brigade", "TEXT"),
        ("shift", "TEXT"),
        ("required_discipline", "TEXT"),
    ]

    for column_name, column_type in cases_migrations:
        if column_name not in cases_columns:
            cursor.execute(f"ALTER TABLE cases ADD COLUMN {column_name} {column_type}")

    # -----------------------------------------
    # chat_history — колонки, добавленные после первой версии
    # -----------------------------------------

    chat_history_columns = {
        row[1]
        for row in cursor.execute("PRAGMA table_info(chat_history)").fetchall()
    }

    chat_history_migrations = [
        ("author", "TEXT"),
        ("author_role", "TEXT"),
    ]

    for column_name, column_type in chat_history_migrations:
        if column_name not in chat_history_columns:
            cursor.execute(f"ALTER TABLE chat_history ADD COLUMN {column_name} {column_type}")

    conn.commit()
    conn.close()


def take_case(case_id, assigned_to):
    """
    "Взять в работу" — специалист (механик/электрик) забирает
    обращение себе. Разрешено только из "Открыто" или "Требует
    специалиста" — нельзя взять то, что уже кто-то ведёт, или уже
    закрыто.
    """

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT status FROM cases WHERE id = ?", (case_id,))

    row = cursor.fetchone()

    if not row:
        conn.close()
        raise ValueError("Обращение не найдено.")

    if row["status"] not in (STATUS_OPEN, STATUS_ESCALATED):
        conn.close()
        raise ValueError(f"Нельзя взять в работу обращение со статусом «{row['status']}».")

    cursor.execute(
        """
        UPDATE cases
        SET status = ?, assigned_to = ?, assigned_at = ?
        WHERE id = ?
        """,
        (STATUS_IN_PROGRESS, assigned_to, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), case_id)
    )

    conn.commit()
    conn.close()


def complete_repair(case_id, resolution_comment, completed_by):
    """
    "Завершить ремонт" — специалист описывает, что сделал. НЕ
    закрывает обращение напрямую (специалист не должен сам менять
    статус оборудования на "Работает") — уходит в тот же черновик
    закрытия, что и у начальника смены, ждёт подтверждения
    гл. инженера. Переиспользует существующие draft_* поля.
    """

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT status FROM cases WHERE id = ?", (case_id,))

    row = cursor.fetchone()

    if not row:
        conn.close()
        raise ValueError("Обращение не найдено.")

    if row["status"] != STATUS_IN_PROGRESS:
        conn.close()
        raise ValueError(f"Нельзя завершить ремонт для обращения со статусом «{row['status']}».")

    cursor.execute(
        """
        UPDATE cases
        SET status = ?, draft_closed_by = ?, draft_resolution_comment = ?, draft_closed_at = ?
        WHERE id = ?
        """,
        (
            STATUS_DRAFT_CLOSED,
            completed_by,
            resolution_comment,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            case_id
        )
    )

    conn.commit()
    conn.close()


def get_work_queue(discipline=None):
    """
    Очередь работ для "Механика"/"Электрика" — открытые и взятые
    в работу обращения, отсортированные по срочности (сначала
    эскалированные, потом открытые, потом уже взятые в работу).

    discipline фильтрует по тому, КОГО позвал ИИ при передаче
    обращения (required_discipline). Если ИИ не определил —
    откатываемся на дисциплину станка ("both" видно обоим).
    None показывает все.
    """

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = """
        SELECT
            cases.*,
            equipment.name AS equipment_name,
            equipment.discipline AS equipment_discipline
        FROM cases
        LEFT JOIN equipment ON equipment.id = cases.equipment_id
        WHERE cases.status IN (?, ?, ?)
    """

    params = [STATUS_ESCALATED, STATUS_OPEN, STATUS_IN_PROGRESS]

    if discipline:

        # Главный признак — кого позвал ИИ (required_discipline).
        # Дисциплина станка используется только там, где ИИ не смог
        # определить: у станков с "both" иначе обращение видят и
        # механик, и электрик, и каждый думает, что пойдёт другой.
        query += """
            AND (
                cases.required_discipline = ?
                OR (
                    cases.required_discipline IS NULL
                    AND (equipment.discipline = ? OR equipment.discipline = 'both')
                )
            )
        """
        params.append(discipline)
        params.append(discipline)

    query += " ORDER BY cases.id DESC"

    cursor.execute(query, params)

    rows = [dict(row) for row in cursor.fetchall()]

    conn.close()

    priority = {STATUS_ESCALATED: 0, STATUS_OPEN: 1, STATUS_IN_PROGRESS: 2}

    rows.sort(key=lambda case: priority.get(case["status"], 99))

    return rows
