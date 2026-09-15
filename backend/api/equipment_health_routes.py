"""
Исправность оборудования — считаем, а не показываем 100%.

Колонка equipment.health заведена со значением по умолчанию 100 и никем
никогда не обновляется, поэтому у станка со статусом «Внимание» в карточке
всё равно висело «Исправность 100%».

Считаем по фактам за последние 90 дней и ОБЯЗАТЕЛЬНО возвращаем разбивку:
цифра, которую нельзя объяснить мастеру, на заводе бесполезна.

Веса подобраны так, чтобы один инцидент не обрушивал показатель, а
серия — обрушивала. Это оценка, а не физика: если мастера скажут, что
простой важнее поломок, меняются четыре числа ниже.

Подключение в main.py:
    from backend.api.equipment_health_routes import router as equipment_health_router
    app.include_router(equipment_health_router)
"""
import sqlite3
from datetime import datetime, timedelta

from fastapi import APIRouter, Cookie, Depends, HTTPException

from backend.config import DB_NAME
from backend.services.auth_service import get_user_by_session

router = APIRouter(prefix="/api/equipment", tags=["equipment-health"])

WINDOW_DAYS = 90

# сколько снимает каждый фактор и насколько максимум
W_CASE = 4;        MAX_CASES = 40      # обращение
W_ESCALATED = 6;   MAX_ESCALATED = 30  # эскалация — сверх обычного обращения
W_DOWNTIME_H = 2;  MAX_DOWNTIME = 30   # час простоя
W_OVERDUE_TO = 5;  MAX_OVERDUE = 20    # просроченная работа по графику

STATUS_PENALTY = {"Ошибка": 15, "Внимание": 7}


def current_user(session_token: str | None = Cookie(default=None)):
    user = get_user_by_session(session_token)
    if user is None:
        raise HTTPException(status_code=401, detail="Не авторизован.")
    return user


def _db():
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _safe(conn, sql, params=()):
    """Таблицы могли не создаться на свежей установке — не роняем страницу."""
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []


@router.get("/health")
def equipment_health(equipment_id: int | None = None, user: dict = Depends(current_user)):
    now = datetime.now()
    since = (now - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    year, month_now = now.year, now.month

    conn = _db()
    try:
        eq_filter = " AND equipment_id = ?" if equipment_id is not None else ""
        eq_param = [equipment_id] if equipment_id is not None else []

        equipment = _safe(
            conn,
            "SELECT id, name, status FROM equipment"
            + (" WHERE id = ?" if equipment_id is not None else ""),
            eq_param,
        )

        cases = _safe(
            conn,
            f"""SELECT equipment_id,
                       COUNT(*) AS total,
                       SUM(CASE WHEN status = 'Требует специалиста' THEN 1 ELSE 0 END) AS escalated
                FROM cases
                WHERE created_at >= ? AND equipment_id IS NOT NULL{eq_filter}
                GROUP BY equipment_id""",
            [since] + eq_param,
        )

        downtime = _safe(
            conn,
            f"""SELECT equipment_id, COALESCE(SUM(duration_minutes), 0) AS minutes
                FROM downtime_log
                WHERE started_at >= ?{eq_filter}
                GROUP BY equipment_id""",
            [since] + eq_param,
        )

        schedule = _safe(
            conn,
            f"SELECT id, equipment_id, months FROM maintenance_schedule WHERE year = ?{eq_filter}",
            [year] + eq_param,
        )
        logs = _safe(
            conn,
            f"SELECT schedule_id, equipment_id, month FROM maintenance_log WHERE year = ?{eq_filter}",
            [year] + eq_param,
        )
    finally:
        conn.close()

    by_case = {r["equipment_id"]: r for r in cases}
    by_down = {r["equipment_id"]: r["minutes"] or 0 for r in downtime}

    done = {(r["schedule_id"], r["month"]) for r in logs}
    overdue_by_eq: dict = {}
    for row in schedule:
        for part in str(row["months"] or "").split(","):
            part = part.strip()
            if not part.isdigit():
                continue
            m = int(part)
            if 1 <= m < month_now and (row["id"], m) not in done:
                overdue_by_eq[row["equipment_id"]] = overdue_by_eq.get(row["equipment_id"], 0) + 1

    result = {}
    for eq in equipment:
        eq_id = eq["id"]
        c = by_case.get(eq_id)
        total_cases = (c["total"] if c else 0) or 0
        escalated = (c["escalated"] if c else 0) or 0
        minutes = by_down.get(eq_id, 0) or 0
        overdue = overdue_by_eq.get(eq_id, 0)

        p_cases = min(total_cases * W_CASE, MAX_CASES)
        p_esc = min(escalated * W_ESCALATED, MAX_ESCALATED)
        p_down = min(round(minutes / 60 * W_DOWNTIME_H), MAX_DOWNTIME)
        p_to = min(overdue * W_OVERDUE_TO, MAX_OVERDUE)
        p_status = STATUS_PENALTY.get(eq["status"], 0)

        score = max(0, min(100, 100 - p_cases - p_esc - p_down - p_to - p_status))

        result[str(eq_id)] = {
            "health": score,
            "window_days": WINDOW_DAYS,
            "cases": total_cases,
            "escalated": escalated,
            "downtime_minutes": minutes,
            "overdue_maintenance": overdue,
            "status": eq["status"],
            # разбивка — чтобы в интерфейсе можно было показать, из чего вышла цифра
            "penalties": {
                "Обращения": p_cases,
                "Эскалации": p_esc,
                "Простои": p_down,
                "Просроченное ТО": p_to,
                "Текущий статус": p_status,
            },
        }

    return {"success": True, "health": result}
