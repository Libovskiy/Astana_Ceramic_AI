"""
График ТО: плановые работы и отметки выполнения.

Вынесено из main.py без изменений поведения.
"""

from fastapi import APIRouter
from backend.config import DB_NAME
from backend.services.audit_service import log_action
from fastapi import Depends

from backend.api.common import (
    get_current_user,
    require_roles,
)

router = APIRouter()

@router.get("/api/maintenance/schedule")
def get_maintenance_schedule(year: int = 2026, user: dict = Depends(get_current_user)):
    import sqlite3 as _sq
    conn = _sq.connect(DB_NAME); conn.row_factory = _sq.Row
    rows = conn.execute("SELECT ms.*, e.name as equipment_name, e.location FROM maintenance_schedule ms LEFT JOIN equipment e ON e.id=ms.equipment_id WHERE ms.year=? ORDER BY e.location, e.name, ms.work_name", (year,)).fetchall()
    logs = conn.execute("SELECT * FROM maintenance_log WHERE year=?", (year,)).fetchall()
    conn.close()
    return {"success": True, "schedule": [dict(r) for r in rows], "logs": [dict(l) for l in logs]}

@router.post("/api/maintenance/schedule")
def create_maintenance_schedule(request: dict, user: dict = Depends(require_roles("admin","director","chief_engineer","chief_mechanic","chief_electrician"))):
    import sqlite3 as _sq
    conn = _sq.connect(DB_NAME)
    cur = conn.execute("INSERT INTO maintenance_schedule (equipment_id,work_name,work_type,months,duration_hours,responsible,year,created_by) VALUES (?,?,?,?,?,?,?,?)",
        (request["equipment_id"], request["work_name"], request.get("work_type","monthly"),
         request.get("months","1,2,3,4,5,6,7,8,9,10,11,12"), request.get("duration_hours",0.5),
         request.get("responsible"), request.get("year",2026), user["username"]))
    conn.commit(); conn.close()
    return {"success": True, "id": cur.lastrowid}

@router.delete("/api/maintenance/schedule/{schedule_id}")
def delete_maintenance_schedule(schedule_id: int, user: dict = Depends(require_roles("admin","director","chief_engineer","chief_mechanic"))):
    import sqlite3 as _sq
    conn = _sq.connect(DB_NAME)
    conn.execute("DELETE FROM maintenance_schedule WHERE id=?", (schedule_id,))
    conn.commit(); conn.close()
    return {"success": True}

@router.post("/api/maintenance/log")
def log_maintenance_done(request: dict, user: dict = Depends(get_current_user)):
    # Старый путь отметки: ставит сразу «выполнено», без описания и без
    # проверки. Оставлен для совместимости, но теперь пишет в журнал —
    # раньше и отметка, и снятие не оставляли вообще никакого следа.
    #
    # Новый путь — POST /api/maintenance/done: отметка с описанием,
    # которую принимает главный своей службы.
    import sqlite3 as _sq
    from datetime import datetime as _dt
    conn = _sq.connect(DB_NAME, timeout=10)
    cur = conn.execute("INSERT INTO maintenance_log (plan_id,schedule_id,equipment_id,work_name,month,year,done_at,done_by,note) VALUES (?,?,?,?,?,?,?,?,?)",
        (request["schedule_id"], request["schedule_id"], request["equipment_id"], request["work_name"],
         request["month"], request["year"], _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
         user["full_name"] or user["username"], request.get("note","")))
    log_id = cur.lastrowid
    conn.commit(); conn.close()

    log_action(
        username=user["username"], role=user["role"],
        action="maintenance_marked_done",
        target=f"maintenance:{log_id}",
        details=f"{request.get('work_name')}, месяц {request.get('month')} (старый путь, без проверки)",
    )

    return {"success": True}

# Снять отметку может только тот, кто её принимает: главный своей
# службы, главный инженер, директор или админ.
#
# Почему это важно. Раньше ручка была открыта любому вошедшему и
# ничего не писала в журнал. Пять отметок ТО от 18.09 исчезли с
# боевой базы между 24.09 16:08 и 25.09 02:00, и узнать, кто их снял,
# нельзя: следа не осталось нигде. Одного клика по зелёной клетке
# хватало, чтобы стереть чужую работу бесследно.
UNLOG_ROLES = ("chief_engineer", "chief_mechanic", "chief_electrician",
               "director", "admin")


@router.delete("/api/maintenance/log")
def unlog_maintenance(request: dict, user: dict = Depends(require_roles(*UNLOG_ROLES))):
    import sqlite3 as _sq
    conn = _sq.connect(DB_NAME)
    conn.row_factory = _sq.Row

    # Что именно снимаем — читаем ДО удаления: иначе в журнале
    # останется «что-то удалили», и это ничем не лучше молчания.
    was = conn.execute(
        "SELECT id, work_name, done_by, done_at, status, note FROM maintenance_log "
        "WHERE schedule_id=? AND month=? AND year=?",
        (request["schedule_id"], request["month"], request["year"]),
    ).fetchone()

    conn.execute("DELETE FROM maintenance_log WHERE schedule_id=? AND month=? AND year=?",
        (request["schedule_id"], request["month"], request["year"]))
    conn.commit(); conn.close()

    if was:
        log_action(
            username=user["username"], role=user["role"],
            action="maintenance_unmarked",
            target=f"maintenance:{was['id']}",
            details=f"{was['work_name']}, месяц {request.get('month')} — снята отметка "
                    f"{was['done_by']} от {str(was['done_at'])[:16]}",
            before={"status": was["status"], "done_by": was["done_by"],
                    "note": was["note"]},
            after={"status": "снято"},
        )

    return {"success": True}


@router.get("/api/maintenance/planned-from-report")
def maintenance_planned_from_report(
    year: int | None = None,
    month: int | None = None,
    user: dict = Depends(get_current_user)
):
    """
    Плановые остановки из сменного отчёта — рядом с графиком ТО.

    Это НЕ отметка о выполнении и НЕ сопоставление с работой графика:
    в отчёте написано «Проточка СМК-102», в графике — «проточка
    валков, 8 ч», и связывать их автоматически нельзя. Нужно, чтобы
    «ТО не отмечается» не читалось как «ТО не делают»: работы идут,
    просто отмечают их в другом файле.
    """
    from datetime import datetime

    from backend.services.production_import_service import planned_stops

    now = datetime.now()
    return {
        "success": True,
        **planned_stops(year or now.year, month or now.month),
    }
