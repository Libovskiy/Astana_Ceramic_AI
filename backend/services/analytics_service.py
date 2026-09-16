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
