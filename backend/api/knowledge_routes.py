"""
Знания завода: инструкции, решения из обращений, документация станков.

Три источника, из которых ИИ и человек берут ответ «как чинить». Лежали
на двух страницах, причём одна целиком повторяла половину другой;
сведены в один раздел «Знания» тремя вкладками.

Вынесено из main.py без изменений поведения.
"""

import sqlite3

from fastapi import APIRouter, HTTPException
from backend.services.audit_service import log_action
from backend.services.knowledge_service import get_all_resolutions
from backend.services.procedures_service import (
    create_procedure,
    delete_procedure,
    get_procedure_with_steps,
    get_procedures_by_equipment,
)
from fastapi import Depends
from pydantic import BaseModel

from backend.api.common import (
    get_current_user,
    require_roles,
)
from backend.config import DB_NAME, DOCS_PATH
from backend.services.docs_library_service import registry_orphans, scan_library

router = APIRouter()

class CreateProcedureRequest(BaseModel):

    equipment_id: int

    title: str

    duration_minutes: int | None = None

    target_role: str | None = None

    requires_stop: bool = False

    steps: list[str]


@router.get("/api/knowledge")
def get_knowledge_route(
    user: dict = Depends(get_current_user)
):
    """Видно всем авторизованным — как и Инструкции, это то, что
    реально помогает на месте, не только руководству."""

    return {
        "success": True,
        "grouped": get_all_resolutions()
    }


@router.get("/api/knowledge/documents")
def all_documents(user: dict = Depends(get_current_user)):
    """
    Документация завода — то, что лежит на диске, а не то, что завели.

    В списке документов системы 18 строк, их заводили руками через
    карточку станка. На диске при этом 650 файлов: заводскую
    документацию заливали папками, минуя систему. Вкладка показывала
    шесть и была пустее, чем знает ИИ, — он ищет по этим же папкам.

    Сюда же идут записи, у которых файла нет на месте: не удаляем, а
    показываем отдельно, чтобы было видно, что надо перезалить.

    Файлы отдаются не отсюда, а по /docs-files с проверкой сессии.
    Видно всем авторизованным — как инструкции и решения.
    """

    library = scan_library()

    return {
        "success": True,
        "groups": library["groups"],
        "files_total": library["files_total"],
        "unique": library["unique"],
        "duplicates": library["duplicates"],
        "unlinked": library["unlinked"],
        "empty": library["empty"],
        "replaced": library["replaced"],
        # Кнопка «Загрузить эту страницу» показывается только тому, кто
        # действительно может это сделать: кнопка, которая приводит к
        # «нет прав», хуже её отсутствия.
        "can_upload_page": user["role"] in PAGE_UPLOAD_ROLES,
        # Записи системы, потерявшие файл. Перезалить их должен человек.
        "orphans": registry_orphans(),
    }


class PageUploadRequest(BaseModel):
    """Страница взамен пустой, прямо в ту же папку."""

    # Путь пустого файла относительно docs/ — именно его и заменяем.
    path: str
    filename: str
    content: str


# Кто кладёт документы. Тот же список, что у прикрепления к станку
# (document.attach в regulation_rbac): гл. инженер, гл. механик,
# гл. энергетик, технолог, директор, админ.
PAGE_UPLOAD_ROLES = ("chief_engineer", "chief_mechanic", "chief_electrician",
                     "technologist", "director", "admin")

PAGE_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff",
                 ".doc", ".docx", ".xls", ".xlsx"}

MAX_PAGE_BYTES = 25 * 1024 * 1024


@router.post("/api/knowledge/documents/upload-page")
def upload_page(request: PageUploadRequest,
                user: dict = Depends(require_roles(*PAGE_UPLOAD_ROLES))):
    """
    Загрузить страницу взамен пустой — В ТУ ЖЕ ПАПКУ, где она лежит.

    Зачем отдельно от карточки станка. Четыре пустые страницы паспорта
    ресивера РЕМЕЗА лежат в «Технической базе», и такого станка в
    списке оборудования нет вовсе — ни ресивера, ни компрессорной
    установки среди 49 единиц. Загрузка через карточку кладёт файл в
    uploads/<станок>, то есть в другое место, и пустая страница там не
    закроется никогда: совпадение считается в пределах одной папки.

    Поэтому кладём рядом с пустой. Имя берём её же — тогда пустой файл
    просто перезаписывается, и в списке остаётся одна живая страница.
    """

    import base64
    import re

    root = DOCS_PATH.resolve()

    # Путь пришёл от клиента — проверяем, что он ведёт к файлу внутри
    # docs/, а не «наверх» через ../ и не по ссылке за пределы папки.
    try:
        target_old = (root / request.path).resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="Неверный путь.")

    if not target_old.is_relative_to(root):
        raise HTTPException(status_code=403, detail="Путь за пределами документов.")
    if not target_old.exists():
        raise HTTPException(status_code=404, detail="Страница не найдена.")

    # Заменяем только пустую. Живой документ переписать этой ручкой
    # нельзя: для замены настоящего файла есть карточка станка, где
    # видно, что именно заменяется.
    if target_old.stat().st_size != 0:
        raise HTTPException(status_code=400,
                            detail="Эта страница не пустая — заменять её отсюда нельзя.")

    name = re.sub(r"[^\w.-]", "_", (request.filename or "").strip()).lstrip(".")[-80:]
    suffix = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    if suffix not in PAGE_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail="Формат не поддерживается: " +
                   ", ".join(sorted(s.lstrip('.') for s in PAGE_SUFFIXES)))

    payload = request.content
    if "," in payload and payload.strip().startswith("data:"):
        payload = payload.split(",", 1)[1]
    try:
        binary = base64.b64decode(payload, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Файл повреждён при передаче.")

    if not binary:
        raise HTTPException(status_code=400, detail="Файл пустой — менять пустое на пустое незачем.")
    if len(binary) > MAX_PAGE_BYTES:
        raise HTTPException(status_code=400, detail="Файл больше 25 МБ.")

    # Имя оставляем прежнее, меняем только расширение: так страница
    # закрывает пустую по правилу «тот же станок или та же папка плюс
    # то же имя без расширения».
    target = target_old.with_suffix(suffix)

    # Пишем через временный файл: оборванная загрузка не должна
    # оставить половину страницы вместо пустой.
    temporary = target.with_name(target.name + ".part")
    temporary.write_bytes(binary)
    temporary.replace(target)

    # Пустой файл с другим расширением больше не нужен как файл, но и
    # молча терять его нельзя. Обнулённая страница уже ничего не
    # содержит, поэтому убираем — иначе она так и висела бы в списке.
    if target_old != target and target_old.exists() and target_old.stat().st_size == 0:
        target_old.unlink()

    log_action(
        username=user["username"], role=user["role"],
        action="document_page_uploaded",
        target=f"docs:{target.relative_to(root).as_posix()}",
        details=f"страница загружена взамен пустой ({request.path}), {len(binary)} байт",
    )

    return {"success": True, "path": target.relative_to(root).as_posix(),
            "size_bytes": len(binary)}


PROCEDURE_WRITE_ROLES = ("chief_engineer", "chief_mechanic", "chief_electrician", "admin")


@router.get("/api/procedures")
def get_procedures_route(
    user: dict = Depends(get_current_user)
):
    """Видно всем авторизованным — особенно нужно рабочему/
    механику/электрику на местах, не только руководству."""

    return {
        "success": True,
        "grouped": get_procedures_by_equipment()
    }


@router.get("/api/procedures/{procedure_id}")
def get_procedure_route(
    procedure_id: int,
    user: dict = Depends(get_current_user)
):

    procedure = get_procedure_with_steps(procedure_id)

    if not procedure:
        return {
            "success": False,
            "message": "Инструкция не найдена."
        }

    return {
        "success": True,
        "procedure": procedure
    }


@router.delete("/api/procedures/{procedure_id}")
def delete_procedure_route(
    procedure_id: int,
    user: dict = Depends(require_roles(*PROCEDURE_WRITE_ROLES))
):
    """
    Удаление инструкции. Функция в сервисе была, наружу её не выводили —
    поэтому ошибочно заведённую инструкцию нельзя было убрать.
    """
    procedure = get_procedure_with_steps(procedure_id)

    if not procedure:
        return {"success": False, "message": "Инструкция не найдена."}

    delete_procedure(procedure_id)

    log_action(
        username=user["username"],
        role=user["role"],
        action="procedure_deleted",
        target=f"procedure:{procedure_id}",
        before=procedure,
    )

    return {"success": True}


@router.post("/api/procedures")
def create_procedure_route(
    request: CreateProcedureRequest,
    user: dict = Depends(require_roles(*PROCEDURE_WRITE_ROLES))
):

    try:

        procedure_id = create_procedure(
            equipment_id=request.equipment_id,
            title=request.title,
            duration_minutes=request.duration_minutes,
            target_role=request.target_role,
            requires_stop=request.requires_stop,
            steps=request.steps,
            created_by=user["full_name"] or user["username"]
        )

    except ValueError as error:

        return {
            "success": False,
            "message": str(error)
        }

    log_action(
        username=user["username"],
        role=user["role"],
        action="procedure_created",
        target=f"procedure:{procedure_id}",
        details=request.title
    )

    return {
        "success": True,
        "procedure_id": procedure_id
    }
