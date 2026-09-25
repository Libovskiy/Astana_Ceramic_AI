"""
Параметры технолога: нормы, история изменений, справочник регистров.

Вынесено из main.py без изменений поведения; справочник регистров
добавлен 25.09.2026.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.config import DB_NAME
from backend.api.common import (
    get_current_user,
    require_roles,
)
from backend.services import sensor_registers_service as registers
from backend.services.audit_service import log_edit

router = APIRouter()


# Регистры правит тот, кто знает панель. Технолог задаёт НОРМЫ, а
# какой регистр к какому станку относится — это про железо, и
# отвечает за это главный инженер.
REGISTER_EDIT_ROLES = ("chief_engineer", "chief_electrician", "admin")


class RegisterPatch(BaseModel):
    title: str | None = None
    unit: str | None = None
    equipment_id: int | None = None
    note: str | None = None
    # Отдельный признак: «снять станок» и «не трогать станок» через
    # один и тот же null различить иначе нельзя.
    clear_equipment: bool = False


@router.get("/api/sensor-registers")
def get_registers(user: dict = Depends(get_current_user)):
    """
    Справочник регистров панели.

    Раньше связь «параметр → регистр» была зашита в код страницы
    (LIVE_MAP в technolog.html, пять пар). Поменять её мог только
    программист, а знает эти пары главный инженер.
    """

    registers.sync_from_panel()
    rows = registers.list_registers()

    return {
        "success": True,
        "registers": rows,
        "can_edit": user["role"] in REGISTER_EDIT_ROLES,
        "live": sum(1 for r in rows if r["state"] == "live"),
        "silent": sum(1 for r in rows if r["state"] == "silent"),
        "unbound": sum(1 for r in rows if not r["equipment_id"]),
        "unnamed": sum(1 for r in rows if not (r["title"] or "").strip()),
    }


@router.put("/api/sensor-registers/{register_id}")
def patch_register(register_id: int, patch: RegisterPatch,
                   user: dict = Depends(require_roles(*REGISTER_EDIT_ROLES))):
    """Назначить регистру имя, единицу и станок."""

    try:
        result = registers.update_register(
            register_id,
            title=patch.title,
            unit=patch.unit,
            equipment_id=(0 if patch.clear_equipment else patch.equipment_id),
            note=patch.note,
            changed_by=user["username"],
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    keep = ("title", "unit", "equipment_id", "note")
    changes = log_edit(
        entity_type="sensor_register", entity_id=register_id,
        before={k: result["before"].get(k) for k in keep},
        after={k: result["after"].get(k) for k in keep},
        user=user, action="sensor_register_updated",
        name=result["after"].get("register"),
    )

    return {"success": True, "register": result["after"],
            "changed": [c["label"] for c in changes]}

@router.get("/api/technolog/params")
def get_technolog_params(user: dict = Depends(get_current_user)):
    import sqlite3 as _sq
    conn = _sq.connect(DB_NAME, timeout=10)
    conn.row_factory = _sq.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS technolog_params (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        stage TEXT NOT NULL, param_name TEXT NOT NULL, unit TEXT,
        min_val REAL, max_val REAL, target_val REAL,
        updated_by TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(stage, param_name))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS technolog_params_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, param_id INTEGER,
        stage TEXT, param_name TEXT,
        old_min REAL, old_max REAL, old_target REAL,
        new_min REAL, new_max REAL, new_target REAL,
        changed_by TEXT, changed_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    conn.commit()
    rows = conn.execute("SELECT * FROM technolog_params ORDER BY stage, param_name").fetchall()
    conn.close()
    return {"success": True, "params": [dict(r) for r in rows]}

@router.put("/api/technolog/params/{param_id}")
def update_technolog_param(param_id: int, request: dict, user: dict = Depends(require_roles("admin","director","chief_engineer","technologist"))):
    import sqlite3 as _sq
    from datetime import datetime as _dt
    conn = _sq.connect(DB_NAME, timeout=10)
    conn.row_factory = _sq.Row
    old = conn.execute("SELECT * FROM technolog_params WHERE id=?", (param_id,)).fetchone()
    if not old:
        conn.close()
        return {"success": False, "message": "Не найден"}
    conn.execute("""INSERT INTO technolog_params_log
        (param_id,stage,param_name,old_min,old_max,old_target,new_min,new_max,new_target,changed_by,changed_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (param_id,old["stage"],old["param_name"],old["min_val"],old["max_val"],old["target_val"],
         request.get("min_val"),request.get("max_val"),request.get("target_val"),
         user["full_name"] or user["username"],_dt.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.execute("UPDATE technolog_params SET min_val=?,max_val=?,target_val=?,updated_by=?,updated_at=? WHERE id=?",
        (request.get("min_val"),request.get("max_val"),request.get("target_val"),
         user["full_name"] or user["username"],_dt.now().strftime("%Y-%m-%d %H:%M:%S"),param_id))
    conn.commit()
    conn.close()
    return {"success": True}

@router.get("/api/technolog/params/{param_id}/history")
def get_param_history(param_id: int, user: dict = Depends(get_current_user)):
    import sqlite3 as _sq
    conn = _sq.connect(DB_NAME, timeout=10)
    conn.row_factory = _sq.Row
    rows = conn.execute("SELECT * FROM technolog_params_log WHERE param_id=? ORDER BY changed_at DESC LIMIT 20",(param_id,)).fetchall()
    conn.close()
    return {"success": True, "history": [dict(r) for r in rows]}

@router.post("/api/technolog/params/seed")
def seed_technolog_params(user: dict = Depends(get_current_user)):
    import sqlite3 as _sq
    from datetime import datetime as _dt
    conn = _sq.connect(DB_NAME, timeout=10)
    defaults = [
        ("Массаподготовка","Влажность массы","%",18,22,20),
        ("Массаподготовка","Зернистость помола","мм",0,3,1.5),
        ("Массаподготовка","Загрузка питателя PL024-1","%",60,95,80),
        ("Массаподготовка","Загрузка питателя PL024-2","%",60,95,80),
        ("Массаподготовка","Частота питателя PL024-1","Гц",30,50,40),
        ("Массаподготовка","Частота питателя PL024-2","Гц",30,50,40),
        ("Массаподготовка","Частота KP-10","Гц",20,45,35),
        ("Массаподготовка","Влажность добавки (уголь)","%",8,14,11),
        ("Формовка","Давление в экструдере","бар",25,45,35),
        ("Формовка","Влажность сырца","%",16,20,18),
        ("Формовка","Длина кирпича-сырца","мм",248,252,250),
        ("Формовка","Ширина кирпича-сырца","мм",118,122,120),
        ("Формовка","Высота кирпича-сырца","мм",63,67,65),
        ("Формовка","Скорость экструдера","м/мин",8,14,11),
        ("Сушка","Температура зона 1","°C",40,70,55),
        ("Сушка","Температура зона 2","°C",60,90,75),
        ("Сушка","Температура зона 3","°C",80,110,95),
        ("Сушка","Влажность на выходе","%",1,4,2),
        ("Сушка","Время сушки","час",20,30,24),
        ("Обжиг","Температура обжига (макс)","°C",950,1050,1000),
        ("Обжиг","Скорость вагонеток","мин/толч",12,20,15),
        ("Обжиг","Расход угля","кг/час",80,140,110),
        ("Обжиг","Температура дымовых газов","°C",100,180,140),
        ("Упаковка","Брак (норма)","%",0,3,1),
    ]
    for stage,name,unit,mn,mx,tgt in defaults:
        try:
            conn.execute("INSERT OR IGNORE INTO technolog_params (stage,param_name,unit,min_val,max_val,target_val,updated_by,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (stage,name,unit,mn,mx,tgt,user["username"],_dt.now().strftime("%Y-%m-%d %H:%M:%S")))
        except: pass
    conn.commit()
    conn.close()
    return {"success": True}


@router.post("/api/technolog/params")
def create_technolog_param(request: dict, user: dict = Depends(require_roles("admin","director","chief_engineer","technologist"))):
    import sqlite3 as _sq
    from datetime import datetime as _dt
    conn = _sq.connect(DB_NAME, timeout=10)
    try:
        cur = conn.execute("""INSERT INTO technolog_params
            (stage,param_name,unit,min_val,max_val,target_val,updated_by,updated_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            (request["stage"], request["param_name"], request.get("unit"),
             request.get("min_val"), request.get("max_val"), request.get("target_val"),
             user["full_name"] or user["username"], _dt.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        return {"success": True, "id": cur.lastrowid}
    except Exception as e:
        return {"success": False, "message": str(e)}
    finally:
        conn.close()

@router.delete("/api/technolog/params/{param_id}")
def delete_technolog_param(param_id: int, user: dict = Depends(require_roles("admin","director","chief_engineer","technologist"))):
    import sqlite3 as _sq
    conn = _sq.connect(DB_NAME, timeout=10)
    conn.execute("DELETE FROM technolog_params WHERE id=?", (param_id,))
    conn.commit()
    conn.close()
    return {"success": True}
