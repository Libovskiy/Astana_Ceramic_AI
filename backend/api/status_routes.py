"""
Живое состояние завода для шапки меню.

Раньше там висела надпись «Завод работает» — она горела всегда, при
любом положении дел, и смотреть на неё было незачем. Надпись, которая
не меняется, хуже пустого места: она занимает первое по заметности
место и приучает не верить интерфейсу.

Здесь три признака, каждый из настоящих данных:

  ДАТЧИКИ   — когда последний раз приходили показания. Сбор идёт через
              вкладку браузера на сервере: закрыли вкладку — данные
              молча кончились, и узнать об этом больше неоткуда.
  АВАРИИ    — станки со статусом «ошибка» и открытые обращения по
              поломкам. Это то, из-за чего цех стоит.
  В СИСТЕМЕ — сколько человек сейчас работает в ACAI.

Про третий признак честно: владелец просил «сколько людей на смене»,
но расписания смен в системе нет — ни таблицы бригад по дням, ни
табеля. Показываем то, что знаем на самом деле: у кого сейчас живая
сессия. Появится табель — заменим на него.

Кому показывать, решает не эта ручка, а страница: у лаборанта и
аналитика цеховые признаки в шапке только отнимают место.
"""

import sqlite3
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends

from backend.api.common import get_current_user
from backend.config import DB_NAME

router = APIRouter()

# Сколько минут сессия считается живой. Человек мог просто отойти,
# поэтому берём с запасом: это «кто сейчас в системе», а не «кто
# сию секунду щёлкает мышью».
ONLINE_MINUTES = 20

# Молчание датчиков дольше этого — уже не заминка связи.
SENSORS_STALE_MINUTES = 15


def _factory_db():
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _sensors_age_minutes() -> int | None:
    """Сколько минут назад приходили показания. None — не приходили никогда."""
    from backend.config import DB_PATH

    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        row = conn.execute("SELECT MAX(recorded_at) FROM sensor_readings").fetchone()
        conn.close()
    except Exception:
        return None

    if not row or not row[0]:
        return None

    stamp = str(row[0]).split(".")[0]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return max(0, int((datetime.now() - datetime.strptime(stamp, fmt)).total_seconds() // 60))
        except ValueError:
            continue
    return None


def _human_age(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} мин назад"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} ч назад"
    days = hours // 24
    return f"{days} дн. назад"


@router.get("/api/status/header")
def header_status(user: dict = Depends(get_current_user)):
    """Три живых признака для шапки. Считает сервер, страница только рисует."""
    conn = _factory_db()
    try:
        broken = conn.execute(
            "SELECT COUNT(*) FROM equipment "
            "WHERE COALESCE(is_active, 1) = 1 AND status = 'Ошибка'"
        ).fetchone()[0]

        open_cases = conn.execute(
            "SELECT COUNT(*) FROM cases WHERE status NOT IN ('Закрыто', 'Черновик закрытия')"
        ).fetchone()[0]

        since = (datetime.now() - timedelta(minutes=ONLINE_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
        online = conn.execute(
            "SELECT COUNT(DISTINCT s.user_id) FROM sessions s "
            "JOIN users u ON u.id = s.user_id "
            "WHERE s.expires_at > ? AND COALESCE(u.hidden, 0) = 0", (since,)
        ).fetchone()[0]
    finally:
        conn.close()

    age = _sensors_age_minutes()

    if age is None:
        sensors = {"state": "none", "text": "Датчики: данных нет"}
    elif age > SENSORS_STALE_MINUTES:
        sensors = {"state": "warn", "text": f"Датчики: {_human_age(age)}"}
    else:
        sensors = {"state": "ok", "text": "Датчики: идут"}

    if broken or open_cases:
        parts = []
        if broken:
            parts.append(f"{broken} станк{'ов' if broken > 4 or broken == 0 else ('а' if broken > 1 else '')} стоит")
        if open_cases:
            parts.append(f"{open_cases} обращени{'й' if open_cases > 4 else ('я' if open_cases > 1 else 'е')}")
        alarms = {"state": "danger" if broken else "warn", "text": ", ".join(parts)}
    else:
        alarms = {"state": "ok", "text": "Аварий нет"}

    people = {
        "state": "ok" if online else "none",
        "text": f"В системе: {online}" if online else "В системе никого",
    }

    return {
        "success": True,
        "sensors": sensors,
        "alarms": alarms,
        "people": people,
        # Честная оговорка для интерфейса: это не табель.
        "people_note": "Считаются вошедшие в ACAI, а не табель смены — расписания смен в системе нет.",
    }
