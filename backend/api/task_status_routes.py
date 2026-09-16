"""
Движение задачи по статусам: взял в работу → отчитался → подтверждено.

Почему отдельным файлом: в main.py были только чтение и создание задач
(GET /api/tasks, POST /api/tasks, GET /api/tasks/{id}) — самих действий
над задачей наружу не выводили вообще. Фронт при этом дёргал
POST /api/tasks/{id}/status, которого не существовало, и кнопка
«Выполнено» молча не работала.

Порядок такой:
    новая ──взял──> в работе ──отчитался+комментарий──> на проверке
                       ^                                    │
                       └────── вернули с замечанием ────────┤
                                                            │
                                                     подтверждено
                                                    (гл. инженер)

Исполнитель обязан написать, что сделал (см. task_service.complete_task):
отметка «выполнено» без единого слова не даёт ни проверить работу, ни
разобраться потом, что именно чинили.
"""

from fastapi import APIRouter, Cookie, Depends, HTTPException
from pydantic import BaseModel

from backend.services.auth_service import get_user_by_session
from backend.services import task_service

router = APIRouter(prefix="/api/tasks", tags=["tasks-status"])

# Подтверждает тот же круг, что принимает работу по ТО.
CONFIRM_ROLES = {"chief_engineer", "director", "admin"}


def current_user(session_token: str | None = Cookie(default=None)):
    user = get_user_by_session(session_token)
    if user is None:
        raise HTTPException(status_code=401, detail="Не авторизован.")
    return user


class CommentPayload(BaseModel):
    comment: str = ""


def _run(action, *args):
    try:
        action(*args)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{task_id}/start")
def start(task_id: int, user: dict = Depends(current_user)):
    _run(task_service.start_task, task_id, user["id"])
    return {"success": True, "task": task_service.get_task(task_id)}


@router.post("/{task_id}/complete")
def complete(task_id: int, payload: CommentPayload, user: dict = Depends(current_user)):
    """Исполнитель отчитывается. Комментарий обязателен."""
    _run(task_service.complete_task, task_id, user["id"], payload.comment)
    return {"success": True, "task": task_service.get_task(task_id)}


@router.post("/{task_id}/confirm")
def confirm(task_id: int, user: dict = Depends(current_user)):
    if user["role"] not in CONFIRM_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Подтверждать выполнение задач может гл. инженер или директор.",
        )
    _run(task_service.confirm_task, task_id, user["id"])
    return {"success": True, "task": task_service.get_task(task_id)}


@router.post("/{task_id}/return")
def send_back(task_id: int, payload: CommentPayload, user: dict = Depends(current_user)):
    if user["role"] not in CONFIRM_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Возвращать задачи на доработку может гл. инженер или директор.",
        )
    _run(task_service.return_task, task_id, user["id"], payload.comment)
    return {"success": True, "task": task_service.get_task(task_id)}


@router.post("/{task_id}/cancel")
def cancel(task_id: int, payload: CommentPayload, user: dict = Depends(current_user)):
    if user["role"] not in CONFIRM_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Отменять задачи может гл. инженер или директор.",
        )
    _run(task_service.cancel_task, task_id, user["id"], payload.comment)
    return {"success": True, "task": task_service.get_task(task_id)}
