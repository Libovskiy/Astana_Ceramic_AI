"""
Задачи: список, создание, карточка.

Вынесено из main.py без изменений поведения.
"""

from fastapi import APIRouter
from backend.services.audit_service import log_action
from backend.services.task_service import create_task, get_task, list_tasks
from fastapi import Depends, HTTPException
from pydantic import BaseModel

from backend.api.common import (
    require_roles,
)

router = APIRouter()

class CreateTaskRequest(BaseModel):
    title: str
    description: str | None = None
    task_type: str = "ordinary"
    priority: str = "normal"
    due_at: str | None = None
    visibility: str = "assignees"
    visibility_role: str | None = None
    equipment_id: int | None = None
    assignee_ids: list[int] = []

# =========================================
# TASK CENTER
# =========================================

TASK_CREATE_ROLES = (
    "director",
    "chief_engineer",
    "production_chief",
    "shift_supervisor",
    "technologist",
    "chief_mechanic",
    "chief_electrician",
    "analyst",
)

TASK_VIEW_ROLES = (
    "director",
    "chief_engineer",
    "production_chief",
    "shift_supervisor",
    "technologist",
    "lab_technician",
    "chief_mechanic",
    "mechanic",
    "chief_electrician",
    "electrician",
    "analyst",
    "worker",
)


@router.get("/api/tasks")
def get_tasks_route(
    status: str | None = None,
    task_type: str | None = None,
    limit: int = 100,
    user: dict = Depends(require_roles(*TASK_VIEW_ROLES)),
):
    if limit < 1:
        limit = 1

    if limit > 200:
        limit = 200

    try:
        tasks = list_tasks(
            user_id=user["id"],
            status=status,
            task_type=task_type,
            limit=limit,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        )

    return {
        "success": True,
        "tasks": tasks,
    }

@router.post("/api/tasks")
def create_task_route(
    request: CreateTaskRequest,
    user: dict = Depends(require_roles(*TASK_CREATE_ROLES)),
):
    try:
        task_id = create_task(
            title=request.title,
            description=request.description,
            task_type=request.task_type,
            priority=request.priority,
            due_at=request.due_at,
            created_by=user["id"],
            visibility=request.visibility,
            visibility_role=request.visibility_role,
            equipment_id=request.equipment_id,
            assignee_ids=request.assignee_ids,
        )
    except ValueError as error:
        return {
            "success": False,
            "message": str(error),
        }

    log_action(
        username=user["username"],
        role=user["role"],
        action="task_created",
        target=f"task:{task_id}",
        details=request.title,
    )

    return {
        "success": True,
        "task_id": task_id,
    }

@router.get("/api/tasks/{task_id}")
def get_task_route(
    task_id: int,
    user: dict = Depends(require_roles(*TASK_VIEW_ROLES)),
):
    task = get_task(task_id)

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Задача не найдена.",
        )

    return {
        "success": True,
        "task": task,
    }
