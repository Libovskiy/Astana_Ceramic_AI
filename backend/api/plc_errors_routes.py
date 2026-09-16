"""
База кодов ошибок PLC — по производственным линиям (не по станкам,
см. docstring backend/services/plc_error_service.py).

Видят: electrician, chief_electrician, chief_engineer, director, admin.
Редактируют: chief_electrician, chief_engineer, admin.
"""

from fastapi import APIRouter, Cookie, Depends, HTTPException
from pydantic import BaseModel

from backend.services.auth_service import get_user_by_session
from backend.services.plc_error_service import (
    VIEW_ROLES,
    EDIT_ROLES,
    list_errors,
    get_error,
    create_error,
    update_error,
    archive_error,
    list_lines,
    line_names,
    create_line,
    rename_line,
    archive_line,
)

router = APIRouter(prefix="/api/plc-errors", tags=["plc-errors"])


def current_user(session_token: str | None = Cookie(default=None)):
    user = get_user_by_session(session_token)
    if user is None:
        raise HTTPException(status_code=401, detail="Не авторизован.")
    if user["role"] not in VIEW_ROLES:
        raise HTTPException(status_code=403, detail="Нет доступа к базе кодов ошибок PLC.")
    return user


def require_editor(user):
    if user["role"] not in EDIT_ROLES:
        raise HTTPException(status_code=403, detail="Редактировать базу кодов ошибок может только гл. электрик, гл. инженер или admin.")


class ErrorCreate(BaseModel):
    line: str
    code: str
    title: str
    solution: str = ""


class ErrorUpdate(BaseModel):
    title: str
    solution: str = ""


class LinePayload(BaseModel):
    name: str


@router.get("/lines")
def get_lines(user: dict = Depends(current_user)):
    return {
        "success": True,
        "lines": line_names(),
        "lines_full": list_lines(include_counts=True),
        "can_edit": user["role"] in EDIT_ROLES,
    }


@router.post("/lines")
def post_line(payload: LinePayload, user: dict = Depends(current_user)):
    require_editor(user)
    try:
        line = create_line(payload.name, user["username"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"success": True, "line": line}


@router.put("/lines/{line_id}")
def put_line(line_id: int, payload: LinePayload, user: dict = Depends(current_user)):
    require_editor(user)
    try:
        rename_line(line_id, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"success": True}


@router.delete("/lines/{line_id}")
def delete_line(line_id: int, user: dict = Depends(current_user)):
    require_editor(user)
    try:
        archive_line(line_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"success": True}


@router.get("")
def get_errors(line: str | None = None, user: dict = Depends(current_user)):
    return {"success": True, "errors": list_errors(line)}


@router.post("")
def post_error(payload: ErrorCreate, user: dict = Depends(current_user)):
    require_editor(user)

    if payload.line not in line_names():
        raise HTTPException(status_code=400, detail="Неизвестный раздел.")
    if not payload.code.strip() or not payload.title.strip():
        raise HTTPException(status_code=400, detail="Код и название обязательны.")

    try:
        error = create_error(
            payload.line, payload.code, payload.title, payload.solution,
            user["username"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"success": True, "error": error}


@router.put("/{error_id}")
def put_error(error_id: int, payload: ErrorUpdate, user: dict = Depends(current_user)):
    require_editor(user)

    existing = get_error(error_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Код не найден.")
    if not payload.title.strip():
        raise HTTPException(status_code=400, detail="Название обязательно.")

    error = update_error(error_id, payload.title, payload.solution, user["username"])
    return {"success": True, "error": error}


@router.delete("/{error_id}")
def delete_error(error_id: int, user: dict = Depends(current_user)):
    require_editor(user)

    existing = get_error(error_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Код не найден.")

    archive_error(error_id, user["username"])
    return {"success": True}
