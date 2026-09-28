"""
Свёртка показаний датчиков: минуты — год, часы — навсегда.

Зачем. Сырые показания идут по 19 тысяч в сутки. Для графика за сутки
это в самый раз, а за месяц — уже 600 тысяч строк, которые надо
прочитать и усреднить на лету при каждом открытии страницы. Поэтому
три уровня:

    сырые (sensor_readings)  — 30 дней, как есть, посекундная правда;
    минуты (sensor_minutes)  — год: среднее, минимум, максимум;
    часы   (sensor_hours)    — навсегда, та же форма.

Минимум и максимум хранятся вместе со средним нарочно: всплеск в
пределах минуты не должен исчезать при усреднении. По ним же видно
аварию — у `авария_флаг` максимум за минуту равен единице, если флаг
поднимался хотя бы раз.

ПОРЯДОК УДАЛЕНИЯ СЫРЫХ (решение владельца 28.09.2026):

    свернуть день → записать итог в rollup_log → СВЕРИТЬ → и только
    после этого удалять, и только если удаление разрешено настройкой.

Сверка (`verify_day`) пересчитывает всё заново из сырых и сравнивает с
тем, что легло в свёртку: число минут, число показаний, суммы, минимумы
и максимумы по каждому регистру. Не сошлось хоть в одном — день не
удаляется, а в rollup_log остаётся причина.

Автоматическое удаление по умолчанию ВЫКЛЮЧЕНО. Включается настройкой
после того, как владелец посмотрит отчёт сверки за самый старый день.
"""

import sqlite3
from datetime import datetime, timedelta

from backend.config import DB_PATH
from backend.services import app_settings_service as settings_store

# ── Настройки ───────────────────────────────────────────────────────
RAW_KEEP_DAYS = "sensors_raw_keep_days"            # сколько держим сырые
AUTODELETE = "sensors_rollup_autodelete"           # можно ли удалять самому
KEEP_ALARM_DAYS = "sensors_keep_raw_on_alarm_days"  # беречь дни с аварией

DEFAULTS = {
    RAW_KEEP_DAYS: 30,
    # Пока владелец не увидел отчёт сверки — удалять нельзя. Это не
    # осторожность ради осторожности: сырые данные не восстановить.
    AUTODELETE: "0",
    # Правило «дни с поднятым флагом хранить год» выключено намеренно.
    # Флаг 1658 поднят почти треть суток, и пока неизвестно, что это за
    # сигнал. Включи такое правило вслепую — сырые не удалятся никогда.
    KEEP_ALARM_DAYS: "0",
}

ALARM_REGISTER = "авария_флаг"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sensor_minutes (
    register TEXT NOT NULL,
    minute   TEXT NOT NULL,          -- '2026-09-28 14:32'
    avg REAL, min REAL, max REAL,
    n INTEGER NOT NULL,              -- сколько сырых легло в точку
    n_bad INTEGER NOT NULL DEFAULT 0, -- сколько было нечисловых
    PRIMARY KEY (register, minute)
);
-- Второй порядок нужен для выборки поперёк регистров: «что показывали
-- остальные приводы в ту минуту».
CREATE INDEX IF NOT EXISTS idx_sensor_minutes_time
    ON sensor_minutes(minute, register);

CREATE TABLE IF NOT EXISTS sensor_hours (
    register TEXT NOT NULL,
    hour     TEXT NOT NULL,          -- '2026-09-28 14'
    avg REAL, min REAL, max REAL,
    n INTEGER NOT NULL,
    n_bad INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (register, hour)
);
CREATE INDEX IF NOT EXISTS idx_sensor_hours_time
    ON sensor_hours(hour, register);

CREATE TABLE IF NOT EXISTS rollup_log (
    day TEXT PRIMARY KEY,
    raw_rows INTEGER,
    raw_numeric INTEGER,
    minute_rows INTEGER,
    hour_rows INTEGER,
    rolled_at TEXT,
    checked_at TEXT,
    checks TEXT,                     -- что именно сверяли, по-русски
    raw_deleted_at TEXT,
    note TEXT
);
"""


def _conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def settings() -> dict:
    return {
        "raw_keep_days": int(settings_store.get(RAW_KEEP_DAYS) or DEFAULTS[RAW_KEEP_DAYS]),
        "autodelete": str(settings_store.get(AUTODELETE) or DEFAULTS[AUTODELETE]) == "1",
        "keep_alarm_days": str(settings_store.get(KEEP_ALARM_DAYS) or DEFAULTS[KEEP_ALARM_DAYS]) == "1",
    }


# ── Какие дни есть в сырых ──────────────────────────────────────────

def raw_days() -> list[str]:
    conn = _conn()
    rows = conn.execute(
        "SELECT DISTINCT date(recorded_at) AS d FROM sensor_readings ORDER BY d"
    ).fetchall()
    conn.close()
    return [r["d"] for r in rows if r["d"]]


def oldest_raw_day() -> str | None:
    days = raw_days()
    return days[0] if days else None


# ── Свёртка ─────────────────────────────────────────────────────────

def rollup_day(day: str) -> dict:
    """
    Свернуть один день. Можно звать повторно: день пересобирается
    целиком, без задвоения.

    Нечисловые значения не выбрасываются молча — они считаются в n_bad,
    чтобы «пусто» и «текст вместо числа» не выглядели одинаково.
    """
    conn = _conn()
    cur = conn.cursor()

    cur.execute("DELETE FROM sensor_minutes WHERE substr(minute, 1, 10) = ?", (day,))
    cur.execute("DELETE FROM sensor_hours WHERE substr(hour, 1, 10) = ?", (day,))

    # CAST в SQLite не падает на нечисловом: получается 0.0. Поэтому
    # числовые отбираем отдельным условием, а остальные только считаем.
    numeric = "value GLOB '-[0-9]*' OR value GLOB '[0-9]*'"

    cur.execute(f"""
        INSERT INTO sensor_minutes (register, minute, avg, min, max, n, n_bad)
        SELECT sensor_name,
               substr(recorded_at, 1, 16),
               AVG(CASE WHEN {numeric} THEN CAST(value AS REAL) END),
               MIN(CASE WHEN {numeric} THEN CAST(value AS REAL) END),
               MAX(CASE WHEN {numeric} THEN CAST(value AS REAL) END),
               SUM(CASE WHEN {numeric} THEN 1 ELSE 0 END),
               SUM(CASE WHEN {numeric} THEN 0 ELSE 1 END)
        FROM sensor_readings
        WHERE date(recorded_at) = ?
        GROUP BY sensor_name, substr(recorded_at, 1, 16)
    """, (day,))
    minute_rows = cur.rowcount

    # Часы собираем ИЗ МИНУТ, а не из сырых: тогда час — это честное
    # среднее по минутам, и после удаления сырых он останется таким же.
    cur.execute("""
        INSERT INTO sensor_hours (register, hour, avg, min, max, n, n_bad)
        SELECT register, substr(minute, 1, 13),
               SUM(avg * n) / NULLIF(SUM(n), 0),
               MIN(min), MAX(max), SUM(n), SUM(n_bad)
        FROM sensor_minutes
        WHERE substr(minute, 1, 10) = ?
        GROUP BY register, substr(minute, 1, 13)
    """, (day,))
    hour_rows = cur.rowcount

    raw = cur.execute(
        f"""SELECT COUNT(*) AS all_rows,
                   SUM(CASE WHEN {numeric} THEN 1 ELSE 0 END) AS numeric_rows
            FROM sensor_readings WHERE date(recorded_at) = ?""", (day,)).fetchone()

    cur.execute("""
        INSERT INTO rollup_log (day, raw_rows, raw_numeric, minute_rows, hour_rows, rolled_at)
        VALUES (?, ?, ?, ?, ?, datetime('now','localtime'))
        ON CONFLICT(day) DO UPDATE SET
            raw_rows = excluded.raw_rows, raw_numeric = excluded.raw_numeric,
            minute_rows = excluded.minute_rows, hour_rows = excluded.hour_rows,
            rolled_at = excluded.rolled_at, checked_at = NULL, checks = NULL
    """, (day, raw["all_rows"], raw["numeric_rows"] or 0, minute_rows, hour_rows))

    conn.commit()
    conn.close()
    return {"day": day, "raw_rows": raw["all_rows"], "raw_numeric": raw["numeric_rows"] or 0,
            "minute_rows": minute_rows, "hour_rows": hour_rows}


# ── Сверка ──────────────────────────────────────────────────────────

def verify_day(day: str, tolerance: float = 1e-6) -> dict:
    """
    Пересчитать день заново из сырых и сравнить со свёрткой.

    Сравниваем по каждому регистру: число минут, число показаний,
    сумму значений, минимум и максимум. Сумма — главная проверка:
    совпадение средних при разном числе точек ещё ничего не значит,
    а сумма ловит и потерянную точку, и посчитанную дважды.
    """
    conn = _conn()
    numeric = "value GLOB '-[0-9]*' OR value GLOB '[0-9]*'"

    raw = conn.execute(f"""
        SELECT sensor_name AS register,
               COUNT(DISTINCT substr(recorded_at, 1, 16)) AS minutes,
               SUM(CASE WHEN {numeric} THEN 1 ELSE 0 END) AS n,
               SUM(CASE WHEN {numeric} THEN CAST(value AS REAL) ELSE 0 END) AS total,
               MIN(CASE WHEN {numeric} THEN CAST(value AS REAL) END) AS lo,
               MAX(CASE WHEN {numeric} THEN CAST(value AS REAL) END) AS hi
        FROM sensor_readings WHERE date(recorded_at) = ?
        GROUP BY sensor_name ORDER BY sensor_name
    """, (day,)).fetchall()

    rolled = conn.execute("""
        SELECT register, COUNT(*) AS minutes, SUM(n) AS n,
               SUM(avg * n) AS total, MIN(min) AS lo, MAX(max) AS hi
        FROM sensor_minutes WHERE substr(minute, 1, 10) = ?
        GROUP BY register ORDER BY register
    """, (day,)).fetchall()

    hours = conn.execute("""
        SELECT SUM(n) AS n, SUM(avg * n) AS total
        FROM sensor_hours WHERE substr(hour, 1, 10) = ?
    """, (day,)).fetchone()

    by_register, problems = [], []
    rolled_map = {r["register"]: r for r in rolled}

    for row in raw:
        mine = rolled_map.pop(row["register"], None)
        if mine is None:
            problems.append(f'{row["register"]}: в свёртке нет вовсе')
            continue

        same_minutes = row["minutes"] == mine["minutes"]
        same_n = (row["n"] or 0) == (mine["n"] or 0)
        same_total = abs((row["total"] or 0) - (mine["total"] or 0)) <= max(
            tolerance, abs(row["total"] or 0) * 1e-9)
        same_lo = (row["lo"] is None and mine["lo"] is None) or \
                  abs((row["lo"] or 0) - (mine["lo"] or 0)) <= tolerance
        same_hi = (row["hi"] is None and mine["hi"] is None) or \
                  abs((row["hi"] or 0) - (mine["hi"] or 0)) <= tolerance

        ok = same_minutes and same_n and same_total and same_lo and same_hi
        if not ok:
            problems.append(
                f'{row["register"]}: минут {row["minutes"]}/{mine["minutes"]}, '
                f'показаний {row["n"]}/{mine["n"]}, '
                f'сумма {row["total"]}/{mine["total"]}, '
                f'мин {row["lo"]}/{mine["lo"]}, макс {row["hi"]}/{mine["hi"]}')

        by_register.append({
            "register": row["register"], "ok": ok,
            "minutes_raw": row["minutes"], "minutes_rolled": mine["minutes"],
            "n_raw": row["n"] or 0, "n_rolled": mine["n"] or 0,
            "total_raw": row["total"] or 0, "total_rolled": mine["total"] or 0,
            "min_raw": row["lo"], "min_rolled": mine["lo"],
            "max_raw": row["hi"], "max_rolled": mine["hi"],
        })

    for extra in rolled_map:
        problems.append(f"{extra}: есть в свёртке, но нет в сырых за этот день")

    # Часы собираются из минут, поэтому их сумма обязана совпасть с
    # минутной. Если разошлась — свёртка часов битая.
    minute_total = sum(r["total_rolled"] for r in by_register)
    hour_total = hours["total"] if hours else None
    if hour_total is not None and abs((hour_total or 0) - minute_total) > max(tolerance, abs(minute_total) * 1e-9):
        problems.append(f"часы против минут: {hour_total} против {minute_total}")

    ok = not problems
    conn.execute("""
        UPDATE rollup_log SET checked_at = datetime('now','localtime'), checks = ?
        WHERE day = ?
    """, ("сошлось по всем регистрам" if ok else "; ".join(problems)[:2000], day))
    conn.commit()
    conn.close()

    return {"day": day, "ok": ok, "registers": by_register, "problems": problems,
            "minute_total": minute_total, "hour_total": hour_total}


# ── Удаление сырых ──────────────────────────────────────────────────

def has_alarm(day: str) -> bool:
    """Поднимался ли аварийный флаг в этот день."""
    conn = _conn()
    row = conn.execute("""
        SELECT MAX(max) AS hi FROM sensor_minutes
        WHERE register = ? AND substr(minute, 1, 10) = ?
    """, (ALARM_REGISTER, day)).fetchone()
    conn.close()
    return bool(row and row["hi"] and row["hi"] > 0)


def can_delete_raw(day: str, now: datetime = None) -> tuple[bool, str]:
    """Можно ли удалять сырые за этот день — и если нет, то почему."""
    conf = settings()
    now = now or datetime.now()

    if not conf["autodelete"]:
        return False, ("автоматическое удаление выключено настройкой "
                       f"{AUTODELETE} — ждёт решения владельца")

    edge = (now - timedelta(days=conf["raw_keep_days"])).strftime("%Y-%m-%d")
    if day >= edge:
        return False, f"день моложе {conf['raw_keep_days']} суток"

    conn = _conn()
    row = conn.execute("SELECT * FROM rollup_log WHERE day = ?", (day,)).fetchone()
    conn.close()

    if row is None:
        return False, "день не свёрнут"
    if not row["checked_at"]:
        return False, "свёртка не сверена"
    if row["checks"] != "сошлось по всем регистрам":
        return False, f"сверка не сошлась: {row['checks']}"
    if row["raw_deleted_at"]:
        return False, "сырые уже удалены"

    if conf["keep_alarm_days"] and has_alarm(day):
        return False, "в этот день поднимался аварийный флаг, правило хранения включено"

    return True, "можно"


def delete_raw(day: str, now: datetime = None) -> dict:
    """Удалить сырые за день. Сам проверяет, что это разрешено."""
    allowed, why = can_delete_raw(day, now)
    if not allowed:
        return {"day": day, "deleted": 0, "skipped": why}

    conn = _conn()
    cur = conn.execute("DELETE FROM sensor_readings WHERE date(recorded_at) = ?", (day,))
    removed = cur.rowcount
    conn.execute("""
        UPDATE rollup_log SET raw_deleted_at = datetime('now','localtime'),
               note = COALESCE(note, '') || ?
        WHERE day = ?
    """, (f"удалено сырых: {removed}; ", day))
    conn.commit()
    conn.close()
    return {"day": day, "deleted": removed, "skipped": None}


def status(limit: int = 40) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM rollup_log ORDER BY day DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
