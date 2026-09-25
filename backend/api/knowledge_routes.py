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
    Вся документация завода одним списком, с названием станка.

    До этого документы можно было увидеть только в карточке своего
    станка: чтобы узнать, есть ли вообще руководство по печи, надо
    было угадать станок и открыть его. Для вкладки «Документация»
    нужен общий список, иначе раздел «Знания» знает о документах
    меньше, чем о них знает ИИ.

    Видно всем авторизованным — как инструкции и решения: это то, что
    помогает на месте, а не отчётность для руководства.
    """

    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(
            """
            SELECT d.id, d.equipment_id, d.title, d.file_path, d.doc_type,
                   d.note, d.added_by, d.added_at,
                   e.name AS equipment_name, e.location AS zone
            FROM equipment_documents d
            LEFT JOIN equipment e ON e.id = d.equipment_id
            WHERE COALESCE(d.is_active, 1) = 1
            ORDER BY e.name, d.title
            """
        )]
    finally:
        conn.close()

    # Документ мог быть переложен или удалён из docs/ мимо системы.
    # Честное «файла нет» лучше битой ссылки: по ней человек решит,
    # что сломался сайт, и перестанет сюда ходить.
    for item in rows:
        if item.get("file_path"):
            item["exists"] = (DOCS_PATH / item["file_path"]).exists()
            item["url"] = f"/docs-files/{item['file_path']}"
        else:
            item["exists"] = False
            item["url"] = None

    return {
        "success": True,
        "documents": rows,
        "missing": sum(1 for r in rows if not r["exists"]),
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
