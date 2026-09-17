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

    try:
        notifications.extend(_backup_notifications(user))
    except Exception as error:
        print(f"[notification_service] Бэкап пропущен: {error}")

    try:
        notifications.extend(_sensor_notifications(user))
    except Exception as error:
        print(f"[notification_service] Датчики пропущены: {error}")

    # Сортируем ещё раз после добавления задач, ТО и бэкапа — раньше
    # сортировка шла до них, и просроченная задача оказывалась ниже
    # рядового напоминания.
    notifications.sort(key=lambda item: severity_order.get(item["severity"], 99))

    return notifications


# =========================================================
# БЭКАП НЕ ДЕЛАЕТСЯ
# =========================================================

# Ночная копия создаётся раз в сутки; даём запас на случай, если Mac
# спал и launchd досчитал запуск позже.
BACKUP_STALE_HOURS = 30


def _backup_notifications(user):
    """
    Предупреждение администратору, если свежей копии базы нет.

    Ночной бэкап однажды молча падал двое суток: скрипт перенесли, а
    launchd продолжал искать его по старому пути. Узнали случайно. Без
    напоминания такое повторится — никто не заглядывает в папку backups
    просто так.
    """
    from datetime import datetime
    from pathlib import Path

    from backend.config import BACKUPS_DIR, is_owner

    if user.get("role") != "admin" and not is_owner(user):
        return []

    backups = sorted(
        Path(BACKUPS_DIR).glob("factory_*.db"),
        key=lambda f: f.stat().st_mtime,
    )

    if not backups:
        return [{
            "type": "backup_missing",
            "severity": "critical",
            "icon": "💾",
            "title": "Резервных копий нет ни одной",
            "subtitle": "Проверьте задание com.acai.backup",
            "url": "/settings",
        }]

    age_hours = (datetime.now().timestamp() - backups[-1].stat().st_mtime) / 3600

    if age_hours < BACKUP_STALE_HOURS:
        return []

    return [{
        "type": "backup_missing",
        "severity": "critical",
        "icon": "💾",
        "title": f"Бэкап не делался {int(age_hours // 24)} сут {int(age_hours % 24)} ч",
        "subtitle": "Проверьте logs/backup.error.log",
        "url": "/settings",
    }]


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


def _plural(n, one, few, many):
    """1 работа, 2 работы, 5 работ — иначе в колокольчике «52 работ»."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


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

    if not by_equipment:
        return out

    # Одно уведомление на весь график, а не по штуке на станок. Было
    # 14 пунктов про ТО из 17 — просроченная поломка и подтверждение
    # закрытия тонули среди них, и колокольчик переставали открывать.
    # Подробности по станкам и так видны на странице графика.
    total = sum(i["overdue"] + i["due_now"] for i in by_equipment.values())
    overdue = sum(i["overdue"] for i in by_equipment.values())

    names = sorted(
        by_equipment.values(),
        key=lambda i: (-i["overdue"], -(i["overdue"] + i["due_now"]))
    )
    top = [i["equipment_name"] or "Оборудование" for i in names[:3]]
    rest = len(names) - len(top)
    subtitle = ", ".join(top) + (f" и ещё {rest}" if rest > 0 else "")

    if overdue:
        title = (f"ТО просрочено: {overdue} {_plural(overdue, 'работа', 'работы', 'работ')}, "
                 f"всего {total} на {len(names)} {_plural(len(names), 'станке', 'станках', 'станках')}")
        severity = "critical"
    else:
        title = (f"ТО в этом месяце: {total} {_plural(total, 'работа', 'работы', 'работ')} "
                 f"на {len(names)} {_plural(len(names), 'станке', 'станках', 'станках')}")
        severity = "warning"

    out.append({
        "type": "maintenance_due",
        "severity": severity,
        "icon": "🔧",
        "title": title,
        "subtitle": subtitle,
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
                   WHERE status NOT IN ('confirmed', 'cancelled')
                     AND due_at IS NOT NULL AND due_at != ''
                   ORDER BY due_at
                   LIMIT 50"""
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT DISTINCT t.id, t.title, t.due_at, t.priority, t.status
                   FROM tasks t
                   LEFT JOIN task_assignees ta ON ta.task_id = t.id
                   WHERE t.status NOT IN ('confirmed', 'cancelled')
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


# =========================================================
# СБОР ПОКАЗАНИЙ ОСТАНОВИЛСЯ
# =========================================================

SENSOR_ALERT_ROLES = ("admin", "chief_engineer", "chief_electrician")


def _sensor_notifications(user):
    """
    Сбор показаний держится на вкладке WebHMI в браузере сервера. Её
    закрывают, Chrome её усыпляет, панель разлогинивается — и история
    молча пустеет: 17.09 с 9:36 до 10:59 не записалось ничего. Жёлтую
    плашку на главной видно, только если туда зайти.
    """
    from datetime import datetime

    from sqlalchemy import func

    from backend import models
    from backend.config import is_owner
    from backend.database import SessionLocal
    from backend.services.sensor_recorder import STALE_ALERT_MIN

    if user.get("role") not in SENSOR_ALERT_ROLES and not is_owner(user):
        return []

    db = SessionLocal()
    try:
        last = db.query(func.max(models.SensorReading.recorded_at)).scalar()
    finally:
        db.close()

    if last is None:
        return []

    minutes = int((datetime.now() - last).total_seconds() // 60)

    if minutes < STALE_ALERT_MIN:
        return []

    when = f"{minutes // 60} ч {minutes % 60} мин" if minutes >= 60 else f"{minutes} мин"

    return [{
        "type": "sensors_stale",
        "severity": "critical" if minutes >= 60 else "warning",
        "icon": "📡",
        "title": f"Показания датчиков не пишутся {when}",
        "subtitle": "Откройте вкладку WebHMI на сервере и войдите в панель",
        "url": "/settings",
    }]
