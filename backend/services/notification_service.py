"""
Уведомления внутри системы — не отдельная база данных, а агрегация
того, что уже есть: активные простои дольше порога, эскалированные
обращения, черновики закрытия в ожидании подтверждения гл. инженера,
повторяющиеся неисправности.

Никаких email/Telegram — только внутри интерфейса (колокольчик в
шапке), это осознанно первый этап, как и предлагалось.

Учитывает роль пользователя (фильтрует по дисциплине/своему
оборудованию) и даёт точную ссылку на конкретную проблему, а не
на общую страницу.
"""

from backend.services.downtime_service import get_active_downtimes
from backend.services.case_service import search_case_events, get_recurring_issues
from backend.services.auth_service import get_assigned_equipment_ids


DOWNTIME_ALERT_THRESHOLD_MINUTES = 20


def _passes_role_filter(
    role,
    equipment_id,
    discipline,
    assigned_equipment_ids,
    required_discipline=None,
    case_brigade=None,
    user_brigade=None
):
    """
    Кого это уведомление реально касается.

    Раньше механик и электрик получали всё по станкам с
    дисциплиной "both" — а таких у вас десять, включая упаковочную
    машину и оба робота FANUC. В итоге электрик видел заклинивший
    подшипник, а механик — не сработавший датчик. Оба привыкали, что
    половина сигналов не про них, и переставали смотреть вообще.
    Худшее, что может случиться с уведомлениями.

    Теперь главный признак — что решил ИИ при передаче
    (required_discipline). Дисциплина станка остаётся запасным
    вариантом, когда ИИ не смог определить.

    Начальник смены и оператор получают только СВОЮ смену: чужая
    смена — не их забота и не их ответственность.
    """

    # -----------------------------------------
    # Своя смена
    # -----------------------------------------

    if role in ("worker", "shift_supervisor"):

        if user_brigade and case_brigade and case_brigade != user_brigade:
            return False

    if role == "worker":
        return equipment_id in assigned_equipment_ids

    # -----------------------------------------
    # Механика / электрика
    # -----------------------------------------

    if role in ("mechanic", "chief_mechanic"):

        if required_discipline:
            return required_discipline == "mechanical"

        return discipline in ("mechanical", "both")

    if role in ("electrician", "chief_electrician"):

        if required_discipline:
            return required_discipline == "electrical"

        return discipline in ("electrical", "both")

    return True


def get_notifications(user):

    role = user["role"]
    brigade = user.get("brigade")

    assigned_equipment_ids = (
        set(get_assigned_equipment_ids(user["id"]))
        if role == "worker"
        else set()
    )

    notifications = []

    # -----------------------------------------
    # 1. Долгие простои — ссылка сразу на паспорт станка
    # -----------------------------------------

    for downtime in get_active_downtimes():

        if downtime["duration_minutes"] < DOWNTIME_ALERT_THRESHOLD_MINUTES:
            continue

        if not _passes_role_filter(
            role,
            downtime["equipment_id"],
            downtime.get("equipment_discipline"),
            assigned_equipment_ids,
            user_brigade=brigade
        ):
            continue

        notifications.append({
            "type": "downtime",
            "severity": "critical",
            "icon": "🔴",
            "title": f"Простой {downtime['duration_minutes']} мин",
            "subtitle": downtime.get("equipment_name") or "Оборудование",
            "url": f"/equipment?open={downtime['equipment_id']}" if downtime.get("equipment_id") else "/production"
        })

    # -----------------------------------------
    # 2. Эскалированные обращения (нужен специалист)
    # -----------------------------------------

    escalated_cases = search_case_events(status="Требует специалиста", limit=20)

    for case in escalated_cases:

        equipment_id = case.get("equipment_id")

        if not _passes_role_filter(
            role, equipment_id, case.get("equipment_discipline"), assigned_equipment_ids,
            required_discipline=case.get("required_discipline"),
            case_brigade=case.get("brigade"),
            user_brigade=brigade
        ):
            continue

        notifications.append({
            "type": "escalated_case",
            "severity": "critical",
            "icon": "🔴",
            "title": (
                "Нужна электрика" if case.get("required_discipline") == "electrical"
                else "Нужна механика" if case.get("required_discipline") == "mechanical"
                else "Требует специалиста"
            ),
            "subtitle": case.get("equipment_name") or case.get("machine") or "Оборудование",
            "url": f"/equipment?open={equipment_id}" if equipment_id else "/events"
        })

    # -----------------------------------------
    # 3. Черновики закрытия — ждут подтверждения гл. инженера
    #    (видно только тем, кто реально может подтверждать —
    #    руководству, не рядовым специалистам/операторам)
    # -----------------------------------------

    if role in ("admin", "director", "chief_engineer"):

        draft_cases = search_case_events(status="Черновик закрытия", limit=20)

        for case in draft_cases:

            equipment_id = case.get("equipment_id")

            if role == "shift_supervisor" and brigade and case.get("brigade") != brigade:
                continue

            notifications.append({
                "type": "pending_confirmation",
                "severity": "info",
                "icon": "📋",
                "title": "Ожидает подтверждения",
                "subtitle": case.get("equipment_name") or case.get("machine") or "Обращение",
                "url": f"/equipment?open={equipment_id}" if equipment_id else "/events"
            })

    # -----------------------------------------
    # 4. Повторяющиеся неисправности
    # -----------------------------------------

    for issue in get_recurring_issues(limit=5):

        equipment_id = issue.get("equipment_id")

        if not _passes_role_filter(
            role, equipment_id, issue.get("equipment_discipline"), assigned_equipment_ids,
            user_brigade=brigade
        ):
            continue

        notifications.append({
            "type": "recurring_issue",
            "severity": "warning",
            "icon": "⚠️",
            "title": f"Повторяющаяся неисправность ({issue['count']} раз за 14 дней)",
            "subtitle": issue.get("equipment_name") or "Оборудование",
            "url": f"/equipment?open={equipment_id}" if equipment_id else "/"
        })

    # Критичные сначала
    severity_order = {"critical": 0, "warning": 1, "info": 2}

    notifications.sort(key=lambda item: severity_order.get(item["severity"], 99))

    # Задачи с истёкшим сроком: без напоминания о них вспоминают,
    # только когда спросят.
    try:
        notifications.extend(_task_notifications(user))
    except Exception as error:
        print(f"[notification_service] Задачи пропущены: {error}")

    # ТО раз в месяц/квартал и т.д. — без напоминания про него
    # вспоминают, только когда посмотрят график сами, а туда никто
    # не заходит без повода. Колокольчик — единственный повод.
    try:
        notifications.extend(_maintenance_notifications(user))
    except Exception as error:
        print(f"[notification_service] ТО пропущено: {error}")

    return notifications


# =========================================================
# ТО: ПРОСРОЧЕННОЕ И НА ЭТОТ МЕСЯЦ
# =========================================================

MAINTENANCE_NOTIFY_ROLES = {
    "admin", "director", "chief_engineer",
    "chief_mechanic", "chief_electrician", "engineer",
}


def _maintenance_start():
    """
    Месяц, с которого график ТО считается действующим — тот же смысл,
    что и в backend/api/maintenance_summary_routes.py: до этого месяца
    работы внесли задним числом, просрочкой это не считается.
    """
    import os

    raw = (os.environ.get("ACAI_MAINTENANCE_START") or "").strip()

    if not raw:
        from pathlib import Path
        from backend.config import BASE_DIR

        env_file = Path(BASE_DIR) / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("ACAI_MAINTENANCE_START="):
                    raw = line.split("=", 1)[1].strip()
                    break

    try:
        year_str, month_str = raw.split("-")[:2]
        return int(year_str), int(month_str)
    except Exception:
        return None, None


def _maintenance_notifications(user):
    """
    Работы по графику ТО, срок которых наступил (этот месяц) или прошёл,
    а отметки о выполнении в maintenance_log ещё нет. Один пункт на
    станок с числом работ — иначе колокольчик разбухает: работ в
    графике десятки на каждый станок.
    """
    import sqlite3
    from datetime import datetime

    from backend.config import DB_NAME

    role = user.get("role")
    if role not in MAINTENANCE_NOTIFY_ROLES:
        return []

    now = datetime.now()
    year, month_now = now.year, now.month
    start_year, start_month = _maintenance_start()

    out = []
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        conn.row_factory = sqlite3.Row
    except Exception:
        return out

    try:
        schedule = conn.execute(
            """SELECT s.id, s.equipment_id, s.work_name, s.months,
                      e.name AS equipment_name, e.discipline
               FROM maintenance_schedule s
               LEFT JOIN equipment e ON e.id = s.equipment_id
               WHERE s.year = ?""",
            (year,),
        ).fetchall()
        done = {
            (row["schedule_id"], row["month"])
            for row in conn.execute(
                "SELECT schedule_id, month FROM maintenance_log WHERE year = ?",
                (year,),
            ).fetchall()
        }
    except sqlite3.OperationalError:
        # графика ТО в базе ещё нет — не ломаем колокольчик
        return out
    finally:
        conn.close()

    by_equipment: dict[int, dict] = {}

    for row in schedule:

        if role in ("chief_mechanic",) and row["discipline"] not in ("mechanical", "both", None):
            continue
        if role in ("chief_electrician",) and row["discipline"] not in ("electrical", "both", None):
            continue

        for part in str(row["months"] or "").split(","):
            part = part.strip()
            if not part.isdigit():
                continue
            m = int(part)
            if not (1 <= m <= month_now):
                continue

            before_start = bool(start_year) and (
                year < start_year or (year == start_year and m < start_month)
            )
            if before_start:
                continue

            if (row["id"], m) in done:
                continue

            eq_id = row["equipment_id"]
            bucket = by_equipment.setdefault(eq_id, {
                "equipment_name": row["equipment_name"],
                "overdue": 0,
                "due_now": 0,
            })

            if m < month_now:
                bucket["overdue"] += 1
            else:
                bucket["due_now"] += 1

    for eq_id, info in by_equipment.items():

        total = info["overdue"] + info["due_now"]
        overdue = info["overdue"]

        if overdue:
            title = f"ТО просрочено: {overdue} из {total}"
            severity = "critical"
        else:
            title = f"ТО в этом месяце: {total}"
            severity = "warning"

        out.append({
            "type": "maintenance_due",
            "severity": severity,
            "icon": "🔧",
            "title": title,
            "subtitle": info["equipment_name"] or "Оборудование",
            "url": "/maintenance",
        })

    return out


# =========================================================
# ЗАДАЧИ: ПРОСРОЧЕННЫЕ И С СЕГОДНЯШНИМ СРОКОМ
# =========================================================

def _task_notifications(user):
    """
    Задачи, о которых стоит напомнить.

    Руководитель видит все задачи участка, остальные — только свои:
    назначенные на них или созданные ими. Иначе колокольчик мастера
    забьётся чужими делами и его перестанут открывать.
    """
    import sqlite3
    from datetime import datetime

    from backend.config import DB_NAME

    MANAGER_ROLES = {
        "admin", "director", "chief_engineer",
        "chief_mechanic", "chief_electrician", "shift_supervisor",
    }

    role = user.get("role")
    user_id = user.get("id")
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    out = []

    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        conn.row_factory = sqlite3.Row
    except Exception:
        return out

    try:
        if role in MANAGER_ROLES:
            rows = conn.execute(
                """SELECT id, title, due_at, priority, status
                   FROM tasks
                   WHERE status NOT IN ('done', 'cancelled')
                     AND due_at IS NOT NULL AND due_at != ''
                   ORDER BY due_at
                   LIMIT 50"""
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT DISTINCT t.id, t.title, t.due_at, t.priority, t.status
                   FROM tasks t
                   LEFT JOIN task_assignees ta ON ta.task_id = t.id
                   WHERE t.status NOT IN ('done', 'cancelled')
                     AND t.due_at IS NOT NULL AND t.due_at != ''
                     AND (ta.user_id = ? OR t.created_by = ?)
                   ORDER BY t.due_at
                   LIMIT 50""",
                (user_id, user_id),
            ).fetchall()
    except sqlite3.OperationalError:
        # таблицы задач ещё нет — не ломаем колокольчик
        conn.close()
        return out
    finally:
        try:
            conn.close()
        except Exception:
            pass

    for row in rows:
        due = (row["due_at"] or "")[:10]
        if not due:
            continue

        if due < today:
            try:
                days = (now - datetime.strptime(due, "%Y-%m-%d")).days
            except ValueError:
                days = 0

            out.append({
                "type": "task_overdue",
                "severity": "critical" if days > 3 else "warning",
                "title": f"Просрочена: {row['title']}",
                "message": f"Срок был {days} дн. назад" if days else "Срок прошёл",
                "link": "/events",
                "task_id": row["id"],
            })

        elif due == today:
            out.append({
                "type": "task_today",
                "severity": "info",
                "title": f"Срок сегодня: {row['title']}",
                "message": "Задача не закрыта",
                "link": "/events",
                "task_id": row["id"],
            })

    return out
