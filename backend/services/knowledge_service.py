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


# Слова, которые есть в любой жалобе и ничего не различают.
_NOISE = {
    "на", "в", "и", "не", "с", "по", "что", "это", "для", "из", "от",
    "при", "как", "да", "нет", "был", "была", "было", "есть", "очень",
    "станок", "машина", "код", "ошибка",
}


def _normalize(text):
    return (text or "").lower().replace("ё", "е")


def _stem(word):
    """
    Грубая основа слова: «греется», «греется», «горячий» не сведутся, но
    «температура/температуры», «бруса/брус», «клапан/клапана» — да.

    Полноценной морфологии в проекте нет и не нужно: сравниваются две
    короткие фразы на русском, и хватает совпадения по началу слова.
    Тот же приём — в part_usage_service для поиска запчастей по тексту.
    """
    word = word.strip(".,;:()«»\"'?!")
    if len(word) > 7:
        return word[:-3]
    if len(word) > 5:
        return word[:-2]
    if len(word) > 4:
        return word[:-1]
    return word


def _keywords(text):
    return {
        _stem(word)
        for word in _normalize(text).split()
        if len(word) > 2 and word not in _NOISE
    }


def _same_machine(one, two):
    """
    Названия станка в обращении и в базе знаний совпадают не всегда
    дословно: «Экструдер шнековый MAGNA 575» и «Экструдер MAGNA».
    Считаем совпадением, если одно название содержится в другом.
    """
    one, two = _normalize(one).strip(), _normalize(two).strip()
    if not one or not two:
        return False
    return one == two or one in two or two in one


def find_similar(machine, question, limit=3):
    """
    Похожие подтверждённые случаи по этому станку — целиком, а не
    только текст решения: нужны ещё жалоба, номер обращения, кто
    подтвердил и когда. Человеку важно «когда это было и кто чинил»,
    ИИ — сама формулировка.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, machine, symptom_text, resolution_comment,
               case_id, confirmed_by, created_at
        FROM resolution_knowledge_base
        WHERE COALESCE(status, 'active') = 'active'
        ORDER BY id DESC
        LIMIT 200
        """
    )

    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()

    if not rows:
        return []

    asked = _keywords(question)

    scored = []

    for row in rows:

        if not _same_machine(machine, row["machine"]):
            continue

        symptom = _keywords(row["symptom_text"])
        # Название станка есть и в жалобе, и в симптоме — по нему
        # совпадает что угодно, поэтому оно из счёта исключается.
        symptom -= _keywords(row["machine"])

        score = 2 * len(asked & symptom) + len(asked & _keywords(row["resolution_comment"]))

        if score:
            scored.append((score, row))

    scored.sort(key=lambda item: item[0], reverse=True)

    return [row for _, row in scored[:limit]]


def similar_note(machine, question):
    """
    Строка для переписки: что уже помогало на этом станке.

    Её видит человек напрямую — она не зависит от того, захочет ли ИИ
    воспользоваться подсказкой. Ради этого база знаний и ведётся:
    в прошлый раз кто-то потратил смену, чтобы это выяснить.
    """
    found = find_similar(machine, question, limit=2)
    if not found:
        return ""

    lines = ["🔎 На этом станке уже было похожее:"]

    for row in found:
        when = (row.get("created_at") or "")[:10]
        when = ".".join(reversed(when.split("-"))) if when else ""
        who = row.get("confirmed_by") or "—"
        case = f"обращение №{row['case_id']}" if row.get("case_id") else "прошлый случай"
        lines.append(f"• «{(row.get('symptom_text') or '').strip()}» → {(row.get('resolution_comment') or '').strip()}")
        lines.append(f"  ({case}, подтвердил {who}{', ' + when if when else ''})")

    return "\n".join(lines)


def add_similar_note(case_id, question):
    """
    Дописать эту строку в переписку — отдельным сообщением с ролью
    `system`, как и подсказку по складу. Внутрь совета ИИ её класть
    нельзя: советы сравниваются с уже сказанным (`_tried_actions`),
    и приписка заставила бы ИИ ходить по шагам по кругу.

    Повторно одно и то же не пишем.
    """
    conn = get_connection()
    try:
        case = conn.execute(
            "SELECT machine, worker_question, symptom FROM cases WHERE id = ?", (case_id,)
        ).fetchone()
        if not case:
            return None

        note = similar_note(case["machine"], question or case["worker_question"] or case["symptom"] or "")
        if not note:
            return None

        already = conn.execute(
            "SELECT 1 FROM chat_history WHERE case_id = ? AND role = 'system' AND message = ? LIMIT 1",
            (case_id, note)
        ).fetchone()
        if already:
            return None
    finally:
        conn.close()

    from backend.services.conversation_service import add_message
    add_message(case_id, "system", note, author="ACAI")
    return note


def get_relevant_resolutions(machine, question, limit=3):
    """
    Поиск подтверждённых решений по этому станку.

    Раньше сравнивались слова как есть: «температура бруса высокая»
    находила запись, а «греется брус» или «брус горячий» — уже нет,
    хотя речь об одном и том же. Механик формулирует иначе, чем
    оператор, и знание, ради которого базу и ведут, до него не
    доходило (нашли 21.09.2026).

    Теперь сравниваются основы значимых слов, а искать можно и по
    тексту самого решения: механик пишет «клапан воды», и запись про
    клапан находится, даже если в жалобе было про температуру.

    Векторного поиска здесь намеренно нет: на нынешнем объёме он не
    нужен. Если база вырастет до тысяч записей — переносить в ChromaDB,
    инфраструктура есть в vector_service.py.
    """

    return [row["resolution_comment"] for row in find_similar(machine, question, limit)]


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

        # Страницы «База знаний» и «Инструкции» читают symptom и
        # resolution, а в базе колонки называются symptom_text и
        # resolution_comment. Из-за расхождения каждая карточка
        # выглядела пустым бланком: «Общее решение» без единой строки
        # описания, хотя решение в базе лежало целиком (18.09.2026,
        # обращение №64 — «неисправность клапана подачи воды»).
        # Отдаём под обоими именами: внутреннее название колонки не
        # должно течь в интерфейс, а старое имя кто-то мог уже читать.
        row["symptom"] = row.get("symptom_text")
        row["resolution"] = row.get("resolution_comment")

        grouped.setdefault(row["machine"], []).append(row)

    return grouped
