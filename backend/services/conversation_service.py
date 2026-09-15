"""
Обращение как ПЕРЕПИСКА, а не как форма с кнопками.

Рабочий пишет своими словами -> ИИ отвечает -> рабочий уточняет
("проверил, натяжение нормальное") -> ИИ предлагает следующий шаг.
Когда ИИ исчерпал варианты, обращение уходит специалисту, и тот
отвечает В ТОЙ ЖЕ ветке — рабочий не начинает разговор заново и
видит всю историю.

Чем отличается от прежней логики: раньше единственным сигналом
было "Помогло"/"Не помогло", и свободный текст рабочего после
первого сообщения никуда не попадал. Теперь каждое его сообщение
уходит в контекст ИИ вместе со всей перепиской, поэтому уточнения
("грелось только после запуска", "заменили подшипник, всё равно
шумит") реально влияют на следующий совет.

Ограничение шагов (MAX_AI_STEPS) сохранено: это защита от того,
чтобы рабочий бесконечно переписывался с ИИ вместо вызова
специалиста.
"""

import sqlite3
from datetime import datetime

from backend.config import DB_NAME, MAX_AI_STEPS

from backend.services.case_service import (
    get_case,
    set_step,
    escalate_case,
    close_case_by_ai,
    STATUS_OPEN,
    STATUS_ESCALATED,
    STATUS_IN_PROGRESS,
    STATUS_CLOSED,
    STATUS_DRAFT_CLOSED
)
from backend.services.vector_service import search_documents
from backend.services.filter_service import filter_results
from backend.services.knowledge_service import get_relevant_resolutions
from backend.services.procedures_service import find_matching_procedure
from backend.services.ai_service import (
    suggest_next_action,
    detect_resolution,
    detect_discipline
)
from backend.services.downtime_service import try_auto_end_downtime_for_case


# Роли, которые в переписке выступают как специалисты, а не как
# заявитель. Их сообщения ИИ не считает жалобой.
SPECIALIST_ROLES = (
    "chief_engineer", "engineer", "shift_supervisor",
    "chief_mechanic", "mechanic",
    "chief_electrician", "electrician",
    "admin", "director"
)

# Статусы, при которых переписка ещё живая.
ACTIVE_STATUSES = (STATUS_OPEN, STATUS_ESCALATED, STATUS_IN_PROGRESS)


def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


# =========================================================
# СООБЩЕНИЯ
# =========================================================

def add_message(case_id, role, message, author=None, author_role=None):
    """
    role — техническая роль в переписке:
        "worker"     — заявитель (тот, кто открыл обращение)
        "assistant"  — ИИ
        "specialist" — механик/электрик/инженер/начальник смены
        "system"     — служебные отметки (эскалация, закрытие)
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO chat_history (case_id, role, message, author, author_role, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            case_id,
            role,
            message,
            author,
            author_role,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
    )

    message_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return message_id


def get_messages(case_id):

    conn = get_connection()

    rows = conn.execute(
        """
        SELECT id, role, message, author, author_role, created_at
        FROM chat_history
        WHERE case_id = ?
        ORDER BY id
        """,
        (case_id,)
    ).fetchall()

    conn.close()

    return [dict(row) for row in rows]


# =========================================================
# КОНТЕКСТ ДЛЯ ИИ
# =========================================================

def _dialogue_text(messages, limit=12):
    """Последние реплики в виде текста — уходят в промпт, чтобы ИИ
    видел разговор целиком, а не только исходную жалобу."""

    lines = []

    for item in messages[-limit:]:

        if item["role"] == "assistant":
            speaker = "ACAI"
        elif item["role"] == "specialist":
            speaker = f"Специалист ({item.get('author') or '—'})"
        elif item["role"] == "system":
            continue
        else:
            speaker = "Рабочий"

        lines.append(f"{speaker}: {item['message']}")

    return "\n".join(lines)


def _tried_actions(messages):
    """Что ИИ уже предлагал — чтобы не повторялся."""

    return [
        item["message"]
        for item in messages
        if item["role"] == "assistant"
    ]


# =========================================================
# ОТВЕТ ИИ
# =========================================================



DISCIPLINE_TITLE = {
    "mechanical": "механика",
    "electrical": "электрика"
}


def _escalate(case_id, case, messages, reason, lead):
    """
    Передача специалисту — с указанием, КАКОМУ.

    Зачем разбирать: если звать "специалиста вообще", обращение
    видят и механик, и электрик. На практике это значит, что либо
    идут оба, либо каждый думает, что пойдёт другой. ИИ смотрит на
    саму неисправность — датчик не срабатывает, значит электрика,
    подшипник греется, значит механика.

    Если определить не удалось, оставляем как было: пусть видят
    оба. Позвать не того хуже, чем позвать обоих.
    """

    escalate_case(case_id)

    dialogue = _dialogue_text(messages)

    equipment_discipline = None

    if case.get("equipment_id"):
        try:
            from backend.services.equipment_service import get_equipment
            equipment = get_equipment(case["equipment_id"])
            equipment_discipline = equipment.get("discipline") if equipment else None
        except Exception:
            equipment_discipline = None

    discipline = detect_discipline(
        case.get("machine") or "",
        dialogue,
        equipment_discipline=equipment_discipline
    )

    if discipline:
        _set_required_discipline(case_id, discipline)
        who = DISCIPLINE_TITLE.get(discipline, "специалист")
        text = f"{lead} Здесь нужна {who} — передаю обращение."
    else:
        text = f"{lead} Передаю обращение специалисту — он ответит здесь же."

    _log_escalation(case_id, f"{reason}; дисциплина: {discipline or 'не определена'}")

    add_message(case_id, "system", text, author="ACAI")

    return {"type": "escalated", "message": text, "discipline": discipline}


def _set_required_discipline(case_id, discipline):

    try:
        conn = get_connection()
        conn.execute(
            "UPDATE cases SET required_discipline = ? WHERE id = ?",
            (discipline, case_id)
        )
        conn.commit()
        conn.close()
    except Exception as error:
        print(f"[conversation_service] Не удалось записать дисциплину: {error}")


def _log_escalation(case_id, reason):
    """
    Отмечаем в журнале момент, когда позвали человека.

    Без этой записи "сколько специалист шёл" пришлось бы считать от
    создания обращения — но пока ИИ вёл разбор, механика никто не
    дёргал, и записывать это время ему в счёт нечестно.
    """

    try:
        from backend.services.audit_service import log_action
        log_action(
            username="ACAI", role="assistant",
            action="case_escalated", target=f"case:{case_id}",
            details=reason
        )
    except Exception as error:
        print(f"[conversation_service] Не удалось записать эскалацию: {error}")


def generate_reply(case_id):
    """
    Формирует следующий ответ ИИ по текущему состоянию переписки.

    Возвращает dict:
        {"type": "answer",     "message": ..., "explanation": {...}, "step": n}
        {"type": "escalated",  "message": ...}
        {"type": "unavailable","message": ...}   — ИИ недоступен (нет квоты/сети)
    """

    case = get_case(case_id)

    if case is None:
        return {"type": "error", "message": "Обращение не найдено."}

    messages = get_messages(case_id)

    current_step = case.get("current_step") or 0

    # -----------------------------------------
    # Лимит шагов
    # -----------------------------------------

    if current_step >= MAX_AI_STEPS:

        return _escalate(case_id, case, messages, "исчерпаны шаги ИИ",
                        "Я предложил всё, что мог по этой неисправности.")

    # -----------------------------------------
    # Последнее сообщение рабочего
    # -----------------------------------------

    last_user_message = ""

    for item in reversed(messages):
        if item["role"] in ("worker", "specialist"):
            last_user_message = item["message"]
            break

    question = case.get("worker_question") or last_user_message

    # -----------------------------------------
    # 1. Инструкция завода — высший приоритет
    # -----------------------------------------

    tried = _tried_actions(messages)

    procedure = find_matching_procedure(case.get("equipment_id"), question)

    if procedure:

        remaining = [
            step["text"]
            for step in procedure["steps"]
            if step["text"] not in tried
        ]

        if remaining:

            set_step(case_id, current_step + 1)

            add_message(case_id, "assistant", remaining[0], author="ACAI")

            return {
                "type": "answer",
                "message": remaining[0],
                "step": current_step + 1,
                "explanation": {
                    "confidence": "Высокая",
                    "basis": [f"Инструкция завода: «{procedure['title']}»"]
                }
            }

    # -----------------------------------------
    # 2. Документация + база знаний -> ИИ
    # -----------------------------------------

    results = search_documents(
        machine=case.get("machine") or "",
        question=last_user_message or question,
        limit=5
    )

    filtered = filter_results(results)

    context_chunks = filtered.get("documents", [])
    doc_context = "\n\n".join(context_chunks[:3])

    hints = get_relevant_resolutions(case.get("machine") or "", question)

    # Всю переписку отдаём как часть проблемы — именно это делает
    # разговор разговором, а не серией независимых вопросов.
    dialogue = _dialogue_text(messages)

    full_question = (
        f"Исходная жалоба: {question}\n\n"
        f"Переписка:\n{dialogue}" if dialogue else question
    )

    suggestion = suggest_next_action(
        machine=case.get("machine") or "",
        question=full_question,
        doc_context=doc_context,
        tried_actions=tried,
        knowledge_hints=hints
    )

    # -----------------------------------------
    # 3. Нет ответа -> эскалация
    # -----------------------------------------

    if not suggestion:

        return _escalate(case_id, case, messages, "ИИ не нашёл решения",
                        "Не могу предложить надёжное решение по этой неисправности.")

    # -----------------------------------------
    # 4. Ответ
    # -----------------------------------------

    basis = []

    if hints:
        basis.append(f"{len(hints)} подтверждённых похожих случаев")

    if context_chunks:
        files = {
            item.get("file")
            for item in filtered.get("metadatas", [])[:3]
            if item.get("file")
        }
        basis.append("Документация: " + ", ".join(sorted(files)) if files else "Документация станка")

    if hints:
        confidence = "Высокая"
    elif context_chunks:
        confidence = "Средняя"
    else:
        confidence = "Низкая"
        basis.append("Общие знания ИИ — документации по этому станку не нашлось")

    set_step(case_id, current_step + 1)

    add_message(case_id, "assistant", suggestion, author="ACAI")

    return {
        "type": "answer",
        "message": suggestion,
        "step": current_step + 1,
        "explanation": {"confidence": confidence, "basis": basis}
    }


# =========================================================
# ВХОД: СООБЩЕНИЕ ОТ ЧЕЛОВЕКА
# =========================================================

def post_message(case_id, user, text):
    """
    Сообщение от человека в переписку.

    Если обращение ещё в фазе ИИ и пишет заявитель — ИИ сразу
    отвечает. Если обращение уже у специалиста — ИИ молчит, отвечают
    люди.
    """

    case = get_case(case_id)

    if case is None:
        return {"success": False, "message": "Обращение не найдено."}

    if case["status"] in (STATUS_CLOSED, STATUS_DRAFT_CLOSED):
        return {"success": False, "message": "Обращение закрыто, писать в него нельзя."}

    text = (text or "").strip()

    if not text:
        return {"success": False, "message": "Пустое сообщение."}

    is_specialist = user["role"] in SPECIALIST_ROLES

    add_message(
        case_id,
        "specialist" if is_specialist else "worker",
        text,
        author=user.get("full_name") or user.get("username"),
        author_role=user["role"]
    )

    # -----------------------------------------
    # Рабочий сказал, что заработало?
    # -----------------------------------------
    # Кнопку "Решено" мы у рабочего убрали: человек в перчатках у
    # станка не должен искать кнопки, он просто пишет "всё, крутится".
    # Понять это — работа ИИ.
    #
    # Проверяем на ЛЮБОЙ стадии, включая переданное специалисту:
    # если механик пришёл и починил, рабочий напишет об этом здесь же.

    if not is_specialist:

        messages = get_messages(case_id)

        if detect_resolution(case.get("machine") or "", _dialogue_text(messages)):

            # ИИ НЕ закрывает обращение сам — только спрашивает.
            #
            # Остановка станка и факт его исправности — вещь
            # производственная, а не разговорная. "Вроде пошло" и
            # "заработало" звучат похоже, но между ними смена. Если
            # ИИ ошибётся и закроет рано, простой обрежется задним
            # числом, статистика соврёт, а рабочий останется без
            # помощи. Поэтому решает человек, одним нажатием.

            add_message(
                case_id, "system",
                "Похоже, неисправность устранена. Станок работает?",
                author="ACAI"
            )

            return {
                "success": True,
                "reply": {"type": "confirm_resolution"},
                "messages": get_messages(case_id)
            }

    # ИИ предлагает следующий шаг, пока обращение не ушло специалисту
    # и пишет заявитель.
    if case["status"] == STATUS_OPEN and not is_specialist:

        reply = generate_reply(case_id)

        return {"success": True, "reply": reply, "messages": get_messages(case_id)}

    return {"success": True, "reply": None, "messages": get_messages(case_id)}


def _close_as_resolved(case_id, user):
    """Закрытие по словам рабочего — без кнопок."""

    messages = get_messages(case_id)

    last_advice = None

    for item in reversed(messages):
        if item["role"] in ("assistant", "specialist"):
            last_advice = item["message"]
            break

    add_message(
        case_id, "system",
        "Рабочий подтвердил, что станок работает. Обращение закрыто.",
        author="ACAI"
    )

    close_case_by_ai(case_id, resolution_comment=last_advice)

    try_auto_end_downtime_for_case(
        case_id,
        ended_by=user.get("full_name") or user.get("username")
    )

    return {
        "success": True,
        "reply": {"type": "resolved"},
        "messages": get_messages(case_id)
    }


# =========================================================
# "ПОМОГЛО"
# =========================================================

def resolve_by_worker(case_id, user):

    case = get_case(case_id)

    if case is None:
        return {"success": False, "message": "Обращение не найдено."}

    if case["status"] in (STATUS_CLOSED, STATUS_DRAFT_CLOSED):
        return {"success": False, "message": "Обращение уже закрыто."}

    messages = get_messages(case_id)

    last_advice = None

    for item in reversed(messages):
        if item["role"] in ("assistant", "specialist"):
            last_advice = item["message"]
            break

    add_message(
        case_id,
        "system",
        "Проблема решена, обращение закрыто.",
        author=user.get("full_name") or user.get("username"),
        author_role=user["role"]
    )

    close_case_by_ai(case_id, resolution_comment=last_advice)

    try_auto_end_downtime_for_case(case_id, ended_by=user.get("full_name") or user.get("username"))

    return {"success": True, "resolved": True, "messages": get_messages(case_id)}


# =========================================================
# СПИСОК ПЕРЕПИСОК ПОЛЬЗОВАТЕЛЯ
# =========================================================

def get_my_conversations(user, limit=20):
    """
    Для рабочего — его незакрытые обращения, чтобы вернуться в
    переписку, а не заводить новую по той же поломке.
    """

    conn = get_connection()

    rows = conn.execute(
        """
        SELECT
            cases.id,
            cases.machine,
            cases.symptom,
            cases.worker_question,
            cases.status,
            cases.created_at,
            cases.equipment_id,
            -- COALESCE: имя из справочника важнее текстового поля
            -- cases.machine. В нём у старых обращений лежит мусор
            -- вроде «undefined» — станок к тому моменту уже был,
            -- просто клиент не подставил название.
            COALESCE(equipment.name, cases.machine) AS equipment_name,
            (SELECT message FROM chat_history
              WHERE chat_history.case_id = cases.id
              ORDER BY chat_history.id DESC LIMIT 1) AS last_message,
            (SELECT created_at FROM chat_history
              WHERE chat_history.case_id = cases.id
              ORDER BY chat_history.id DESC LIMIT 1) AS last_at
        FROM cases
        LEFT JOIN equipment ON equipment.id = cases.equipment_id
        WHERE cases.status IN (?, ?, ?)
        ORDER BY cases.id DESC
        LIMIT ?
        """,
        (STATUS_OPEN, STATUS_ESCALATED, STATUS_IN_PROGRESS, limit)
    ).fetchall()

    conn.close()

    return [dict(row) for row in rows]

# =========================================================
# КАРТОЧКА ОБРАЩЕНИЯ — вся его жизнь на одном экране
# =========================================================

def get_case_card(case_id):
    """
    Полная история обращения: когда начато, сколько стоял станок,
    вся переписка, кто составил черновик закрытия и с каким
    комментарием, кто подтвердил и когда.

    Нужно заместителю директора (он подтверждает и должен видеть, что
    именно подтверждает) и директору (разбор задним числом: почему
    станок стоял четыре часа и что с ним делали).

    Ничего не удаляется и не переписывается — это и есть архив,
    к которому можно вернуться через месяц.
    """

    case = get_case(case_id)

    if case is None:
        return None

    conn = get_connection()

    equipment_name = None

    if case.get("equipment_id"):

        row = conn.execute(
            "SELECT name FROM equipment WHERE id = ?",
            (case["equipment_id"],)
        ).fetchone()

        if row:
            equipment_name = row["name"]

    # -----------------------------------------
    # Простои по этому обращению
    # -----------------------------------------

    downtimes = [
        dict(row)
        for row in conn.execute(
            """
            SELECT id, started_at, ended_at, duration_minutes,
                   started_by, ended_by, reason
            FROM downtime_log
            WHERE case_id = ?
            ORDER BY id
            """,
            (case_id,)
        ).fetchall()
    ]

    # -----------------------------------------
    # Записи журнала действий по этому обращению
    # -----------------------------------------

    audit = [
        dict(row)
        for row in conn.execute(
            """
            SELECT username, role, action, details, created_at
            FROM audit_log
            WHERE target = ?
            ORDER BY id
            """,
            (f"case:{case_id}",)
        ).fetchall()
    ]

    conn.close()

    total_downtime = sum(
        item["duration_minutes"] or 0
        for item in downtimes
    )

    # -----------------------------------------
    # Сколько заняло решение целиком
    # -----------------------------------------

    def parse(value):
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            return None

    opened = parse(case.get("created_at"))
    closed = parse(case.get("closed_at"))
    taken = parse(case.get("assigned_at"))
    drafted = parse(case.get("draft_closed_at"))

    # Момент, когда ИИ сдался и позвал человека
    escalated = None

    for item in audit:
        if item["action"] == "case_escalated":
            escalated = parse(item["created_at"])
            break

    if escalated is None:
        for item in get_messages(case_id):
            if item["role"] == "system" and "специалист" in (item["message"] or "").lower():
                escalated = parse(item["created_at"])
                break

    def minutes_between(start, end):
        if not start or not end:
            return None
        return max(round((end - start).total_seconds() / 60), 0)

    total_minutes = minutes_between(opened, closed)

    # Сколько специалист шёл. Считаем от момента, когда его позвали,
    # а не от создания обращения: пока ИИ вёл разбор, механика никто
    # не дёргал, и записывать это время ему в счёт нечестно.
    reaction_minutes = minutes_between(escalated or opened, taken)

    # Сколько занял сам ремонт — от взятия в работу до отчёта.
    repair_minutes = minutes_between(taken, drafted or closed)

    # Сколько ИИ разбирался сам, прежде чем позвать человека.
    ai_minutes = minutes_between(opened, escalated)

    return {
        "case": {
            **case,
            "equipment_name": equipment_name
        },
        "messages": get_messages(case_id),
        "downtimes": downtimes,
        "audit": audit,
        "totals": {
            "downtime_minutes": total_downtime,
            "resolution_minutes": total_minutes,
            "ai_minutes": ai_minutes,
            "reaction_minutes": reaction_minutes,
            "repair_minutes": repair_minutes,
            "messages_count": len(get_messages(case_id))
        },
        "timeline": {
            "opened_at": case.get("created_at"),
            "escalated_at": escalated.strftime("%Y-%m-%d %H:%M:%S") if escalated else None,
            "taken_at": case.get("assigned_at"),
            "taken_by": case.get("assigned_to"),
            "drafted_at": case.get("draft_closed_at"),
            "closed_at": case.get("closed_at")
        }
    }


# =========================================================
# СПИСКИ ПО РОЛЯМ
# =========================================================

# Кто подтверждает закрытие и видит черновики
APPROVER_ROLES = ("chief_engineer", "admin", "director")

# Роли, которые видят обращения ВСЕХ смен.
#
# Механик и электрик обслуживают весь завод и приходят в любую
# смену — им нужна полная картина, включая то, что было ночью.
# Администрация видит всё по определению.
#
# Начальник смены и оператор сюда НЕ входят: у смены свой архив.
# Начальник смены А разбирает свою смену и не лезет в чужую.
ALL_SHIFTS_ROLES = (
    "admin", "director", "chief_engineer", "engineer",
    "chief_mechanic", "mechanic",
    "chief_electrician", "electrician",
    "analyst"
)


def user_brigade(user):
    """Бригада пользователя или None, если он не привязан к смене."""

    if not user:
        return None

    if user.get("brigade"):
        return user["brigade"]

    # Подстраховка: в сессии бригады может не быть, читаем из базы.
    try:
        conn = get_connection()
        row = conn.execute(
            "SELECT brigade FROM users WHERE id = ?",
            (user.get("id"),)
        ).fetchone()
        conn.close()
        return row["brigade"] if row else None
    except Exception:
        return None


def sees_all_shifts(user) -> bool:
    return user and user.get("role") in ALL_SHIFTS_ROLES


def get_conversations(user, scope="active", limit=50, date_from=None, date_to=None):
    """
    scope:
        "active"    — открытые и переданные специалисту
        "approval"  — черновики закрытия, ждут заместителя директора
        "closed"    — архив

    Списки разные для разных ролей, но данные одни и те же —
    отдельных журналов не заводим.
    """

    if scope == "approval":
        statuses = (STATUS_DRAFT_CLOSED,)
    elif scope == "closed":
        statuses = (STATUS_CLOSED,)
    else:
        statuses = (STATUS_OPEN, STATUS_ESCALATED, STATUS_IN_PROGRESS)

    placeholders = ", ".join("?" for _ in statuses)

    params = list(statuses)

    extra = ""

    # Свой архив у каждой смены. Механики и администрация видят всё.
    if not sees_all_shifts(user):

        brigade = user_brigade(user)

        if brigade:
            extra += " AND cases.brigade = ?"
            params.append(brigade)
        else:
            # Бригада не проставлена — показываем только то, что
            # человек может открыть по своему оборудованию (фильтр
            # по станкам применяется выше, в роутере).
            pass

    if date_from:
        extra += " AND cases.created_at >= ?"
        params.append(f"{date_from} 00:00:00")

    if date_to:
        extra += " AND cases.created_at <= ?"
        params.append(f"{date_to} 23:59:59")

    params.append(limit)

    conn = get_connection()

    rows = conn.execute(
        f"""
        SELECT
            cases.id,
            cases.machine,
            cases.symptom,
            cases.worker_question,
            cases.status,
            cases.created_at,
            cases.closed_at,
            cases.equipment_id,
            cases.brigade,
            cases.shift,
            cases.draft_closed_by,
            cases.draft_resolution_comment,
            cases.draft_closed_at,
            cases.closed_by,
            cases.resolution_comment,
            -- COALESCE: имя из справочника важнее текстового поля
            -- cases.machine. В нём у старых обращений лежит мусор
            -- вроде «undefined» — станок к тому моменту уже был,
            -- просто клиент не подставил название.
            COALESCE(equipment.name, cases.machine) AS equipment_name,
            equipment.discipline AS equipment_discipline,
            (SELECT message FROM chat_history
              WHERE chat_history.case_id = cases.id
              ORDER BY chat_history.id DESC LIMIT 1) AS last_message,
            (SELECT created_at FROM chat_history
              WHERE chat_history.case_id = cases.id
              ORDER BY chat_history.id DESC LIMIT 1) AS last_at
        FROM cases
        LEFT JOIN equipment ON equipment.id = cases.equipment_id
        WHERE cases.status IN ({placeholders}) {extra}
        ORDER BY cases.created_at DESC, cases.id DESC
        LIMIT ?
        """,
        params
    ).fetchall()

    conn.close()

    return [dict(row) for row in rows]

def get_checked_summary(case_id):
    """
    Что по этой неисправности УЖЕ проверили.

    Нужно специалисту, который приходит на готовое: без этого он
    начинает диагностику с нуля и повторяет то, что рабочий сделал
    полчаса назад по подсказке ИИ. А если после механика придёт
    электрик — он повторит уже за механиком.

    Собирается из самой переписки, отдельно ничего заполнять не
    надо: предложение ИИ + что ответил на него человек.
    """

    messages = get_messages(case_id)

    checked = []

    for index, item in enumerate(messages):

        if item["role"] != "assistant":
            continue

        # Что ответили на это предложение
        outcome = None

        for following in messages[index + 1:]:

            if following["role"] in ("worker", "specialist"):
                outcome = following["message"]
                break

            if following["role"] == "assistant":
                break

        checked.append({
            "action": item["message"],
            "result": outcome,
            "by": "ACAI"
        })

    # Отдельно — что делали специалисты своими словами
    for item in messages:

        if item["role"] == "specialist":

            checked.append({
                "action": item["message"],
                "result": None,
                "by": item.get("author") or "Специалист"
            })

    return checked
