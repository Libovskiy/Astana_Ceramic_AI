"""
API структуры производства: этапы, оборудование, части, документы.

Опирается на существующий equipment_service (create_equipment,
update_equipment_details) — второй справочник оборудования не
создаётся. Права берутся из существующего regulation_rbac.

Подключается через patch_main.py вместе с остальными роутерами.

Разместить: backend/api/structure_routes.py
"""

import base64
import re

from fastapi import APIRouter, Cookie, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel

from backend.config import DOCS_PATH, BASE_DIR, is_owner
from backend.services.auth_service import get_user_by_session, get_assigned_equipment_ids
from backend.services.audit_service import log_action, log_change, log_change
from backend.services.regulation_rbac import can, why_denied, permissions_for
from backend.services import structure_service as structure
from backend.services import regulation_service as regulations
from backend.services.downtime_service import get_active_downtimes
from backend.services.equipment_service import (
    create_equipment,
    update_equipment_details,
    get_equipment,
)


router = APIRouter(prefix="/api/structure", tags=["structure"])


# Кто правит структуру производства.
#
# Главный инженер — владелец производственной структуры. Он может
# менять этапы, оборудование, части и документы. Технолог, директор,
# главный механик и главный электрик сохраняют свои профильные права.
#
# Лаборант структуру не меняет: его дело замеры.
STRUCTURE_EDIT_ROLES = (
    "technologist", "director", "admin",
    "chief_engineer", "chief_mechanic", "chief_electrician",
)

DOC_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "doc", "docx", "xls", "xlsx"}

MAX_DOC_BYTES = 25 * 1024 * 1024

MAX_PHOTO_BYTES = 5 * 1024 * 1024


def current_user(session_token: str | None = Cookie(default=None)):

    user = get_user_by_session(session_token)

    if user is None:
        raise HTTPException(status_code=401, detail="Не авторизован.")

    return user


def require_view(user):
    if not can(user, "regulation.view"):
        raise HTTPException(status_code=403, detail="Раздел вам не доступен.")


def require_edit(user):
    if not can(user, "structure.edit"):
        raise HTTPException(
            status_code=403,
            detail=(
                "Менять структуру производства могут главный инженер, технолог, "
                "директор, главный механик и главный электрик."
            )
        )

def require_archive_access(user):
    """Архив оборудования доступен только директору и владельцу системы."""
    from backend.config import is_owner

    if user.get("role") == "director":
        return

    if is_owner(user):
        return

    raise HTTPException(
        status_code=403,
        detail="Архивом оборудования могут управлять только владелец системы и директор."
    )

def require_equipment_access(user, equipment_id: int):
    """Рабочий может обращаться только к назначенным ему станкам."""
    if user.get("role") != "worker":
        return

    allowed_ids = set(get_assigned_equipment_ids(user["id"]))
    if equipment_id not in allowed_ids:
        raise HTTPException(status_code=403, detail="У вас нет доступа к этому оборудованию.")


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", (name or "").strip())
    return cleaned[-80:] or "file"


def _decode(content: str, limit: int):

    payload = content

    if "," in payload and payload.strip().startswith("data:"):
        payload = payload.split(",", 1)[1]

    try:
        binary = base64.b64decode(payload, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Файл повреждён при передаче.")

    if len(binary) > limit:
        raise HTTPException(
            status_code=400,
            detail=f"Файл больше {limit // (1024 * 1024)} МБ."
        )

    return binary


# =========================================================
# МОДЕЛИ
# =========================================================

class StageRequest(BaseModel):
    name: str
    description: str | None = None
    sort_order: int | None = None
    reason: str | None = None


class EquipmentRequest(BaseModel):
    name: str
    type: str | None = None
    stage: str | None = None
    discipline: str | None = None
    location: str | None = None
    description: str | None = None
    inventory_number: str | None = None


class PartRequest(BaseModel):
    name: str
    description: str | None = None
    part_number: str | None = None
    status: str | None = None
    note: str | None = None


class PhotoRequest(BaseModel):
    filename: str
    content: str


class DocumentUploadRequest(BaseModel):
    filename: str
    content: str
    title: str | None = None
    doc_type: str = "manual"
    note: str | None = None
    part_id: int | None = None


# =========================================================
# СТРУКТУРА ЦЕЛИКОМ
# =========================================================

@router.get("")
def structure_tree(user: dict = Depends(current_user)):
    """Этап → оборудование → части."""

    require_view(user)

    allowed_ids = get_assigned_equipment_ids(user["id"]) if user.get("role") == "worker" else None

    return {
        "success": True,
        **structure.get_structure(allowed_ids=allowed_ids),
        "can_edit": can(user, "structure.edit"),
        "permissions": permissions_for(user),
    }


# =========================================================
# ЭТАПЫ
# =========================================================

@router.get("/stages")
def stages(user: dict = Depends(current_user)):

    require_view(user)

    stages = structure.get_stages()
    if user.get("role") == "worker":
        allowed_ids = get_assigned_equipment_ids(user["id"])
        visible = structure.get_equipment_list(allowed_ids=allowed_ids)
        visible_keys = {item.get("stage") for item in visible if item.get("stage")}
        stages = [stage for stage in stages if stage["stage_key"] in visible_keys]

    return {
        "success": True,
        "stages": stages,
        "can_edit": can(user, "structure.edit"),
        "can_approve": can(user, "document.approve"),
    }


@router.post("/stages")
def create_stage(request: StageRequest, user: dict = Depends(current_user)):

    require_edit(user)

    try:
        stage_id = structure.create_stage(
            name=request.name,
            description=request.description,
            sort_order=request.sort_order,
            created_by=user.get("full_name") or user["username"],
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    created = next((x for x in structure.get_stages(only_active=False) if int(x["id"]) == stage_id), None)
    log_change(
        username=user["username"], role=user["role"],
        action="stage_created", target=f"stage:{stage_id}",
        before=None, after=created, reason="Создание этапа",
        details=f"Добавлен этап «{request.name}»"
    )

    return {"success": True, "id": stage_id, "stages": structure.get_stages()}


class StageReorderRequest(BaseModel):
    stage_keys: list[str]


class MoveEquipmentRequest(BaseModel):
    new_stage: str
    reason: str


@router.put("/stages/{stage_id}")
def edit_stage(stage_id: int, request: StageRequest, user: dict = Depends(current_user)):
    require_edit(user)

    conn = structure.get_connection()
    before_row = conn.execute(
        "SELECT * FROM production_stages WHERE id = ?", (stage_id,)
    ).fetchone()
    conn.close()
    if not before_row:
        raise HTTPException(status_code=404, detail="Этап не найден.")

    before = dict(before_row)
    try:
        result = structure.rename_stage(stage_id, request.name, request.description)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    after_row = structure.get_stages(only_active=False)
    after = next((x for x in after_row if int(x["id"]) == stage_id), None)
    log_change(
        username=user["username"], role=user["role"],
        action="stage_updated", target=f"stage:{stage_id}",
        before=before, after=after, reason=request.reason,
        details=f"Этап: {before.get('name')} → {request.name}"
    )
    return {"success": True, "stage": after}


@router.post("/stages/reorder")
def reorder_stages(request: StageReorderRequest, user: dict = Depends(current_user)):
    require_edit(user)
    before = [{"stage_key": s["stage_key"], "sort_order": s["sort_order"]} for s in structure.get_stages(only_active=False)]
    try:
        stages = structure.reorder_stages(request.stage_keys)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    after = [{"stage_key": s["stage_key"], "sort_order": s["sort_order"]} for s in stages]
    log_change(
        username=user["username"], role=user["role"],
        action="stages_reordered", target="production_structure",
        before=before, after=after, reason="Изменение порядка этапов",
        details="Изменён порядок производственных этапов"
    )
    return {"success": True, "stages": stages}


@router.delete("/stages/{stage_id}")
def remove_stage(stage_id: int, user: dict = Depends(current_user)):
    """Этап убирается из списка, оборудование на нём остаётся."""

    require_edit(user)

    conn = structure.get_connection()
    row = conn.execute("SELECT * FROM production_stages WHERE id = ?", (stage_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Этап не найден.")
    before = dict(row)
    if not structure.archive_stage(stage_id):
        raise HTTPException(status_code=404, detail="Этап не найден.")
    after = dict(before); after["is_active"] = 0
    log_change(
        username=user["username"], role=user["role"],
        action="stage_archived", target=f"stage:{stage_id}",
        before=before, after=after, reason="Архивирование этапа",
        details=f"Этап «{before.get('name','')}» убран из активной структуры"
    )

    return {"success": True, "stages": structure.get_stages()}


# =========================================================
# ОБОРУДОВАНИЕ
# =========================================================

@router.get("/stages/{stage_key}/overview")
def stage_overview(stage_key: str, user: dict = Depends(current_user)):
    """Единое окно этапа: оборудование, проблемы, простой и история."""

    require_view(user)

    conn = structure.get_connection()
    stage = conn.execute(
        """
        SELECT id, stage_key, name, description, sort_order
        FROM production_stages
        WHERE stage_key = ? AND COALESCE(is_active, 1) = 1
        """,
        (stage_key,),
    ).fetchone()
    if not stage:
        conn.close()
        raise HTTPException(status_code=404, detail="Этап не найден.")

    allowed_ids = get_assigned_equipment_ids(user["id"]) if user.get("role") == "worker" else None
    equipment = structure.get_equipment_list(stage=stage_key, allowed_ids=allowed_ids)
    equipment_ids = [item["id"] for item in equipment]

    cases = []
    if equipment_ids:
        placeholders = ",".join("?" for _ in equipment_ids)
        rows = conn.execute(
            f"""
            SELECT c.id, c.equipment_id, c.machine, c.symptom,
                   c.worker_question, c.status, c.created_at,
                   c.closed_at, e.name AS equipment_name
            FROM cases c
            LEFT JOIN equipment e ON e.id = c.equipment_id
            WHERE c.equipment_id IN ({placeholders})
            ORDER BY c.id DESC
            LIMIT 50
            """,
            equipment_ids,
        ).fetchall()
        cases = [dict(row) for row in rows]

    audit = []
    stage_target = f"stage:{stage["id"]}"
    rows = conn.execute(
        """
        SELECT username, role, action, details, created_at
        FROM audit_log
        WHERE target = ?
        ORDER BY id DESC
        LIMIT 30
        """,
        (stage_target,),
    ).fetchall()
    audit.extend(dict(row) for row in rows)
    conn.close()

    active_downtimes = get_active_downtimes()
    downtime_by_equipment = {
        d.get("equipment_id"): d for d in active_downtimes
    }

    for item in equipment:
        dt = downtime_by_equipment.get(item["id"])
        item["downtime_minutes"] = (dt or {}).get("duration_minutes") if dt else None
        item["is_working"] = item.get("status") == "Работает"

    statuses = {item.get("status") for item in equipment}
    if not equipment:
        status = "Нет данных"
    elif "Ошибка" in statuses or "Критично" in statuses:
        status = "Ошибка"
    elif "Внимание" in statuses:
        status = "Внимание"
    else:
        status = "Работает"

    return {
        "success": True,
        "stage": dict(stage),
        "status": status,
        "equipment": equipment,
        "cases": cases,
        "history": audit,
        "summary": {
            "equipment": len(equipment),
            "working": sum(1 for item in equipment if item.get("status") == "Работает"),
            "attention": sum(1 for item in equipment if item.get("status") in {"Внимание", "Ошибка", "Критично"}),
            "downtime_minutes": sum((item.get("downtime_minutes") or 0) for item in equipment),
        },
    }


@router.get("/equipment")
def equipment_list(stage: str | None = None, user: dict = Depends(current_user)):

    require_view(user)

    allowed_ids = get_assigned_equipment_ids(user["id"]) if user.get("role") == "worker" else None

    return {
        "success": True,
        "equipment": structure.get_equipment_list(stage=stage, allowed_ids=allowed_ids),
        "can_edit": can(user, "structure.edit"),
        "can_approve": can(user, "document.approve"),
    }


@router.post("/equipment")
def add_equipment(request: EquipmentRequest, user: dict = Depends(current_user)):
    """
    Новое оборудование. Идёт через существующий
    equipment_service.create_equipment — второй справочник
    оборудования не заводим.
    """

    require_edit(user)

    try:
        equipment_id = create_equipment(
            name=request.name,
            type_=request.type or "",
            stage=request.stage or "",
            discipline=request.discipline or "both",
            location=request.location,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    structure.update_equipment_extra(
        equipment_id,
        description=request.description,
        inventory_number=request.inventory_number,
    )

    created = get_equipment(equipment_id)
    log_change(
        username=user["username"], role=user["role"],
        action="equipment_created", target=f"equipment:{equipment_id}",
        before=None, after=created, reason="Создание оборудования",
        details=f"Добавлено оборудование «{request.name}»"
    )

    return {"success": True, "id": equipment_id}


@router.put("/equipment/{equipment_id}")
def edit_equipment(equipment_id: int, request: EquipmentRequest,
                   user: dict = Depends(current_user)):

    require_edit(user)

    before = get_equipment(equipment_id)

    if not before:
        raise HTTPException(status_code=404, detail="Оборудование не найдено.")

    try:
        update_equipment_details(
            equipment_id,
            name=request.name,
            type_=request.type or before.get("type"),
            stage=request.stage or before.get("stage"),
            discipline=request.discipline or before.get("discipline"),
            location=request.location if request.location is not None else before.get("location"),
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    structure.update_equipment_extra(
        equipment_id,
        description=request.description,
        inventory_number=request.inventory_number,
    )

    # Пишем «было → стало»: через полгода при разборе это
    # единственный способ понять, кто и что поменял
    changes = []

    for field, label in [("name", "название"), ("type", "тип"),
                         ("stage", "этап"), ("discipline", "дисциплина"),
                         ("location", "расположение")]:
        new_value = getattr(request, field if field != "type" else "type")
        if new_value is not None and str(before.get(field)) != str(new_value):
            changes.append(f"{label}: {before.get(field)} → {new_value}")

    after = get_equipment(equipment_id)
    log_change(
        username=user["username"], role=user["role"],
        action="equipment_updated", target=f"equipment:{equipment_id}",
        before=before, after=after, reason="Изменение оборудования",
        details="; ".join(changes) if changes else "без изменений полей"
    )

    return {"success": True, "changes": changes}


@router.put("/equipment/{equipment_id}/move")
def move_equipment(
    equipment_id: int,
    request: MoveEquipmentRequest,
    user: dict = Depends(current_user)
):
    require_edit(user)

    before = get_equipment(equipment_id)

    if not before:
        raise HTTPException(
            status_code=404,
            detail="Оборудование не найдено."
        )

    try:
        result = structure.move_equipment(
            equipment_id,
            request.new_stage,
            request.reason
        )
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error)
        )

    after = get_equipment(equipment_id)

    log_change(
        username=user["username"],
        role=user["role"],
        action="equipment_moved",
        target=f"equipment:{equipment_id}",
        before=before,
        after=after,
        reason=request.reason,
        details=f"Перенос: {result.get('from_name')} → {result.get('to_name')}"
    )

    return {
        "success": True,
        "result": result,
        "equipment": after
    }

@router.get("/equipment/{equipment_id}/usage")
def equipment_usage(equipment_id: int, user: dict = Depends(current_user)):
    """Где станок уже используется — показываем перед архивацией."""

    require_view(user)
    require_equipment_access(user, equipment_id)

    return {"success": True, "usage": structure.get_equipment_usage(equipment_id)}


@router.delete("/equipment/{equipment_id}")
def archive_equipment(equipment_id: int, user: dict = Depends(current_user)):
    """
    Архивирование, а не удаление: у станка есть обращения,
    простои и замеры, и стирать их вместе с записью нельзя.
    """

    require_archive_access(user)

    before = get_equipment(equipment_id)
    if not before:
        raise HTTPException(status_code=404, detail="Оборудование не найдено.")
    if not structure.archive_equipment(equipment_id):
        raise HTTPException(status_code=404, detail="Оборудование не найдено.")
    usage = structure.get_equipment_usage(equipment_id)
    after = dict(before); after["is_active"] = 0
    log_change(
        username=user["username"], role=user["role"],
        action="equipment_archived", target=f"equipment:{equipment_id}",
        before=before, after=after, reason="Архивирование оборудования",
        details=f"История сохранена: {usage}"
    )

    return {"success": True, "usage": usage}

@router.get("/equipment-archive")
def equipment_archive(user: dict = Depends(current_user)):
    """Список архивного оборудования. Доступ только директору и владельцу."""
    require_archive_access(user)

    return {
        "success": True,
        "equipment": structure.get_equipment_list(include_archived=True)
    }


@router.post("/equipment/{equipment_id}/restore")
def restore_equipment(
    equipment_id: int,
    user: dict = Depends(current_user)
):
    """Восстановление оборудования из архива."""

    require_archive_access(user)

    # Получаем оборудование вместе с архивными записями.
    all_equipment = structure.get_equipment_list(
        include_archived=True
    )

    before = next(
        (
            item
            for item in all_equipment
            if int(item.get("id", 0)) == equipment_id
        ),
        None
    )

    if not before:
        raise HTTPException(
            status_code=404,
            detail="Оборудование не найдено."
        )

    # Восстановить можно только архивную запись.
    if int(before.get("is_active", 1)) == 1:
        raise HTTPException(
            status_code=400,
            detail="Оборудование уже активно."
        )

    restored = structure.restore_equipment(equipment_id)

    if not restored:
        raise HTTPException(
            status_code=404,
            detail="Архивное оборудование не найдено."
        )

    after = next(
        (
            item
            for item in structure.get_equipment_list(
                include_archived=True
            )
            if int(item.get("id", 0)) == equipment_id
        ),
        None
    )

    log_change(
        username=user["username"],
        role=user["role"],
        action="equipment_restored",
        target=f"equipment:{equipment_id}",
        before=before,
        after=after,
        reason="Восстановление оборудования из архива",
        details="Оборудование возвращено в активный список."
    )

    return {
        "success": True,
        "equipment": after
    }

@router.delete("/equipment/{equipment_id}/permanent")
def permanently_delete_equipment(
    equipment_id: int,
    user: dict = Depends(current_user)
):
    """
    Полностью удалить оборудование из базы.

    Доступ только владельцу системы.
    Удалить можно только оборудование,
    которое уже находится в архиве.
    """

    if not is_owner(user):
        raise HTTPException(
            status_code=403,
            detail="Полностью удалять оборудование может только владелец системы."
        )

    all_equipment = structure.get_equipment_list(
        include_archived=True
    )

    before = next(
        (
            item
            for item in all_equipment
            if int(item.get("id", 0)) == equipment_id
        ),
        None
    )

    if not before:
        raise HTTPException(
            status_code=404,
            detail="Оборудование не найдено."
        )

    if int(before.get("is_active", 1)) == 1:
        raise HTTPException(
            status_code=400,
            detail="Активное оборудование нельзя удалить. Сначала отправьте его в архив."
        )

    deleted = structure.permanently_delete_equipment(
        equipment_id
    )

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Архивное оборудование не найдено."
        )

    log_change(
        username=user["username"],
        role=user["role"],
        action="equipment_permanently_deleted",
        target=f"equipment:{equipment_id}",
        before=before,
        after=None,
        reason="Окончательное удаление оборудования из архива",
        details=(
            f"Оборудование «{before.get('name', 'Без названия')}» "
            "окончательно удалено из базы."
        )
    )

    return {
        "success": True,
        "message": "Оборудование окончательно удалено."
    }

@router.post("/equipment/{equipment_id}/photo")
def equipment_photo(equipment_id: int, request: PhotoRequest,
                    user: dict = Depends(current_user)):

    require_edit(user)
    require_equipment_access(user, equipment_id)

    name = _safe_name(request.filename)
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""

    if extension not in {"jpg", "jpeg", "png", "webp"}:
        raise HTTPException(status_code=400, detail="Нужен jpg, png или webp.")

    binary = _decode(request.content, MAX_PHOTO_BYTES)

    folder = BASE_DIR / "frontend" / "static" / "uploads" / "equipment"
    folder.mkdir(parents=True, exist_ok=True)

    target = folder / f"equipment_{equipment_id}.{extension}"
    target.write_bytes(binary)

    web_path = f"/static/uploads/equipment/{target.name}"

    before = get_equipment(equipment_id)
    structure.update_equipment_extra(equipment_id, photo_path=web_path)
    after = get_equipment(equipment_id)
    log_change(
        username=user["username"], role=user["role"],
        action="equipment_photo_updated", target=f"equipment:{equipment_id}",
        before=before, after=after, reason="Обновление фото оборудования",
        details=web_path
    )

    return {"success": True, "photo_path": web_path}


# =========================================================
# ЧАСТИ
# =========================================================

@router.get("/equipment/{equipment_id}/parts")
def parts(equipment_id: int, user: dict = Depends(current_user)):

    require_view(user)
    require_equipment_access(user, equipment_id)

    return {
        "success": True,
        "parts": structure.get_parts(equipment_id),
        "can_edit": can(user, "structure.edit"),
        "can_approve": can(user, "document.approve"),
    }

@router.get("/parts")
def all_parts(user: dict = Depends(current_user)):
    """
    Общий список запчастей для раздела «Запасные части».
    """

    require_view(user)

    allowed_ids = get_assigned_equipment_ids(user["id"]) if user.get("role") == "worker" else None

    return {
        "success": True,
        "parts": structure.get_all_parts(allowed_ids=allowed_ids),
        "can_edit": can(user, "structure.edit"),
        "can_approve": can(user, "document.approve"),
    }

@router.post("/equipment/{equipment_id}/parts")
def add_part(equipment_id: int, request: PartRequest, user: dict = Depends(current_user)):

    require_edit(user)

    try:
        part_id = structure.create_part(
            equipment_id=equipment_id,
            name=request.name,
            created_by=user.get("full_name") or user["username"],
            description=request.description,
            part_number=request.part_number,
            status=request.status,
            note=request.note,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    created = structure.get_part(part_id)
    log_change(
        username=user["username"], role=user["role"],
        action="part_created", target=f"part:{part_id}",
        before=None, after=created, reason="Создание части оборудования",
        details=f"Добавлена часть «{request.name}» к оборудованию {equipment_id}"
    )

    return {"success": True, "id": part_id, "parts": structure.get_parts(equipment_id)}


@router.put("/parts/{part_id}")
def edit_part(part_id: int, request: PartRequest, user: dict = Depends(current_user)):

    require_edit(user)

    try:
        result = structure.update_part(part_id, request.dict(exclude_none=True))
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))

    if result and result["changes"]:
        log_change(
            username=user["username"], role=user["role"],
            action="part_updated", target=f"part:{part_id}",
            before=result.get("before"), after=result.get("after"),
            reason="Изменение части оборудования",
            details="; ".join(
                f"{item['field']}: {item['before']} → {item['after']}"
                for item in result["changes"]
            )
        )

    return {"success": True, "changes": result["changes"] if result else []}


@router.delete("/parts/{part_id}")
def remove_part(part_id: int, user: dict = Depends(current_user)):

    require_edit(user)

    part = structure.get_part(part_id)

    if not part:
        raise HTTPException(status_code=404, detail="Часть не найдена.")

    structure.archive_part(part_id)
    after = dict(part); after["is_active"] = 0
    log_change(
        username=user["username"], role=user["role"],
        action="part_archived", target=f"part:{part_id}",
        before=part, after=after, reason="Архивирование части оборудования",
        details=part["name"]
    )

    return {"success": True}


# =========================================================
# ОБОРУДОВАНИЕ В КОНКРЕТНОМ РЕГЛАМЕНТЕ
# =========================================================

class StageEquipmentRequest(BaseModel):
    equipment_ids: list[int]


@router.get("/regulations/{regulation_id}/stages/{stage_id}/equipment")
def regulation_stage_equipment(
    regulation_id: int,
    stage_id: int,
    user: dict = Depends(current_user),
):
    require_view(user)

    equipment = regulations.get_stage_equipment(
        regulation_id,
        stage_id,
    )

    # Рабочий видит только оборудование,
    # которое назначено именно ему.
    if user.get("role") == "worker":
        allowed_ids = set(
            get_assigned_equipment_ids(user["id"])
        )

        equipment = [
            item
            for item in equipment
            if int(item["id"]) in allowed_ids
        ]

    return {
        "success": True,
        "equipment": equipment,
    }


@router.put("/regulations/{regulation_id}/stages/{stage_id}/equipment")
def update_regulation_stage_equipment(
    regulation_id: int, stage_id: int, request: StageEquipmentRequest,
    user: dict = Depends(current_user)
):
    require_edit(user)
    try:
        items = regulations.set_stage_equipment(
            regulation_id, stage_id, request.equipment_ids,
            changed_by=user.get("full_name") or user["username"]
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    log_action(
        username=user["username"], role=user["role"],
        action="regulation_stage_equipment_changed",
        target=f"regulation:{regulation_id}",
        details=f"stage:{stage_id}; equipment:{request.equipment_ids}"
    )
    return {"success": True, "equipment": items}


# =========================================================
# ДОКУМЕНТЫ
# =========================================================

@router.get("/documents")
def documents(equipment_id: int | None = None, part_id: int | None = None,
              stage_key: str | None = None, user: dict = Depends(current_user)):

    require_view(user)
    if equipment_id is not None:
        require_equipment_access(user, equipment_id)
    elif part_id is not None and user.get("role") == "worker":
        part = structure.get_part(part_id)
        if not part:
            raise HTTPException(status_code=404, detail="Часть не найдена.")
        require_equipment_access(user, int(part["equipment_id"]))
    elif stage_key is not None and user.get("role") == "worker":
        allowed_ids = set(get_assigned_equipment_ids(user["id"]))
        visible = structure.get_equipment_list(stage=stage_key, allowed_ids=allowed_ids)
        if not visible:
            raise HTTPException(status_code=403, detail="У вас нет доступа к этому этапу.")

    items = structure.get_documents(
        equipment_id=equipment_id, part_id=part_id, stage_key=stage_key
    )

    # Проверяем, что файл на месте: его могли переложить или
    # удалить из docs, и битая ссылка хуже честной пометки
    for item in items:
        if item.get("file_path"):
            item["exists"] = (DOCS_PATH / item["file_path"]).exists()
            item["url"] = f"/docs-files/{item['file_path']}"
        else:
            item["exists"] = False
            item["url"] = None

    return {
        "success": True,
        "documents": items,
        "can_edit": can(user, "structure.edit"),
        "can_approve": can(user, "document.approve"),
    }


@router.post("/equipment/{equipment_id}/documents")
def upload_document(equipment_id: int, request: DocumentUploadRequest,
                    user: dict = Depends(current_user)):
    """
    Загрузка документа технологом прямо из браузера.

    Файл ложится в docs/uploads/<станок>/ — ту же папку, которую
    индексирует база знаний. Загруженный PDF попадёт в поиск ИИ
    при следующей пересборке.
    """

    require_edit(user)

    equipment = get_equipment(equipment_id)

    if not equipment:
        raise HTTPException(status_code=404, detail="Оборудование не найдено.")

    name = _safe_name(request.filename)
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""

    if extension not in DOC_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Формат не поддерживается: {', '.join(sorted(DOC_EXTENSIONS))}."
        )

    binary = _decode(request.content, MAX_DOC_BYTES)

    folder_name = _safe_name(equipment["name"])[:60] or f"equipment_{equipment_id}"

    folder = DOCS_PATH / "uploads" / folder_name
    folder.mkdir(parents=True, exist_ok=True)

    target = folder / name

    # Не перезаписываем молча: разные ревизии паспорта часто
    # называются одинаково
    if target.exists():
        stem, counter = target.stem, 2
        while target.exists():
            target = folder / f"{stem}_{counter}.{extension}"
            counter += 1

    target.write_bytes(binary)

    relative = str(target.relative_to(DOCS_PATH))

    uploader = user.get("full_name") or user["username"]
    auto_approve = user.get("role") in {"technologist", "director", "admin"}

    document_id = regulations.attach_document(
        equipment_id=equipment_id,
        part_id=request.part_id,
        title=request.title or target.stem,
        file_path=relative,
        doc_type=request.doc_type,
        note=request.note,
        added_by=uploader,
        status="approved" if auto_approve else "pending",
        knowledge_status="pending" if auto_approve else "blocked",
        approved_by=uploader if auto_approve else None,
        approved_at=regulations.now() if auto_approve else None,
    )

    conn = structure.get_connection()
    doc_row = conn.execute("SELECT * FROM equipment_documents WHERE id = ?", (document_id,)).fetchone()
    conn.close()
    log_change(
        username=user["username"], role=user["role"],
        action="document_uploaded", target=f"document:{document_id}",
        before=None, after=dict(doc_row) if doc_row else None, reason="Загрузка документа",
        details=f"{request.title or target.stem} ({relative})"
    )

    return {
        "success": True,
        "id": document_id,
        "file_path": relative,
        "note": "Файл попадёт в поиск ИИ при следующей пересборке базы знаний.",
    }


class DocumentDecisionRequest(BaseModel):
    status: str


@router.put("/documents/{document_id}/status")
def document_status(
    document_id: int,
    request: DocumentDecisionRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(current_user),
):
    # Главный инженер, технолог, директор и администратор
    # могут принимать решения по документам.
    if not can(user, "document.approve"):
        raise HTTPException(
            status_code=403,
            detail=why_denied("document.approve")
        )

    if request.status not in {"approved", "rejected", "archived"}:
        raise HTTPException(
            status_code=400,
            detail="Можно установить approved, rejected или archived."
        )

    try:
        regulations.update_document_status(
            document_id,
            request.status,
            user.get("full_name") or user["username"]
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))

    conn = structure.get_connection()
    after_row = conn.execute(
        "SELECT * FROM equipment_documents WHERE id = ?",
        (document_id,)
    ).fetchone()
    conn.close()

    log_change(
        username=user["username"],
        role=user["role"],
        action=f"document_{request.status}",
        target=f"document:{document_id}",
        before=None,
        after=dict(after_row) if after_row else None,
        reason=f"Статус документа: {request.status}",
        details=f"document_id={document_id}"
    )

    if request.status == "approved":
        from backend.services.document_ingestion import ingest_document
        background_tasks.add_task(ingest_document, document_id)

    return {
        "success": True,
        "status": request.status,
        "knowledge_status": (
            "pending" if request.status == "approved"
            else "blocked"
        )
    }


@router.post("/stages/{stage_key}/documents")
def upload_stage_document(stage_key: str, request: DocumentUploadRequest, user: dict = Depends(current_user)):
    """Документ, относящийся ко всему этапу, без привязки к станку."""
    require_edit(user)

    name = _safe_name(request.filename)
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if extension not in DOC_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Формат файла не поддерживается.")

    binary = _decode(request.content, MAX_DOC_BYTES)
    folder = DOCS_PATH / "uploads" / "stages" / _safe_name(stage_key)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    if target.exists():
        stem = target.stem
        counter = 2
        while target.exists():
            target = folder / f"{stem}_{counter}.{extension}"
            counter += 1
    target.write_bytes(binary)
    relative = str(target.relative_to(DOCS_PATH))

    uploader = user.get("full_name") or user["username"]
    auto_approve = user.get("role") in {"technologist", "director", "admin"}
    document_id = regulations.attach_document(
        title=request.title or target.stem, file_path=relative,
        doc_type=request.doc_type, note=request.note, added_by=uploader,
        stage_key=stage_key,
        status="approved" if auto_approve else "pending",
        knowledge_status="pending" if auto_approve else "blocked",
        approved_by=uploader if auto_approve else None,
        approved_at=regulations.now() if auto_approve else None,
    )

    conn = structure.get_connection()
    doc_row = conn.execute("SELECT * FROM equipment_documents WHERE id = ?", (document_id,)).fetchone()
    conn.close()
    log_change(
        username=user["username"], role=user["role"],
        action="stage_document_uploaded", target=f"document:{document_id}",
        before=None, after=dict(doc_row) if doc_row else None, reason="Загрузка документа этапа",
        details=f"{request.title or target.stem} ({relative})"
    )
    return {"success": True, "id": document_id, "file_path": relative,
            "status": "approved" if auto_approve else "pending"}


@router.delete("/documents/{document_id}")
def remove_document(document_id: int, user: dict = Depends(current_user)):
    """Документ убирается из списка, файл и запись остаются."""

    require_edit(user)

    before = next((x for x in structure.get_documents(include_archived=True) if int(x["id"]) == document_id), None)
    if not before:
        raise HTTPException(status_code=404, detail="Документ не найден.")
    if not structure.archive_document(document_id):
        raise HTTPException(status_code=404, detail="Документ не найден.")
    after = dict(before); after["is_active"] = 0
    log_change(
        username=user["username"], role=user["role"],
        action="document_archived", target=f"document:{document_id}",
        before=before, after=after, reason="Архивирование документа",
        details=before.get("title") or before.get("name") or "Документ"
    )

    return {"success": True}


# =========================================================
# ИСТОРИЯ ОБЪЕКТА
# =========================================================

@router.get("/history")
def history(target: str, user: dict = Depends(current_user)):
    require_view(user)

    # Рабочий может видеть историю только назначенного оборудования
    # или деталей этого оборудования.
    if user.get("role") == "worker":
        if target.startswith("equipment:"):
            try:
                equipment_id = int(target.split(":", 1)[1])
            except (ValueError, IndexError):
                raise HTTPException(
                    status_code=400,
                    detail="Некорректный target истории.",
                )

            require_equipment_access(user, equipment_id)

        elif target.startswith("part:"):
            try:
                part_id = int(target.split(":", 1)[1])
            except (ValueError, IndexError):
                raise HTTPException(
                    status_code=400,
                    detail="Некорректный target истории.",
                )

            part = structure.get_part(part_id)

            if not part:
                raise HTTPException(
                    status_code=404,
                    detail="Часть не найдена.",
                )

            require_equipment_access(user, int(part["equipment_id"]))

        else:
            raise HTTPException(
                status_code=403,
                detail="У вас нет доступа к этой истории.",
            )

    conn = structure.get_connection()

    rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT username, role, action, details, created_at
            FROM audit_log
            WHERE target = ?
            ORDER BY id DESC
            LIMIT 100
            """,
            (target,),
        ).fetchall()
    ]

    conn.close()

    return {
        "success": True,
        "events": rows,
    }