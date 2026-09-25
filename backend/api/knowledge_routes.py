"""
Знания завода: инструкции, решения из обращений, документация станков.

Три источника, из которых ИИ и человек берут ответ «как чинить». Лежали
на двух страницах, причём одна целиком повторяла половину другой;
сведены в один раздел «Знания» тремя вкладками.

Вынесено из main.py без изменений поведения.
"""

import sqlite3

from fastapi import APIRouter
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
        # Записи системы, потерявшие файл. Перезалить их должен человек.
        "orphans": registry_orphans(),
    }


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
