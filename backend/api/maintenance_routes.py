"""
График ТО: плановые работы и отметки выполнения.

Вынесено из main.py без изменений поведения.
"""

from fastapi import APIRouter
from backend.config import DB_NAME
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
    import sqlite3 as _sq
    from datetime import datetime as _dt
    conn = _sq.connect(DB_NAME, timeout=10)
    conn.execute("INSERT INTO maintenance_log (plan_id,schedule_id,equipment_id,work_name,month,year,done_at,done_by,note) VALUES (?,?,?,?,?,?,?,?,?)",
        (request["schedule_id"], request["schedule_id"], request["equipment_id"], request["work_name"],
         request["month"], request["year"], _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
         user["full_name"] or user["username"], request.get("note","")))
    conn.commit(); conn.close()
    return {"success": True}

@router.delete("/api/maintenance/log")
def unlog_maintenance(request: dict, user: dict = Depends(get_current_user)):
    import sqlite3 as _sq
    conn = _sq.connect(DB_NAME)
    conn.execute("DELETE FROM maintenance_log WHERE schedule_id=? AND month=? AND year=?",
        (request["schedule_id"], request["month"], request["year"]))
    conn.commit(); conn.close()
    return {"success": True}
