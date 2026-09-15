"""
Учёт выпуска продукции — начальник смены вводит количество
поддонов по каждому виду кирпича, система сама переводит в штуки
и сравнивает с планом.

Логика плана (согласована с пользователем):
    месячный план (шт, по каждому виду) → делим на количество
    дней в текущем месяце → план на сутки → делим пополам на
    день/ночь → план на смену.

BRICK_TYPES — сколько штук на одном поддоне у каждого вида.
Меняется редко, поэтому пока константа в коде, а не таблица в БД —
проще менять напрямую здесь, если появится новый вид продукции.
"""

import sqlite3
import calendar
from datetime import datetime

from backend.config import DB_NAME


BRICK_TYPES = {
    "полнотелый": 396,
    "пустотелый": 440,
    "блок": 60
}


def get_connection():

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row

    return conn


def init_production_tables():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS production_plan (
            brick_type TEXT PRIMARY KEY,
            monthly_target INTEGER NOT NULL,
            updated_by TEXT,
            updated_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS shift_production_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_date TEXT NOT NULL,
            shift TEXT NOT NULL,
            brick_type TEXT NOT NULL,
            pallets INTEGER NOT NULL,
            pieces INTEGER NOT NULL,
            entered_by TEXT,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def check_plan_anomaly(brick_type, new_target):
    """
    Проверка нового месячного плана перед сохранением — не блокирует
    жёстко (пользователь может действительно менять план), но
    предупреждает при подозрительном отклонении. Защита от
    случайного лишнего нуля при вводе.

    Пороги:
    - new_target == 0 → критично (пустой план почти всегда ошибка)
    - изменение >= 400% (в 5 раз) от предыдущего → критично
    - изменение >= 100% (в 2 раза) → предупреждение
    - если плана раньше не было (previous == 0) → не с чем сравнивать,
      пропускаем проверку отклонения (но проверка на 0 всё равно есть)
    """

    if new_target == 0:

        return {
            "severity": "critical",
            "message": "План равен нулю — вероятно, ошибка ввода.",
            "previous_target": None,
            "change_percent": None
        }

    plans = get_monthly_plans()
    previous_target = plans.get(brick_type, 0)

    if previous_target == 0:

        return {
            "severity": "ok",
            "message": None,
            "previous_target": None,
            "change_percent": None
        }

    change_percent = round(
        ((new_target - previous_target) / previous_target) * 100
    )

    if abs(change_percent) >= 400:

        return {
            "severity": "critical",
            "message": (
                f"План отличается от предыдущего на {change_percent:+d}% "
                f"(было {previous_target}, стало {new_target}). "
                f"Похоже на ошибку ввода (лишний ноль?)."
            ),
            "previous_target": previous_target,
            "change_percent": change_percent
        }

    if abs(change_percent) >= 100:

        return {
            "severity": "warning",
            "message": (
                f"План отличается от предыдущего на {change_percent:+d}% "
                f"(было {previous_target}, стало {new_target}). Проверьте значение."
            ),
            "previous_target": previous_target,
            "change_percent": change_percent
        }

    return {
        "severity": "ok",
        "message": None,
        "previous_target": previous_target,
        "change_percent": change_percent
    }


def set_monthly_plan(brick_type, monthly_target, updated_by):

    if brick_type not in BRICK_TYPES:
        raise ValueError(f"Неизвестный вид кирпича: {brick_type}")

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO production_plan (brick_type, monthly_target, updated_by, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(brick_type) DO UPDATE SET
            monthly_target = excluded.monthly_target,
            updated_by = excluded.updated_by,
            updated_at = excluded.updated_at
        """,
        (
            brick_type,
            monthly_target,
            updated_by,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
    )

    conn.commit()
    conn.close()


def get_monthly_plans():
    """Возвращает план по всем видам — 0, если ещё не задан."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM production_plan")

    rows = {row["brick_type"]: dict(row) for row in cursor.fetchall()}

    conn.close()

    result = {}

    for brick_type in BRICK_TYPES:

        if brick_type in rows:
            result[brick_type] = rows[brick_type]["monthly_target"]
        else:
            result[brick_type] = 0

    return result


def get_daily_target(reference_date=None):
    """Сумма по всем видам месячного плана, делённая на число дней
    в месяце — план на сутки, в штуках. Общий итог (используется
    как дополнительная сводка) — по каждому виду отдельно теперь
    есть get_daily_target_by_type()."""

    reference_date = reference_date or datetime.now()

    days_in_month = calendar.monthrange(
        reference_date.year,
        reference_date.month
    )[1]

    plans = get_monthly_plans()

    total_monthly = sum(plans.values())

    if days_in_month == 0:
        return 0

    return round(total_monthly / days_in_month)


def get_daily_target_by_type(reference_date=None):
    """План на сутки ОТДЕЛЬНО по каждому виду продукции — это
    основная детализация, общий get_daily_target() выше остаётся
    только как дополнительный итог по заводу."""

    reference_date = reference_date or datetime.now()

    days_in_month = calendar.monthrange(
        reference_date.year,
        reference_date.month
    )[1]

    plans = get_monthly_plans()

    if days_in_month == 0:
        return {brick_type: 0 for brick_type in BRICK_TYPES}

    return {
        brick_type: round(monthly_target / days_in_month)
        for brick_type, monthly_target in plans.items()
    }


def get_shift_target(reference_date=None):
    """План на одну смену — сутки делим пополам (день/ночь)."""

    return round(get_daily_target(reference_date) / 2)


def get_shift_target_by_type(reference_date=None):
    """План на смену отдельно по каждому виду продукции."""

    daily_by_type = get_daily_target_by_type(reference_date)

    return {
        brick_type: round(target / 2)
        for brick_type, target in daily_by_type.items()
    }


def log_shift_production(log_date, shift, brick_type, pallets, entered_by):

    if brick_type not in BRICK_TYPES:
        raise ValueError(f"Неизвестный вид кирпича: {brick_type}")

    if pallets <= 0:
        raise ValueError("Количество поддонов должно быть больше нуля.")

    pieces = pallets * BRICK_TYPES[brick_type]

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO shift_production_log
            (log_date, shift, brick_type, pallets, pieces, entered_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            log_date,
            shift,
            brick_type,
            pallets,
            pieces,
            entered_by,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
    )

    conn.commit()
    conn.close()

    return pieces


def get_today_production():
    """
    Факт за сегодня — ОТДЕЛЬНО по каждому виду продукции (это
    основное), плюс общий итог по заводу как дополнительная сводка.
    """

    today = datetime.now().strftime("%Y-%m-%d")

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT brick_type, COALESCE(SUM(pieces), 0) AS produced
        FROM shift_production_log
        WHERE log_date = ?
        GROUP BY brick_type
        """,
        (today,)
    )

    produced_by_type_raw = {row["brick_type"]: row["produced"] for row in cursor.fetchall()}

    conn.close()

    daily_targets = get_daily_target_by_type()

    by_type = {}

    for brick_type in BRICK_TYPES:

        produced = produced_by_type_raw.get(brick_type, 0)
        target = daily_targets.get(brick_type, 0)

        by_type[brick_type] = {
            "produced": produced,
            "target": target,
            "percent": round((produced / target) * 100) if target else 0
        }

    total_produced = sum(item["produced"] for item in by_type.values())
    total_target = sum(item["target"] for item in by_type.values())

    total_percent = round((total_produced / total_target) * 100) if total_target else 0

    return {
        "by_type": by_type,
        "produced": total_produced,
        "target": total_target,
        "percent": total_percent
    }


def get_shift_history(date_from=None, date_to=None):
    """
    Для сравнения смен между собой — сгруппировано по дате+смене,
    с итогом в штуках и % от плана на смену. Используется для
    выявления, какая смена регулярно отстаёт, и для среднего
    значения выполнения.
    """

    conn = get_connection()
    cursor = conn.cursor()

    query = """
        SELECT
            log_date,
            shift,
            SUM(pieces) AS total_pieces
        FROM shift_production_log
        WHERE 1 = 1
    """

    params = []

    if date_from:
        query += " AND log_date >= ?"
        params.append(date_from)

    if date_to:
        query += " AND log_date <= ?"
        params.append(date_to)

    query += " GROUP BY log_date, shift ORDER BY log_date DESC"

    cursor.execute(query, params)

    rows = cursor.fetchall()

    conn.close()

    shift_target = get_shift_target()

    history = []

    for row in rows:

        total = row["total_pieces"]

        percent = round((total / shift_target) * 100) if shift_target else 0

        history.append({
            "date": row["log_date"],
            "shift": row["shift"],
            "produced": total,
            "target": shift_target,
            "percent": percent
        })

    average_percent = (
        round(sum(item["percent"] for item in history) / len(history))
        if history
        else 0
    )

    return {
        "entries": history,
        "average_percent": average_percent
    }


# Реальный режим завода: день 09:00-21:00, ночь 21:00-09:00.
# Границы берутся из shift_schedule_service, чтобы не разъезжались
# в двух местах — там же считается, какая бригада (А/Б/В/Г) выходит
# в эту смену.
from backend.services.shift_schedule_service import (
    DAY_START_HOUR,
    NIGHT_START_HOUR,
    get_shift_at
)

SHIFT_HOURS = {
    # 33 = 09:00 следующих суток, для расчёта длительности ночной смены
    "День": (DAY_START_HOUR, NIGHT_START_HOUR),
    "Ночь": (NIGHT_START_HOUR, NIGHT_START_HOUR + 12)
}


def get_current_shift():
    """
    Текущая смена и сутки, к которым относится выпуск.

    Нужно, чтобы начальник смены не выбирал смену руками: в 23:40
    он оставит "День", и весь ночной выпуск уедет не туда. Ночная
    смена целиком относится к суткам своего НАЧАЛА, включая часы
    после полуночи.
    """

    now = get_shift_at()

    return {
        "shift": now["shift"],
        "log_date": now["shift_date"],
        "brigade": now["brigade"]
    }


def get_shift_chart_data(log_date, shift):
    """
    Данные для графика "Производство за смену" — накопительная
    сумма факта по времени внутри смены + плановая линия (линейная
    от 0 в начале смены до плана на смену в конце).

    Записи не непрерывные (вводятся периодически, не поминутно) —
    график ступенчатый по факту, это честно отражает реальность
    (не выдумываем промежуточные точки).
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT pieces, created_at
        FROM shift_production_log
        WHERE log_date = ? AND shift = ?
        ORDER BY created_at ASC
        """,
        (log_date, shift)
    )

    rows = cursor.fetchall()

    conn.close()

    start_hour, end_hour = SHIFT_HOURS.get(shift, (0, 24))

    points = []
    cumulative = 0

    for row in rows:

        cumulative += row["pieces"]

        # Берём только время (HH:MM) из created_at "YYYY-MM-DD HH:MM:SS"
        time_label = row["created_at"][11:16]

        entry_hour = int(time_label[0:2])
        entry_minute = int(time_label[3:5])

        # Смещение в часах от НАЧАЛА смены — а не просто часы суток.
        # Для ночной смены (18:00 → 06:00) запись в 02:15 должна
        # считаться "8.25 часа от начала", а не сравниваться как
        # текст "02:15" < "18:00" (что сломало бы порядок на графике).
        hour_offset = (entry_hour - start_hour) % 24 + entry_minute / 60

        points.append({
            "time": time_label,
            "hour_offset": round(hour_offset, 2),
            "cumulative": cumulative
        })

    shift_target = get_shift_target()

    duration_hours = end_hour - start_hour

    return {
        "points": points,
        "produced": cumulative,
        "target": shift_target,
        "percent": round((cumulative / shift_target) * 100) if shift_target else 0,
        "remaining": max(shift_target - cumulative, 0),
        "start_hour": start_hour,
        "duration_hours": duration_hours
    }
