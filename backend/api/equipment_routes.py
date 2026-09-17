"""
Оборудование: список, карточка, журнал, документы, статус, архив, ТО выполнено, простои.

Вынесено из main.py без изменений поведения.
"""

from fastapi import APIRouter
import re as _re
import unicodedata as _ud
from backend.config import DB_NAME
from backend.services.audit_service import get_audit_log_by_target, log_action
from backend.services.auth_service import get_assigned_equipment_ids
from backend.services.case_service import get_cases_by_equipment
from backend.services.downtime_service import (
    end_downtime,
    get_active_downtimes,
    get_downtime_history,
    start_downtime,
)
from backend.services.equipment_service import (
    create_equipment,
    get_all_equipment,
    get_equipment,
    update_equipment_details,
)
from backend.services.equipment_state_service import maintenance_completed
from fastapi import BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from backend.api.common import (
    DASHBOARD_ALLOWED_ROLES,
    SETTINGS_ALLOWED_ROLES,
    WORK_QUEUE_ROLES,
    get_current_user,
    require_roles,
)

router = APIRouter()

class CreateEquipmentRequest(BaseModel):

    name: str

    type: str | None = None

    stage: str | None = None

    discipline: str | None = None

    location: str | None = None


class UpdateEquipmentRequest(BaseModel):

    name: str

    type: str | None = None

    stage: str | None = None

    discipline: str | None = None

    location: str | None = None


class StartDowntimeRequest(BaseModel):

    reason: str | None = None


# =========================================
# БЕЗОПАСНОСТЬ ЗАГРУЗОК И ВХОДА
# =========================================

MAX_DOC_BYTES = 50 * 1024 * 1024          # потолок на документ
ALLOWED_DOC_EXT = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".txt", ".jpg", ".jpeg", ".png"}


def safe_filename(name: str, default: str = "document.pdf") -> str:
    """
    Оставляет только имя файла, без каких-либо путей.

    Клиент присылает произвольную строку, и «../../backend/api/main.py»
    в ней — рабочий способ перезаписать код. Поэтому режем всё до
    последнего разделителя, выбрасываем управляющие символы и проверяем
    расширение по белому списку.
    """
    raw = str(name or "").strip()
    raw = raw.replace("\\", "/").split("/")[-1]      # и windows-, и unix-пути
    raw = _ud.normalize("NFC", raw)
    raw = _re.sub(r"[\x00-\x1f]", "", raw)
    raw = raw.lstrip(".") or default                  # «.», «..», «.htaccess»

    ext = ("." + raw.rsplit(".", 1)[-1].lower()) if "." in raw else ""
    if ext not in ALLOWED_DOC_EXT:
        raise HTTPException(
            status_code=415,
            detail=f"Такой тип файла загружать нельзя. Разрешены: {', '.join(sorted(ALLOWED_DOC_EXT))}",
        )
    return raw[:150]


# =========================================
# EQUIPMENT API
# =========================================
# Рабочий (role='worker') видит только назначенные ему станки
# (таблица worker_equipment). Все остальные роли видят всё оборудование.

@router.get("/api/equipment")
def equipment_list(user: dict = Depends(get_current_user)):

    equipment = get_all_equipment()

    if user["role"] == "worker":

        allowed_ids = set(get_assigned_equipment_ids(user["id"]))

        equipment = [
            item
            for item in equipment
            if item["id"] in allowed_ids
        ]

    return {
        "success": True,
        "equipment": equipment
    }


@router.get("/api/equipment/{equipment_id}")
def equipment_details(equipment_id: int, user: dict = Depends(get_current_user)):

    if user["role"] == "worker":

        allowed_ids = set(get_assigned_equipment_ids(user["id"]))

        if equipment_id not in allowed_ids:
            return {
                "success": False,
                "message": "У вас нет доступа к этому оборудованию."
            }

    equipment = get_equipment(equipment_id)

    if equipment is None:

        return {
            "success": False,
            "message": "Оборудование не найдено."
        }

    return {
        "success": True,
        "equipment": equipment
    }


# =========================================
# EQUIPMENT LIFE JOURNAL
# =========================================
# Объединяет обращения (диагностика/ремонт) и отметки обслуживания
# в единую хронологию по конкретному станку — "паспорт оборудования"
# в цифровом виде. Работает только для событий ПОСЛЕ подключения
# equipment_id к обращениям — более старая история недоступна.

@router.get("/api/equipment/{equipment_id}/journal")
def equipment_journal_route(
    equipment_id: int,
    user: dict = Depends(get_current_user)
):

    if user["role"] == "worker":

        allowed_ids = set(get_assigned_equipment_ids(user["id"]))

        if equipment_id not in allowed_ids:
            return {
                "success": False,
                "message": "У вас нет доступа к этому оборудованию."
            }

    equipment = get_equipment(equipment_id)

    if equipment is None:
        return {
            "success": False,
            "message": "Оборудование не найдено."
        }

    cases = get_cases_by_equipment(equipment_id)

    try:
        maintenance_events = get_audit_log_by_target(f"equipment:{equipment_id}")
        if not isinstance(maintenance_events, list):
            maintenance_events = []
    except Exception:
        maintenance_events = []

    events = []

    for case in cases:
        events.append({
            "type": "case",
            "date": str(case["created_at"] or ""),
            "status": str(case["status"] or ""),
            "symptom": str(case["worker_question"] or case["symptom"] or ""),
            "resolution": str(case["resolution_comment"] or ""),
            "case_id": int(case["id"])
        })

    for entry in maintenance_events:
        events.append({
            "type": "maintenance",
            "date": str(entry["created_at"] or ""),
            "username": str(entry["username"] or ""),
            "role": str(entry["role"] or "")
        })

    events.sort(key=lambda item: item["date"], reverse=True)

    def safe(v):
        if isinstance(v, bytes):
            return None
        if isinstance(v, (str, int, float, bool, type(None))):
            return v
        return str(v)

    safe_events = [{k: safe(v) for k, v in e.items()} for e in events]

    return {
        "success": True,
        "journal": safe_events,
        "events": safe_events
    }


@router.post("/api/settings/equipment")
def create_equipment_route(
    request: CreateEquipmentRequest,
    user: dict = Depends(require_roles(*SETTINGS_ALLOWED_ROLES))
):

    try:

        equipment_id = create_equipment(
            request.name,
            request.type,
            request.stage,
            request.discipline,
            request.location
        )

    except ValueError as error:

        return {
            "success": False,
            "message": str(error)
        }

    log_action(
        username=user["username"],
        role=user["role"],
        action="equipment_created",
        target=f"equipment:{equipment_id}",
        details=request.name
    )

    return {
        "success": True,
        "equipment_id": equipment_id
    }


@router.put("/api/settings/equipment/{equipment_id}")
def update_equipment_route(
    equipment_id: int,
    request: UpdateEquipmentRequest,
    user: dict = Depends(require_roles(*SETTINGS_ALLOWED_ROLES))
):

    try:

        update_equipment_details(
            equipment_id,
            request.name,
            request.type,
            request.stage,
            request.discipline,
            request.location
        )

    except ValueError as error:

        return {
            "success": False,
            "message": str(error)
        }

    log_action(
        username=user["username"],
        role=user["role"],
        action="equipment_updated",
        target=f"equipment:{equipment_id}",
        details=request.name
    )

    return {
        "success": True
    }


# =========================================
# MAINTENANCE COMPLETED
# =========================================
# Сбрасывает статус "Внимание"/maintenance_required после того, как
# специалист реально обслужил оборудование. Раньше этот функционал
# существовал в equipment_state_service.py, но не был подключён
# ни к одному роуту — оборудование навсегда оставалось "Внимание".

@router.post("/api/equipment/{equipment_id}/maintenance-completed")
def maintenance_completed_route(
    equipment_id: int,
    user: dict = Depends(
        require_roles(
            "shift_supervisor", "engineer", "chief_engineer",
            "chief_mechanic", "mechanic", "chief_electrician", "electrician"
        )
    )
):

    state = maintenance_completed(equipment_id)

    if state is None:
        return {
            "success": False,
            "message": "Оборудование не найдено."
        }

    log_action(
        username=user["username"],
        role=user["role"],
        action="maintenance_completed",
        target=f"equipment:{equipment_id}"
    )

    return {
        "success": True,
        "equipment": state
    }


# =========================================
# DOWNTIME (простой)
# =========================================
# Те же роли, что и для "Обслуживание выполнено" — кто чинит,
# тот и фиксирует простой/устранение.

DOWNTIME_ROLES = (
    "shift_supervisor", "engineer", "chief_engineer",
    "chief_mechanic", "mechanic", "chief_electrician", "electrician"
)


@router.post("/api/equipment/{equipment_id}/downtime/start")
def start_downtime_route(
    equipment_id: int,
    request: StartDowntimeRequest,
    user: dict = Depends(require_roles(*DOWNTIME_ROLES))
):

    try:

        downtime_id = start_downtime(
            equipment_id=equipment_id,
            reason=request.reason,
            started_by=user["full_name"] or user["username"]
        )

    except ValueError as error:

        return {
            "success": False,
            "message": str(error)
        }

    log_action(
        username=user["username"],
        role=user["role"],
        action="downtime_started",
        target=f"equipment:{equipment_id}",
        details=request.reason
    )

    return {
        "success": True,
        "downtime_id": downtime_id
    }


@router.post("/api/downtime/{downtime_id}/end")
def end_downtime_route(
    downtime_id: int,
    user: dict = Depends(require_roles(*DOWNTIME_ROLES))
):

    try:

        duration_minutes = end_downtime(
            downtime_id=downtime_id,
            ended_by=user["full_name"] or user["username"]
        )

    except ValueError as error:

        return {
            "success": False,
            "message": str(error)
        }

    log_action(
        username=user["username"],
        role=user["role"],
        action="downtime_ended",
        target=f"downtime:{downtime_id}",
        details=f"{duration_minutes} мин"
    )

    return {
        "success": True,
        "duration_minutes": duration_minutes
    }

@router.get("/api/downtime/active")
def get_active_downtimes_route(
    user: dict = Depends(require_roles(*DASHBOARD_ALLOWED_ROLES, *WORK_QUEUE_ROLES))
):

    return {
        "success": True,
        "downtimes": get_active_downtimes()
    }


@router.get("/api/equipment/{equipment_id}/downtime")
def get_equipment_downtime_route(
    equipment_id: int,
    user: dict = Depends(get_current_user)
):

    if user["role"] == "worker":

        allowed_ids = set(get_assigned_equipment_ids(user["id"]))

        if equipment_id not in allowed_ids:
            return {
                "success": False,
                "message": "У вас нет доступа к этому оборудованию."
            }

    return {
        "success": True,
        "history": get_downtime_history(equipment_id=equipment_id)
    }


@router.patch("/api/settings/equipment/{equipment_id}/archive")
def archive_equipment_route(
    equipment_id: int,
    user: dict = Depends(require_roles("admin", "director"))
):
    """Мягкое удаление — is_active=0. Только admin/director."""
    import sqlite3 as _sq
    from backend.config import DB_NAME as _db
    conn = _sq.connect(_db)
    conn.execute("UPDATE equipment SET is_active = 0 WHERE id = ?", (equipment_id,))
    conn.commit()
    conn.close()
    log_action(username=user["username"], role=user["role"],
               action="equipment_archived", target=f"equipment:{equipment_id}")
    return {"success": True}


@router.patch("/api/settings/equipment/{equipment_id}/restore")
def restore_equipment_route(
    equipment_id: int,
    user: dict = Depends(require_roles("admin", "director"))
):
    """Восстановить архивированное оборудование."""
    import sqlite3 as _sq
    from backend.config import DB_NAME as _db
    conn = _sq.connect(_db)
    conn.execute("UPDATE equipment SET is_active = 1 WHERE id = ?", (equipment_id,))
    conn.commit()
    conn.close()
    log_action(username=user["username"], role=user["role"],
               action="equipment_restored", target=f"equipment:{equipment_id}")
    return {"success": True}


# ── Смена статуса оборудования ────────────────────────────
@router.post("/api/equipment/{equipment_id}/status")
def set_equipment_status(
    equipment_id: int,
    request: dict,
    user: dict = Depends(get_current_user)
):
    from backend.services.equipment_service import update_equipment_status
    status = request.get("status")
    if not status:
        return {"success": False, "message": "Статус не указан"}
    update_equipment_status(equipment_id, status)
    log_action(username=user["username"], role=user["role"],
               action="equipment_status_changed",
               target=f"equipment:{equipment_id}", details=status)
    return {"success": True}


@router.post("/api/equipment/{equipment_id}/set-status")
def set_equipment_status_route(
    equipment_id: int,
    request: dict,
    user: dict = Depends(get_current_user)
):
    from backend.services.equipment_service import update_equipment_status
    from backend.services.downtime_service import (
        get_active_downtime_for_equipment,
        end_downtime,
    )

    status = request.get("status")
    if not status:
        raise HTTPException(status_code=400, detail="Статус не указан")

    update_equipment_status(equipment_id, status)

    # Станок вернули в работу — простой закончился. Раньше он закрывался
    # только вместе с обращением, а оно может висеть неделями, пока
    # станок давно крутится: простой копился и врал в аналитике.
    closed_minutes = None
    if status == "Работает":
        active = get_active_downtime_for_equipment(equipment_id)
        if active:
            try:
                closed_minutes = end_downtime(
                    active["id"],
                    ended_by=user.get("full_name") or user["username"],
                )
            except Exception:
                closed_minutes = None

    log_action(username=user["username"], role=user["role"],
        action="equipment_status_changed",
        target=f"equipment:{equipment_id}", details=status)

    if closed_minutes is not None:
        log_action(username=user["username"], role=user["role"],
            action="downtime_closed_by_status",
            target=f"equipment:{equipment_id}",
            details=f"простой закрыт: {closed_minutes} мин")

    return {"success": True, "downtime_closed_minutes": closed_minutes}


# ── Загрузка документа для оборудования ──────────────────

def _register_document(equipment_id, safe_name, filename, user):
    """Документ — в карточку станка (equipment_documents). Оба способа загрузки пишут одинаково."""
    try:
        import sqlite3 as _sq
        from datetime import datetime as _dt
        conn = _sq.connect(DB_NAME)
        conn.execute(
            "INSERT INTO equipment_documents (equipment_id, title, file_path, doc_type, added_by, added_at, is_active) VALUES (?,?,?,?,?,?,1)",
            (equipment_id, filename, f"{safe_name}/{filename}", "manual", user["username"], _dt.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        conn.commit()
        conn.close()
    except Exception as error:
        print(f"[equipment] документ не записан в карточку: {error}")


@router.post("/api/equipment/{equipment_id}/documents/upload-b64")
async def upload_doc_b64(equipment_id: int, request: dict, background_tasks: BackgroundTasks, user: dict = Depends(require_roles("admin","director","chief_engineer","chief_mechanic","chief_electrician"))):
    import base64 as _b64
    equipment = get_equipment(equipment_id)
    if not equipment:
        return {"success": False, "message": "Оборудование не найдено"}
    safe_name = str(equipment["name"]).replace("/", "-")
    from backend.config import DOCS_PATH
    folder = DOCS_PATH / safe_name
    folder.mkdir(parents=True, exist_ok=True)
    filename = safe_filename(request.get("filename"))
    data = request.get("data", "")
    try:
        file_bytes = _b64.b64decode(data)
        if len(file_bytes) > MAX_DOC_BYTES:
            raise HTTPException(status_code=413, detail="Файл больше 50 МБ")
        (folder / filename).write_bytes(file_bytes)
    except Exception as e:
        return {"success": False, "message": str(e)}
    _register_document(equipment_id, safe_name, filename, user)
    from backend.services.quick_ingest import index_uploaded_pdf
    background_tasks.add_task(index_uploaded_pdf, folder / filename, safe_name)

    return {"success": True, "name": filename, "url": f"/docs-files/{safe_name}/{filename}"}


@router.delete("/api/equipment/{equipment_id}/documents/{doc_id}")
def delete_equipment_doc(equipment_id: int, doc_id: int, user: dict = Depends(require_roles("admin","director","chief_engineer","chief_mechanic","chief_electrician"))):
    import sqlite3 as _sq
    conn = _sq.connect(DB_NAME)
    row = conn.execute("SELECT file_path FROM equipment_documents WHERE id=? AND equipment_id=?", (doc_id, equipment_id)).fetchone()
    if row:
        conn.execute("UPDATE equipment_documents SET is_active=0 WHERE id=?", (doc_id,))
        conn.commit()
    conn.close()
    return {"success": True}
