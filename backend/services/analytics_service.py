"""
Аналитика — агрегация того, что уже есть (простои, повторяющиеся
неисправности, частые симптомы), плюс новое: производительность за
период (сегодня/неделя/месяц) и простои по дисциплине за период.

"Вывод ACAI" — НЕ текст, сгенерированный ИИ, а честная фраза на
основе реально посчитанных данных (станок с наибольшим простоем за
период). Никаких выдуманных процентов эффективности.
"""

import sqlite3
from datetime import datetime, timedelta

from backend.config import DB_NAME
from backend.services.production_log_service import get_daily_target_by_type, BRICK_TYPES


def get_connection():

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row

    return conn


def get_performance_trend():
    """
    % выполнения плана — сегодня / за 7 дней / за 30 дней.
    План на период = дневной план × количество дней периода
    (тот же дневной план, что используется в остальной системе —
    единая логика, не отдельная формула для аналитики).
    """

    conn = get_connection()
    cursor = conn.cursor()

    daily_targets = get_daily_target_by_type()
    daily_total_target = sum(daily_targets.values())

    periods = {"today": 1, "week": 7, "month": 30}

    result = {}

    for period_name, days in periods.items():

        date_from = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")

        cursor.execute(
            "SELECT COALESCE(SUM(pieces), 0) FROM shift_production_log WHERE log_date >= ?",
            (date_from,)
        )

        produced = cursor.fetchone()[0]

        target = daily_total_target * days

        percent = round((produced / target) * 100) if target else 0

        result[period_name] = {
            "produced": produced,
            "target": target,
            "percent": percent
        }

    conn.close()

    return result


# Дольше смены — почти наверняка забыли закрыть обращение, а не
# оборудование правда стоит двенадцать часов подряд. Не прячем такие
# простои и не обрезаем: помечаем, чтобы человек проверил.
STALE_DOWNTIME_MINUTES = 12 * 60


def get_downtime_by_period(days=7):
    """
    Простои за период — общая сумма + разбивка по дисциплине
    (механика/электрика/остальное). "Остальное" — простои станков
    без указанной дисциплины (например единственная незаполненная
    "Упаковочная линия" — дубликат, ещё не размечен).
    """

    conn = get_connection()
    cursor = conn.cursor()

    date_from = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")

    cursor.execute(
        """
        SELECT
            downtime_log.duration_minutes,
            downtime_log.started_at,
            downtime_log.ended_at,
            downtime_log.equipment_id,
            equipment.name AS equipment_name,
            equipment.discipline AS equipment_discipline
        FROM downtime_log
        LEFT JOIN equipment ON equipment.id = downtime_log.equipment_id
        WHERE downtime_log.started_at >= ?
        """,
        (date_from,)
    )

    rows = cursor.fetchall()

    conn.close()

    now = datetime.now()

    by_discipline = {"mechanical": 0, "electrical": 0, "other": 0}
    per_equipment = {}
    total_minutes = 0
    closed_minutes = 0
    open_minutes = 0
    open_count = 0
    stale = []

    for row in rows:

        is_open = row["duration_minutes"] is None

        if not is_open:
            minutes = row["duration_minutes"]
            closed_minutes += minutes
        else:
            # Ещё идёт — считаем прошедшее время "на лету".
            #
            # Простой закрывается только вместе с обращением, поэтому
            # забытое обращение тикает бесконечно: открыли в пятницу
            # вечером — в понедельник в отчёте трое суток простоя.
            # Число само по себе не врёт (оборудование правда числится
            # стоящим), но смешивать его с измеренными простоями
            # нельзя: директор должен видеть, что это НЕЗАКРЫТАЯ
            # запись, а не подтверждённый факт.
            started_at = datetime.strptime(row["started_at"], "%Y-%m-%d %H:%M:%S")
            minutes = max(round((now - started_at).total_seconds() / 60), 0)
            open_minutes += minutes
            open_count += 1

            if minutes >= STALE_DOWNTIME_MINUTES:
                stale.append({
                    "equipment_name": row["equipment_name"] or f"Оборудование #{row['equipment_id']}",
                    "started_at": row["started_at"],
                    "minutes": minutes,
                })

        total_minutes += minutes

        equipment_id = row["equipment_id"]
        if equipment_id is not None:
            bucket = per_equipment.setdefault(
                equipment_id,
                {"name": row["equipment_name"] or f"Оборудование #{equipment_id}",
                 "minutes": 0, "count": 0},
            )
            bucket["minutes"] += minutes
            bucket["count"] += 1

        discipline = row["equipment_discipline"]

        if discipline in ("mechanical", "both"):
            by_discipline["mechanical"] += minutes
        elif discipline == "electrical":
            by_discipline["electrical"] += minutes
        else:
            by_discipline["other"] += minutes

    # Разбивка по станкам — фронтенд показывает её в блоке
    # «Простои по оборудованию» и ждёт incidents_count у каждого.
    by_equipment = []

    for equipment_id, data in per_equipment.items():
        by_equipment.append({
            "equipment_id": equipment_id,
            "equipment_name": data["name"],
            "total_minutes": round(data["minutes"]),
            "incidents_count": data["count"],
        })

    by_equipment.sort(key=lambda item: item["total_minutes"], reverse=True)

    stale.sort(key=lambda item: item["minutes"], reverse=True)

    return {
        "total_minutes": total_minutes,
        # Измеренные простои: начало и конец проставлены человеком.
        "closed_minutes": closed_minutes,
        # Ещё идут. Показывать отдельно, иначе незакрытая запись
        # выглядит как подтверждённая потеря времени.
        "open_minutes": open_minutes,
        "open_count": open_count,
        # Идут дольше смены — скорее всего, забыли закрыть обращение.
        "stale": stale,
        # Инцидент — одна запись простоя, а не обращение: рядом с часами
        # должно стоять число случаев, из которых эти часы сложились.
        "incidents_count": len(rows),
        "by_discipline": by_discipline,
        "by_equipment": by_equipment,
    }


def get_biggest_loss_summary(days=7):
    """
    "Вывод" — честная фраза на основе реальных данных: какой станок
    потерял больше всего времени за период. Если данных нет —
    возвращает None, фронтенд не должен ничего выдумывать в этом
    случае.
    """

    conn = get_connection()
    cursor = conn.cursor()

    date_from = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")

    cursor.execute(
        """
        SELECT
            equipment.name AS equipment_name,
            SUM(COALESCE(
                downtime_log.duration_minutes,
                (julianday('now') - julianday(downtime_log.started_at)) * 24 * 60
            )) AS total_minutes
        FROM downtime_log
        LEFT JOIN equipment ON equipment.id = downtime_log.equipment_id
        WHERE downtime_log.started_at >= ? AND downtime_log.equipment_id IS NOT NULL
        GROUP BY downtime_log.equipment_id
        ORDER BY total_minutes DESC
        LIMIT 1
        """,
        (date_from,)
    )

    row = cursor.fetchone()

    conn.close()

    if not row or not row["total_minutes"]:
        return None

    return {
        "equipment_name": row["equipment_name"],
        "minutes": round(row["total_minutes"])
    }


# =========================================================
# ГРАФИК ТО: ЧТО ПОЛОЖЕНО И ЧТО СДЕЛАНО
# =========================================================

def get_maintenance_summary():
    """
    Выполнение графика ТО с начала месяца.

    Считаем ТОЛЬКО с того месяца, в котором график завели в систему.
    До этого ТО могли делать по бумаге — записывать их в просрочку
    значило бы обвинить механиков в том, чего система не видела.
    Дата начала подписывается на экране, чтобы цифра не выглядела
    итогом за весь год.

    Работа считается выполненной, если по ней есть запись в
    maintenance_log за этот год и месяц.
    """

    conn = get_connection()
    cursor = conn.cursor()

    today = datetime.now()
    year, month = today.year, today.month

    started = cursor.execute(
        "SELECT MIN(created_at) FROM maintenance_schedule WHERE year = ?", (year,)
    ).fetchone()[0]

    rows = cursor.execute(
        "SELECT id, work_name, months, responsible, equipment_id FROM maintenance_schedule WHERE year = ?",
        (year,)
    ).fetchall()

    done_ids = {
        row["schedule_id"]
        for row in cursor.execute(
            "SELECT schedule_id FROM maintenance_log WHERE year = ? AND month = ?",
            (year, month)
        ).fetchall()
        if row["schedule_id"] is not None
    }

    conn.close()

    due = []

    for row in rows:
        months = {m.strip() for m in str(row["months"] or "").split(",") if m.strip().isdigit()}
        if str(month) in months:
            due.append(row)

    by_responsible = {}

    for row in due:
        who = row["responsible"] or "не назначен"
        slot = by_responsible.setdefault(who, {"responsible": who, "due": 0, "done": 0})
        slot["due"] += 1
        if row["id"] in done_ids:
            slot["done"] += 1

    done_count = sum(1 for row in due if row["id"] in done_ids)

    overdue = [
        {"work_name": row["work_name"], "responsible": row["responsible"] or "не назначен"}
        for row in due if row["id"] not in done_ids
    ]

    return {
        "year": year,
        "month": month,
        "schedule_started_at": started,
        "due": len(due),
        "done": done_count,
        "overdue": len(overdue),
        "percent": round(done_count * 100 / len(due)) if due else None,
        "by_responsible": sorted(by_responsible.values(), key=lambda s: -s["due"]),
        "overdue_examples": overdue[:6],
    }


# =========================================================
# ОБХОДЫ СМЕНЫ
# =========================================================

def get_checklist_summary(days=7):
    """
    Обходы за период: сколько прошло, сколько замечаний и на каком
    оборудовании они повторяются.

    Повторяющееся замечание важнее единичного: если один и тот же
    узел всплывает в каждом обходе, это не случайность, а место,
    куда нужно идти с ремонтом.
    """

    conn = get_connection()
    cursor = conn.cursor()

    date_from = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")

    rounds = cursor.execute(
        """
        SELECT id, started_at, finished_at, full_name, shift,
               total_count, ok_count, warn_count, bad_count
        FROM checklist_rounds
        WHERE started_at >= ?
        ORDER BY started_at DESC
        """,
        (date_from,)
    ).fetchall()

    problems = cursor.execute(
        """
        SELECT e.name AS equipment_name, i.status, COUNT(*) AS times
        FROM checklist_items i
        JOIN checklist_rounds r ON r.id = i.round_id
        LEFT JOIN equipment e ON e.id = i.equipment_id
        WHERE r.started_at >= ? AND i.status IN ('bad', 'warn')
        GROUP BY e.name, i.status
        ORDER BY times DESC
        """,
        (date_from,)
    ).fetchall()

    conn.close()

    rounds_list = [dict(r) for r in rounds]

    by_equipment = {}

    for row in problems:
        name = row["equipment_name"] or "не указано"
        slot = by_equipment.setdefault(name, {"equipment_name": name, "bad": 0, "warn": 0})
        slot[row["status"]] = row["times"]

    top = sorted(
        by_equipment.values(),
        key=lambda s: (s["bad"], s["warn"]),
        reverse=True
    )

    return {
        "rounds_count": len(rounds_list),
        "checks_total": sum(r["total_count"] or 0 for r in rounds_list),
        "bad_total": sum(r["bad_count"] or 0 for r in rounds_list),
        "warn_total": sum(r["warn_count"] or 0 for r in rounds_list),
        "last_round": rounds_list[0] if rounds_list else None,
        "top_problems": top[:6],
    }
