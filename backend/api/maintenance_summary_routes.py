"""
Сводка по ТО для карточки оборудования.

Карточка станка читала equipment.last_maintenance_at / next_maintenance_at —
поля, которые заполняются только кнопкой «ТО выполнено» в самой карточке.
Настоящий график живёт в maintenance_schedule (работы с перечнем месяцев)
и maintenance_log (отметки о выполнении), и про эти поля ничего не знает.
Отсюда «Не указано / Не запланировано» при 78 внесённых работах.

Считаем сводку прямо из графика:
  последнее ТО — самая свежая отметка в журнале;
  следующее   — ближайший месяц из графика, на который отметки ещё нет;
  просрочено  — месяцы этого года, которые уже прошли без отметки.

Подключение в main.py:
    from backend.api.maintenance_summary_routes import router as maintenance_summary_router
    app.include_router(maintenance_summary_router)
"""
import sqlite3
from datetime import datetime

from fastapi import APIRouter, Cookie, Depends, HTTPException

import os

from backend.config import DB_NAME
from backend.services.auth_service import get_user_by_session


def _maintenance_start():
    """
    Месяц, с которого график считается действующим. До него просрочки
    быть не может: работы внесли задним числом, и никто их не пропускал.
    """
    raw = (os.environ.get("ACAI_MAINTENANCE_START") or "").strip()

    if not raw:
        env_file = Path(__file__).resolve().parents[2] / ".env"
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

router = APIRouter(prefix="/api/maintenance", tags=["maintenance-summary"])

MONTHS_RU = [
    "", "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
]


def current_user(session_token: str | None = Cookie(default=None)):
    user = get_user_by_session(session_token)
    if user is None:
        raise HTTPException(status_code=401, detail="Не авторизован.")
    return user


def _db():
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _parse_months(raw) -> list[int]:
    out = []
    for part in str(raw or "").split(","):
        part = part.strip()
        if part.isdigit():
            m = int(part)
            if 1 <= m <= 12:
                out.append(m)
    return sorted(set(out))


def _build(year: int, month_now: int, schedule, logs, start=(None, None)):
    """
    Возвращает сводку по одному станку.
    logs — множество (schedule_id, month) уже выполненного за год.
    """
    planned = 0
    overdue = []
    upcoming = []

    for row in schedule:
        for m in _parse_months(row["months"]):
            planned += 1
            if (row["id"], m) in logs:
                continue
            entry = {"month": m, "work_name": row["work_name"]}

            start_year, start_month = start
            before_start = bool(start_year) and (
                year < start_year or (year == start_year and m < start_month)
            )

            if before_start:
                # График ещё не действовал — ни просрочка, ни план.
                continue

            if m < month_now:
                overdue.append(entry)
            else:
                upcoming.append(entry)

    upcoming.sort(key=lambda x: x["month"])
    overdue.sort(key=lambda x: x["month"])

    nxt = upcoming[0] if upcoming else None
    return {
        "planned_count": planned,
        "done_count": len(logs),
        "overdue_count": len(overdue),
        "overdue_first": overdue[0] if overdue else None,
        "next_month": nxt["month"] if nxt else None,
        "next_month_name": MONTHS_RU[nxt["month"]] if nxt else None,
        "next_work": nxt["work_name"] if nxt else None,
        "year": year,
    }


@router.get("/summary")
def maintenance_summary(
    equipment_id: int | None = None,
    year: int | None = None,
    user: dict = Depends(current_user),
):
    """
    Без equipment_id — сводка по всему парку (для счётчиков на странице
    оборудования), с ним — по одному станку, вместе с историей работ.
    """
    now = datetime.now()
    year = year or now.year
    month_now = now.month if year == now.year else 13
    start = _maintenance_start()

    conn = _db()
    try:
        params: list = [year]
        where = "WHERE year = ?"
        if equipment_id is not None:
            where += " AND equipment_id = ?"
            params.append(equipment_id)

        schedule = conn.execute(
            f"SELECT id, equipment_id, work_name, months, responsible FROM maintenance_schedule {where}",
            params,
        ).fetchall()

        logs = conn.execute(
            f"SELECT schedule_id, equipment_id, month, done_at, done_by, work_name "
            f"FROM maintenance_log {where}",
            params,
        ).fetchall()
    except sqlite3.OperationalError:
        # графика ТО в базе ещё нет — не ломаем страницу
        conn.close()
        return {"success": True, "summary": {}, "history": []}
    finally:
        try:
            conn.close()
        except Exception:
            pass

    by_eq: dict[int, list] = {}
    for row in schedule:
        by_eq.setdefault(row["equipment_id"], []).append(row)

    logs_by_eq: dict[int, set] = {}
    last_by_eq: dict[int, dict] = {}
    for row in logs:
        logs_by_eq.setdefault(row["equipment_id"], set()).add((row["schedule_id"], row["month"]))
        prev = last_by_eq.get(row["equipment_id"])
        if row["done_at"] and (prev is None or row["done_at"] > prev["done_at"]):
            last_by_eq[row["equipment_id"]] = {
                "done_at": row["done_at"],
                "done_by": row["done_by"],
                "work_name": row["work_name"],
            }

    summary = {}
    for eq_id, rows in by_eq.items():
        item = _build(year, month_now, rows, logs_by_eq.get(eq_id, set()), start)
        item["last"] = last_by_eq.get(eq_id)
        summary[str(eq_id)] = item

    result = {"success": True, "summary": summary}

    if equipment_id is not None:
        # для карточки — ещё и список работ с отметками
        done_pairs = logs_by_eq.get(equipment_id, set())
        works = []
        for row in by_eq.get(equipment_id, []):
            months = _parse_months(row["months"])
            works.append({
                "work_name": row["work_name"],
                "responsible": row["responsible"],
                "months": months,
                "done_months": sorted(m for m in months if (row["id"], m) in done_pairs),
            })
        works.sort(key=lambda w: w["work_name"])
        result["works"] = works
        result["equipment_summary"] = summary.get(str(equipment_id))

    return result


@router.get("/settings")
def maintenance_settings(user: dict = Depends(current_user)):
    """Дата запуска графика — фронтенд красит месяцы по ней же."""
    start_year, start_month = _maintenance_start()
    return {
        "success": True,
        "start_year": start_year,
        "start_month": start_month,
    }
