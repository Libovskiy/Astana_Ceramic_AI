"""
API модуля «Регламенты».

Права проверяются ЗДЕСЬ, а не только в интерфейсе: скрытая кнопка
не защита. Каждая проверка ссылается на regulation_rbac, чтобы
правила лежали в одном месте, а не расползались по роутам.

Подключение в main.py, после app = FastAPI():

    from backend.api.regulation_routes import router as regulation_router
    app.include_router(regulation_router)

Разместить: backend/api/regulation_routes.py
"""

import base64
import re
from pathlib import Path

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from backend.config import BASE_DIR, DOCS_PATH

from backend.services.auth_service import get_user_by_session
from backend.services.audit_service import log_action
from backend.services.regulation_rbac import can, why_denied, permissions_for
from backend.services import regulation_service as service


router = APIRouter(tags=["regulations"])

templates = Jinja2Templates(directory="frontend/templates")


# =========================================================
# ЗАВИСИМОСТИ
# =========================================================

def current_user(session_token: str | None = Cookie(default=None)):

    user = get_user_by_session(session_token)

    if user is None:
        raise HTTPException(status_code=401, detail="Не авторизован.")

    return user


def require(user, action):
    """Проверка права на backend. Отказ объясняется человеку."""

    if not can(user, action):
        raise HTTPException(status_code=403, detail=why_denied(action))


# =========================================================
# МОДЕЛИ ЗАПРОСОВ
# =========================================================

class RegulationRequest(BaseModel):
    product_type: str
    name: str
    description: str | None = None
    photo_path: str | None = None


class StageRequest(BaseModel):
    name: str
    stage_key: str | None = None
    sort_order: int = 100
    description: str | None = None
    reason: str | None = None


class ParameterRequest(BaseModel):
    data: dict


class StructureReorderRequest(BaseModel):
    items: list[dict]
    reason: str | None = None


class UpdateRequest(BaseModel):
    updates: list
    reason: str


class MeasurementRequest(BaseModel):
    parameter_id: int
    value: float | None = None
    text_value: str | None = None
    batch_ref: str | None = None
    note: str | None = None
    source: str | None = None


class MaintenanceRequest(BaseModel):
    equipment_id: int
    name: str
    interval_days: int
    description: str | None = None
    responsible_role: str | None = None
    procedure_id: int | None = None
    last_done_at: str | None = None


class CompleteRequest(BaseModel):
    note: str | None = None


# =========================================================
# СТРАНИЦА
# =========================================================

@router.get("/regulations")
def regulations_page(request: Request):
    return templates.TemplateResponse(request=request, name="regulations.html")


# =========================================================
# РЕГЛАМЕНТЫ
# =========================================================

@router.get("/api/regulations")
def list_all(user: dict = Depends(current_user)):

    require(user, "regulation.view")

    return {
        "success": True,
        "regulations": service.list_regulations(user=user),
        "permissions": permissions_for(user),
        "pending_ack": service.pending_ack(user),
    }


@router.post("/api/regulations")
def create(request: RegulationRequest, user: dict = Depends(current_user)):

    require(user, "regulation.create")

    regulation_id = service.create_regulation(
        product_type=request.product_type,
        name=request.name,
        created_by=user.get("full_name") or user["username"],
        description=request.description,
        photo_path=request.photo_path,
    )

    log_action(
        username=user["username"], role=user["role"],
        action="regulation_created", target=f"regulation:{regulation_id}",
        details=f"{request.product_type} — {request.name}"
    )

    return {"success": True, "id": regulation_id}


@router.get("/api/regulations/{regulation_id}")
def detail(regulation_id: int, user: dict = Depends(current_user)):

    require(user, "regulation.view")

    regulation = service.get_regulation(regulation_id, user=user)

    if not regulation:
        raise HTTPException(status_code=404, detail="Регламент не найден.")

    return {
        "success": True,
        "regulation": regulation,
        "versions": service.get_versions(regulation["product_type"]),
        "ack": service.get_ack_status(regulation_id, regulation["version"], user),
        "permissions": permissions_for(user),
    }


@router.post("/api/regulations/{regulation_id}/stages")
def create_stage(regulation_id: int, request: StageRequest, user: dict = Depends(current_user)):

    require(user, "regulation.edit")

    try:
        result = service.add_stage(
            regulation_id, request.name,
            stage_key=request.stage_key,
            sort_order=request.sort_order,
            description=request.description,
            changed_by=user.get("full_name") or user["username"],
            changed_role=user.get("role"),
            reason=request.reason,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    log_action(username=user["username"], role=user["role"],
               action="regulation_stage_added", target=f"regulation:{result['regulation_id']}",
               details=request.name)
    return {"success": True, "id": result["stage_id"], **result}


@router.put("/api/regulations/{regulation_id}/stages/{stage_id}")
def edit_stage(regulation_id: int, stage_id: int, request: StageRequest, user: dict = Depends(current_user)):
    require(user, "regulation.edit")
    try:
        result = service.update_stage(
            regulation_id, stage_id,
            {"name": request.name, "stage_key": request.stage_key,
             "sort_order": request.sort_order, "description": request.description},
            reason=request.reason or "Изменение этапа",
            changed_by=user.get("full_name") or user["username"],
            changed_role=user.get("role"),
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    log_action(username=user["username"], role=user["role"], action="regulation_stage_changed",
               target=f"regulation:{result['regulation_id']}", details=request.name)
    return {"success": True, **result}


@router.delete("/api/regulations/{regulation_id}/stages/{stage_id}")
def delete_stage(regulation_id: int, stage_id: int, reason: str = "", user: dict = Depends(current_user)):
    require(user, "regulation.edit")
    try:
        result = service.archive_stage(regulation_id, stage_id, reason,
                                       user.get("full_name") or user["username"], user.get("role"))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    log_action(username=user["username"], role=user["role"], action="regulation_stage_archived",
               target=f"regulation:{result['regulation_id']}", details=reason)
    return {"success": True, **result}


@router.post("/api/regulations/{regulation_id}/stages/reorder")
def reorder_stages(regulation_id: int, request: StructureReorderRequest, user: dict = Depends(current_user)):
    require(user, "regulation.edit")
    try:
        result = service.reorder_stages(
            regulation_id, request.items, request.reason,
            user.get("full_name") or user["username"], user.get("role")
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    log_action(
        username=user["username"], role=user["role"],
        action="regulation_stages_reordered",
        target=f"regulation:{result['regulation_id']}",
        details=f"Изменено этапов: {len(result['changed'])}"
    )
    return {"success": True, **result}


@router.post("/api/regulations/{regulation_id}/parameters/reorder")
def reorder_parameters(regulation_id: int, request: StructureReorderRequest, user: dict = Depends(current_user)):
    require(user, "regulation.edit")
    try:
        result = service.reorder_parameters(
            regulation_id, request.items, request.reason,
            user.get("full_name") or user["username"], user.get("role")
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    log_action(
        username=user["username"], role=user["role"],
        action="regulation_parameters_reordered",
        target=f"regulation:{result['regulation_id']}",
        details=f"Изменено параметров: {len(result['changed'])}"
    )
    return {"success": True, **result}


@router.post("/api/regulations/{regulation_id}/parameters")
def create_parameter(regulation_id: int, request: ParameterRequest, user: dict = Depends(current_user)):

    require(user, "regulation.edit")

    try:
        result = service.add_parameter(
            regulation_id,
            request.data,
            changed_by=user.get("full_name") or user["username"],
            changed_role=user.get("role"),
            reason=request.data.get("_reason"),
        )
        parameter_id = result["parameter_id"]
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    log_action(
        username=user["username"], role=user["role"],
        action="regulation_parameter_added", target=f"regulation:{regulation_id}",
        details=request.data.get("name")
    )

    return {
        "success": True,
        "id": parameter_id,
        "regulation_id": result["regulation_id"],
        "version_created": result["version_created"],
    }


@router.delete("/api/regulations/{regulation_id}/parameters/{parameter_id}")
def delete_parameter(regulation_id: int, parameter_id: int, reason: str = "", user: dict = Depends(current_user)):
    require(user, "regulation.edit")
    try:
        result = service.archive_parameter(regulation_id, parameter_id, reason,
                                           user.get("full_name") or user["username"], user.get("role"))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    log_action(username=user["username"], role=user["role"], action="regulation_parameter_archived",
               target=f"regulation:{result['regulation_id']}", details=reason)
    return {"success": True, **result}


@router.post("/api/regulations/{regulation_id}/activate")
def activate(regulation_id: int, user: dict = Depends(current_user)):

    require(user, "regulation.activate")

    try:
        service.activate(regulation_id, user.get("full_name") or user["username"])
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))

    log_action(
        username=user["username"], role=user["role"],
        action="regulation_activated", target=f"regulation:{regulation_id}"
    )

    return {"success": True}


@router.post("/api/regulations/{regulation_id}/update")
def update(regulation_id: int, request: UpdateRequest, user: dict = Depends(current_user)):
    """
    Изменение норм. Создаёт новую версию, архивирует старую,
    пишет «было → стало» и причину в журнал.
    """

    require(user, "regulation.edit")

    try:
        result = service.update_parameters(
            regulation_id,
            updates=request.updates,
            reason=request.reason,
            changed_by=user.get("full_name") or user["username"],
            changed_role=user["role"],
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    log_action(
        username=user["username"], role=user["role"],
        action="regulation_changed",
        target=f"regulation:{result['regulation_id']}",
        details=f"причина: {request.reason} | " + "; ".join(
            f"{item['parameter']} {item['field']}: {item['before']} → {item['after']}"
            for item in result["changes"]
        )
    )

    return {"success": True, **result}


# Отдельный префикс, а не /api/regulations/{product_type}/versions:
# иначе FastAPI не отличит "1.4 Пустотелый" от числового id и будет
# ловить оба пути одним роутом.
@router.get("/api/regulation-versions/{product_type}")
def versions(product_type: str, user: dict = Depends(current_user)):

    require(user, "regulation.view")

    return {"success": True, "versions": service.get_versions(product_type)}


# =========================================================
# ОЗНАКОМЛЕНИЕ
# =========================================================

@router.post("/api/regulations/{regulation_id}/ack")
def acknowledge(regulation_id: int, user: dict = Depends(current_user)):

    regulation = service.get_regulation(regulation_id, with_parameters=False)

    if not regulation:
        raise HTTPException(status_code=404, detail="Регламент не найден.")

    try:
        service.acknowledge(regulation_id, regulation["version"], user)
    except ValueError as error:
        raise HTTPException(status_code=403, detail=str(error))

    log_action(
        username=user["username"], role=user["role"],
        action="regulation_acknowledged",
        target=f"regulation:{regulation_id}",
        details=f"версия {regulation['version']}"
    )

    return {"success": True}


# =========================================================
# ЗАМЕРЫ
# =========================================================

@router.post("/api/measurements")
def add_measurement(request: MeasurementRequest, user: dict = Depends(current_user)):

    require(user, "measurement.create")

    try:
        result = service.add_measurement(
            parameter_id=request.parameter_id,
            value=request.value,
            text_value=request.text_value,
            measured_by=user.get("full_name") or user["username"],
            source=request.source,
            batch_ref=request.batch_ref,
            note=request.note,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    return {"success": True, **result}


@router.get("/api/measurements")
def list_measurements(
    parameter_id: int | None = None,
    equipment_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    user: dict = Depends(current_user)
):

    require(user, "measurement.view")

    return {
        "success": True,
        "measurements": service.get_measurements(
            parameter_id=parameter_id,
            equipment_id=equipment_id,
            date_from=date_from,
            date_to=date_to,
        )
    }


@router.put("/api/measurements/{measurement_id}")
def edit_measurement(measurement_id: int, user: dict = Depends(current_user)):
    """
    Правка внесённого замера.

    Лаборанта здесь нет намеренно: исправлять свой же замер задним
    числом — тихий способ подогнать результат. Ошибся — вносит
    новый, старый остаётся в истории.
    """

    require(user, "measurement.edit")

    raise HTTPException(
        status_code=400,
        detail=(
            "Замер не редактируется даже технологом. Внесите новый — "
            "старый останется в истории с пометкой времени."
        )
    )


# =========================================================
# ПАСПОРТ ОБОРУДОВАНИЯ
# =========================================================

@router.get("/api/equipment/{equipment_id}/passport")
def passport(equipment_id: int, user: dict = Depends(current_user)):
    """
    Параметры действующего регламента для этого станка, последний
    факт по каждому, документы и планы обслуживания.
    """

    require(user, "regulation.view")

    result = service.get_equipment_passport(equipment_id)

    if not result:
        raise HTTPException(status_code=404, detail="Станок не найден.")

    result["permissions"] = permissions_for(user)
    result["success"] = True

    return result


# =========================================================
# ОБСЛУЖИВАНИЕ
# =========================================================

@router.get("/api/maintenance")
def maintenance(days_ahead: int = 14, user: dict = Depends(current_user)):

    require(user, "maintenance.view")

    return {
        "success": True,
        **service.get_due_maintenance(days_ahead=days_ahead),
        "can_complete": can(user, "maintenance.complete"),
        "can_create": can(user, "maintenance.create"),
    }


@router.post("/api/maintenance")
def create_maintenance(request: MaintenanceRequest, user: dict = Depends(current_user)):

    require(user, "maintenance.create")

    try:
        plan_id = service.create_plan(
            equipment_id=request.equipment_id,
            name=request.name,
            interval_days=request.interval_days,
            created_by=user.get("full_name") or user["username"],
            description=request.description,
            responsible_role=request.responsible_role,
            procedure_id=request.procedure_id,
            last_done_at=request.last_done_at,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    log_action(
        username=user["username"], role=user["role"],
        action="maintenance_plan_created", target=f"maintenance:{plan_id}",
        details=f"{request.name}, раз в {request.interval_days} дн."
    )

    return {"success": True, "id": plan_id}


@router.post("/api/maintenance/{plan_id}/complete")
def complete(plan_id: int, request: CompleteRequest, user: dict = Depends(current_user)):

    require(user, "maintenance.complete")

    try:
        result = service.complete_maintenance(
            plan_id,
            done_by=user.get("full_name") or user["username"],
            note=request.note,
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))

    log_action(
        username=user["username"], role=user["role"],
        action="maintenance_completed", target=f"maintenance:{plan_id}",
        details=request.note
    )

    return {"success": True, **result}

# =========================================================
# ФОТО ПРОДУКЦИИ
# =========================================================
# Кладём в frontend/static/uploads/products — эта папка уже
# раздаётся существующим монтированием /static. Своей системы
# хранения не заводим.
#
# Файл приходит строкой base64, а не multipart. Причина
# практическая: multipart в FastAPI требует пакет python-multipart,
# и если его нет в окружении, сервер упадёт при СТАРТЕ, а не при
# загрузке файла. Ронять работающую систему ради формы загрузки
# фотографии нельзя.

UPLOAD_DIR = BASE_DIR / "frontend" / "static" / "uploads" / "products"

ALLOWED_IMAGE = {"jpg", "jpeg", "png", "webp"}

MAX_IMAGE_BYTES = 5 * 1024 * 1024


class PhotoRequest(BaseModel):
    filename: str
    # data:image/jpeg;base64,.... или чистый base64
    content: str


def _safe_name(name: str) -> str:
    """Только буквы, цифры, дефис и точка — чтобы имя файла не увело
    запись за пределы папки."""

    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", name.strip())

    return cleaned[-80:] or "photo"


@router.post("/api/regulations/{regulation_id}/photo")
def upload_photo(regulation_id: int, request: PhotoRequest, user: dict = Depends(current_user)):

    require(user, "regulation.edit")

    regulation = service.get_regulation(regulation_id, with_parameters=False)

    if not regulation:
        raise HTTPException(status_code=404, detail="Регламент не найден.")

    name = _safe_name(request.filename)
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""

    if extension not in ALLOWED_IMAGE:
        raise HTTPException(
            status_code=400,
            detail=f"Формат не поддерживается. Нужен один из: {', '.join(sorted(ALLOWED_IMAGE))}."
        )

    payload = request.content

    if "," in payload and payload.strip().startswith("data:"):
        payload = payload.split(",", 1)[1]

    try:
        binary = base64.b64decode(payload, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Файл повреждён при передаче.")

    if len(binary) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="Файл больше 5 МБ.")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    target = UPLOAD_DIR / f"regulation_{regulation_id}.{extension}"

    target.write_bytes(binary)

    # Путь для браузера через уже существующее монтирование /static
    web_path = f"/static/uploads/products/{target.name}"

    service.set_photo(regulation_id, web_path)

    log_action(
        username=user["username"], role=user["role"],
        action="regulation_photo_uploaded", target=f"regulation:{regulation_id}",
        details=target.name
    )

    return {"success": True, "photo_path": web_path}


# =========================================================
# ДОКУМЕНТЫ ОБОРУДОВАНИЯ
# =========================================================
# Работают через ту же папку docs/, из которой собирается база
# знаний, и раздаются существующим монтированием /docs-files.
# Выдуманных документов не создаём: показываем то, что реально
# лежит на диске.


class DocumentRequest(BaseModel):
    title: str
    file_path: str
    doc_type: str = "manual"
    page_from: int | None = None
    note: str | None = None


@router.get("/api/equipment/{equipment_id}/documents")
def documents(equipment_id: int, user: dict = Depends(current_user)):

    require(user, "regulation.view")

    attached = service.get_documents(equipment_id)

    # Проверяем, что файл всё ещё на месте: документ мог быть
    # переложен или удалён из docs/, и лучше честно показать
    # "файл не найден", чем битую ссылку.
    for item in attached:
        if item.get("file_path"):
            item["exists"] = (DOCS_PATH / item["file_path"]).exists()
            item["url"] = f"/docs-files/{item['file_path']}"
        else:
            item["exists"] = False
            item["url"] = None

    return {
        "success": True,
        "documents": attached,
        "can_attach": can(user, "document.attach"),
    }


@router.get("/api/docs-library")
def docs_library(search: str = "", user: dict = Depends(current_user)):
    """
    Что реально лежит в docs/ — чтобы прикреплять существующие
    файлы, а не выдумывать новые.
    """

    require(user, "regulation.view")

    if not DOCS_PATH.exists():
        return {"success": True, "files": []}

    files = []

    for path in sorted(DOCS_PATH.rglob("*")):

        if not path.is_file():
            continue

        if path.suffix.lower() not in (".pdf", ".jpg", ".jpeg", ".png", ".doc", ".docx", ".xls", ".xlsx"):
            continue

        relative = str(path.relative_to(DOCS_PATH))

        if search and search.lower() not in relative.lower():
            continue

        files.append({
            "path": relative,
            "name": path.name,
            "folder": str(path.parent.relative_to(DOCS_PATH)),
            "size_kb": round(path.stat().st_size / 1024),
        })

        if len(files) >= 300:
            break

    return {"success": True, "files": files}


@router.post("/api/equipment/{equipment_id}/documents")
def attach_document(equipment_id: int, request: DocumentRequest, user: dict = Depends(current_user)):

    require(user, "document.attach")

    if not (DOCS_PATH / request.file_path).exists():
        raise HTTPException(
            status_code=400,
            detail="Такого файла нет в папке docs. Сначала положите документ туда."
        )

    document_id = service.attach_document(
        equipment_id=equipment_id,
        title=request.title,
        file_path=request.file_path,
        doc_type=request.doc_type,
        page_from=request.page_from,
        note=request.note,
        added_by=user.get("full_name") or user["username"],
    )

    log_action(
        username=user["username"], role=user["role"],
        action="equipment_document_attached", target=f"equipment:{equipment_id}",
        details=request.title
    )

    return {"success": True, "id": document_id}

# =========================================================
# ЗАГРУЗКА ДОКУМЕНТА ТЕХНОЛОГОМ
# =========================================================
# Раньше документы можно было только прикрепить из того, что уже
# лежит в docs/ — то есть кто-то должен был положить файл на
# сервер руками. Теперь технолог загружает сам через браузер.
#
# Файл ложится в docs/uploads/<станок>/ — внутрь той же папки,
# которую индексирует база знаний. Загруженный PDF попадёт в
# поиск при следующей пересборке, и это правильно: паспорт станка
# полезен ИИ не меньше, чем человеку.

DOC_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "doc", "docx", "xls", "xlsx"}

MAX_DOC_BYTES = 25 * 1024 * 1024


class DocumentUploadRequest(BaseModel):
    filename: str
    content: str
    title: str | None = None
    doc_type: str = "manual"
    note: str | None = None


@router.post("/api/equipment/{equipment_id}/documents/upload")
def upload_document(equipment_id: int, request: DocumentUploadRequest,
                    user: dict = Depends(current_user)):

    require(user, "document.attach")

    name = _safe_name(request.filename)
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""

    if extension not in DOC_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Формат не поддерживается. Нужен один из: {', '.join(sorted(DOC_EXTENSIONS))}."
        )

    payload = request.content

    if "," in payload and payload.strip().startswith("data:"):
        payload = payload.split(",", 1)[1]

    try:
        binary = base64.b64decode(payload, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Файл повреждён при передаче.")

    if len(binary) > MAX_DOC_BYTES:
        raise HTTPException(status_code=400, detail="Файл больше 25 МБ.")

    # Папка по имени станка — чтобы в docs/ не образовалась свалка
    import sqlite3
    from backend.config import DB_NAME

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    equipment = conn.execute(
        "SELECT name FROM equipment WHERE id = ?", (equipment_id,)
    ).fetchone()
    conn.close()

    if not equipment:
        raise HTTPException(status_code=404, detail="Станок не найден.")

    folder_name = _safe_name(equipment["name"])[:60] or f"equipment_{equipment_id}"

    folder = DOCS_PATH / "uploads" / folder_name
    folder.mkdir(parents=True, exist_ok=True)

    target = folder / name

    # Не перезаписываем молча: одинаковые имена у разных ревизий
    # паспорта — обычное дело
    if target.exists():
        stem = target.stem
        counter = 2
        while target.exists():
            target = folder / f"{stem}_{counter}.{extension}"
            counter += 1

    target.write_bytes(binary)

    relative = str(target.relative_to(DOCS_PATH))

    document_id = service.attach_document(
        equipment_id=equipment_id,
        title=request.title or target.stem,
        file_path=relative,
        doc_type=request.doc_type,
        note=request.note,
        added_by=user.get("full_name") or user["username"],
    )

    log_action(
        username=user["username"], role=user["role"],
        action="equipment_document_uploaded", target=f"equipment:{equipment_id}",
        details=f"{request.title or target.stem} ({relative})"
    )

    return {
        "success": True,
        "id": document_id,
        "file_path": relative,
        "note": "Файл попадёт в поиск ИИ при следующей пересборке базы знаний.",
    }


# =========================================================
# СОСТАВ ШИХТЫ
# =========================================================


class MixRequest(BaseModel):
    values: dict
    batch_ref: str | None = None
    note: str | None = None


@router.get("/api/regulations/{regulation_id}/mix")
def mix(regulation_id: int, user: dict = Depends(current_user)):

    require(user, "regulation.view")

    return {
        "success": True,
        **service.get_mix(regulation_id),
        "can_measure": can(user, "measurement.create"),
    }


@router.post("/api/regulations/{regulation_id}/mix/measure")
def mix_measure(regulation_id: int, request: MixRequest, user: dict = Depends(current_user)):
    """Ручной ввод фактической дозировки — все компоненты разом."""

    require(user, "measurement.create")

    try:
        result = service.save_mix_measurement(
            regulation_id,
            values=request.values,
            measured_by=user.get("full_name") or user["username"],
            batch_ref=request.batch_ref,
            note=request.note,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    return {"success": True, **result}


# =========================================================
# СОСТОЯНИЕ ЭТАПОВ
# =========================================================

@router.get("/api/regulations/{regulation_id}/stages-state")
def stages_state(regulation_id: int, user: dict = Depends(current_user)):

    require(user, "regulation.view")

    return {
        "success": True,
        "stages": service.get_stage_stats(regulation_id),
        "uncontrolled": service.count_uncontrolled(regulation_id),
    }

