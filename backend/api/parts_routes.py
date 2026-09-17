"""
Склад запчастей.

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

# Кто работает со складом. Совпадает со списком страницы /parts в
# PAGE_ROLES. Электрик раньше отсутствовал, хотя меняет те же
# контакторы и датчики, что механик — подшипники.
PARTS_ROLES = ("director", "chief_engineer", "engineer", "chief_mechanic",
               "mechanic", "chief_electrician", "electrician")

@router.get("/api/parts")
def get_parts(user: dict = Depends(get_current_user)):
    import sqlite3 as _sq
    conn = _sq.connect(DB_NAME, timeout=10); conn.row_factory = _sq.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS parts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, part_number TEXT, category TEXT DEFAULT 'other',
        equipment_id INTEGER, unit TEXT DEFAULT 'шт',
        quantity REAL DEFAULT 0, min_quantity REAL DEFAULT 1,
        last_used_at TEXT, created_by TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS parts_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, part_id INTEGER,
        quantity_change REAL, direction TEXT,
        changed_by TEXT, changed_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    conn.commit()
    rows = conn.execute("""SELECT p.*, e.name as eq_name FROM parts p
        LEFT JOIN equipment e ON e.id=p.equipment_id ORDER BY p.name""").fetchall()
    conn.close()
    parts=[{**dict(r), 'equipment_name': r['eq_name']} for r in rows]
    return {"success": True, "parts": parts}

@router.post("/api/parts")
def create_part(request: dict, user: dict = Depends(require_roles("admin","director","chief_engineer","chief_mechanic","chief_electrician"))):
    import sqlite3 as _sq
    from datetime import datetime as _dt
    conn = _sq.connect(DB_NAME, timeout=10)
    cur = conn.execute("INSERT INTO parts (name,part_number,category,equipment_id,unit,quantity,min_quantity,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (request["name"], request.get("part_number"), request.get("category","other"),
         request.get("equipment_id"), request.get("unit","шт"),
         request.get("quantity",0), request.get("min_quantity",1),
         user["full_name"] or user["username"], _dt.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit(); conn.close()
    return {"success": True, "id": cur.lastrowid}

@router.post("/api/parts/{part_id}/move")
def move_part(part_id: int, request: dict, user: dict = Depends(require_roles(*PARTS_ROLES))):
    # Раньше хватало просто войти в систему: рабочий, которому страница
    # склада закрыта, мог через API списать или приходовать что угодно.
    import sqlite3 as _sq
    from datetime import datetime as _dt
    conn = _sq.connect(DB_NAME, timeout=10); conn.row_factory = _sq.Row
    part = conn.execute("SELECT * FROM parts WHERE id=?", (part_id,)).fetchone()
    if not part: conn.close(); return {"success": False, "message": "Не найдено"}
    new_qty = max(0, float(part["quantity"]) + float(request.get("quantity",0)))
    now = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE parts SET quantity=?,last_used_at=? WHERE id=?", (new_qty, now, part_id))
    conn.execute("INSERT INTO parts_log (part_id,quantity_change,direction,changed_by,changed_at) VALUES (?,?,?,?,?)",
        (part_id, abs(float(request.get("quantity",0))), "in" if float(request.get("quantity",0))>0 else "out",
         user["full_name"] or user["username"], now))
    conn.commit(); conn.close()
    return {"success": True, "new_quantity": new_qty}
