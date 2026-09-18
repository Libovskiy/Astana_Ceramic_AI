"""
Была ли система на месте: честный журнал доступности сервера.

ЗАЧЕМ. Сервер — ноутбук. Он засыпает, у него садится батарея, его
уносят, пропадает Wi-Fi. Для цеха это выглядит одинаково: «сайт не
открывается» — и человек больше не пробует. А в системе не остаётся
никакого следа: показания просто не писались, уведомления просто не
ушли, и назавтра всё выглядит так, будто ничего не происходило.

Из журнала сна этого Mac видно, что 18.09.2026 он спал с 07:48 до
08:54 — почти час рабочего утра. Ровно в такие часы «показатели не
обновляются» списывали на расширение WebHMI, хотя причина была другой.

ЧТО ДЕЛАЕМ. Раз в минуту сервер отмечает, что он жив. Пропуск больше
пяти минут — это время, когда системы для завода не существовало. По
этим отметкам страница «Использование» честно показывает: сколько
часов вчера сервер был доступен и когда именно его не было.

Важно: это журнал не «падений программы», а именно недоступности —
выключили, усыпили, унесли, пропала сеть. Отличить причину отметки не
могут, и выдумывать её не нужно: достаточно видеть, что провал был.
"""

import sqlite3
import threading
import time
from datetime import datetime, timedelta

from backend.config import DB_NAME

# Насколько редко пишем. Раз в минуту — этого хватает, чтобы заметить
# провал, и это одна крошечная запись, а не нагрузка.
TICK_SECONDS = 60

# Пропуск, начиная с которого считаем, что системы не было. Пять минут
# — чтобы обычная перезагрузка сервера (секунды) не попадала в отчёт.
GAP_MINUTES = 5

# Сколько дней храним отметки. Год — это ~525 тысяч строк по 20 байт,
# меньше мегабайта, зато видно всю историю пилота.
KEEP_DAYS = 365


def get_connection():
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_availability():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS server_heartbeat (
            minute TEXT PRIMARY KEY      -- 'YYYY-MM-DD HH:MM', местное время
        )
    """)
    conn.commit()
    conn.close()


def beat() -> None:
    """Отметка «я на месте». Падать нельзя: это фоновая мелочь."""
    try:
        conn = get_connection()
        conn.execute(
            "INSERT OR IGNORE INTO server_heartbeat (minute) VALUES (?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M"),)
        )
        conn.commit()
        conn.close()
    except Exception as error:
        print(f"[availability] отметка не записана: {error}")


def _cleanup() -> None:
    try:
        edge = (datetime.now() - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d %H:%M")
        conn = get_connection()
        conn.execute("DELETE FROM server_heartbeat WHERE minute < ?", (edge,))
        conn.commit()
        conn.close()
    except Exception as error:
        print(f"[availability] чистка не удалась: {error}")


def _loop() -> None:
    last_cleanup = datetime.now()
    while True:
        beat()
        if datetime.now() - last_cleanup > timedelta(hours=12):
            _cleanup()
            last_cleanup = datetime.now()
        time.sleep(TICK_SECONDS)


def start() -> None:
    """Запускается один раз при старте основного экземпляра сервера."""
    init_availability()
    beat()
    threading.Thread(target=_loop, daemon=True, name="acai-heartbeat").start()


# ── что показывать ────────────────────────────────────────

def gaps(days: int = 7) -> list:
    """
    Провалы: когда системы не было. Самые свежие — первыми.

    Первая отметка вообще (начало наблюдения) провалом не считается:
    до неё ничего не записывалось, и говорить «сервера не было» — это
    была бы неправда.
    """
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M")

    conn = get_connection()
    try:
        rows = [row[0] for row in conn.execute(
            "SELECT minute FROM server_heartbeat WHERE minute >= ? ORDER BY minute", (since,)
        )]
    finally:
        conn.close()

    if not rows:
        return []

    found = []
    previous = datetime.strptime(rows[0], "%Y-%m-%d %H:%M")

    for value in rows[1:]:
        current = datetime.strptime(value, "%Y-%m-%d %H:%M")
        minutes = int((current - previous).total_seconds() // 60)
        if minutes > GAP_MINUTES:
            found.append({
                "from": previous.strftime("%Y-%m-%d %H:%M"),
                "to": current.strftime("%Y-%m-%d %H:%M"),
                "minutes": minutes,
            })
        previous = current

    # Пропуск «до сих пор»: сервер мог только что вернуться, а мог и
    # вовсе не работать — тогда этот отчёт читают уже после его старта.
    now = datetime.now()
    tail = int((now - previous).total_seconds() // 60)
    if tail > GAP_MINUTES:
        found.append({
            "from": previous.strftime("%Y-%m-%d %H:%M"),
            "to": now.strftime("%Y-%m-%d %H:%M"),
            "minutes": tail,
        })

    found.reverse()
    return found


def summary(days: int = 7) -> dict:
    """
    Коротко: сколько времени система была доступна за период.

    Если отметок нет вовсе — так и говорим, а не рисуем 100%.
    """
    since = datetime.now() - timedelta(days=days)

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n, MIN(minute) AS first FROM server_heartbeat WHERE minute >= ?",
            (since.strftime("%Y-%m-%d %H:%M"),)
        ).fetchone()
    finally:
        conn.close()

    counted = row["n"] or 0
    if not counted:
        return {"known": False, "days": days}

    # Считаем от первой отметки, а не от начала периода: раньше неё
    # система просто не умела это записывать.
    started = datetime.strptime(row["first"], "%Y-%m-%d %H:%M")
    watched = max(1, int((datetime.now() - started).total_seconds() // 60))
    found = gaps(days)

    return {
        "known": True,
        "days": days,
        "since": started.strftime("%Y-%m-%d %H:%M"),
        "minutes_watched": watched,
        "minutes_down": sum(item["minutes"] for item in found),
        "percent": round(min(100.0, counted / watched * 100), 1),
        "gaps": found[:10],
        "gaps_count": len(found),
    }
