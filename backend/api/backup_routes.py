"""Owner-only backup and restore API."""
from fastapi import APIRouter, Cookie, Depends, HTTPException
from pydantic import BaseModel

from backend.services.auth_service import get_user_by_session
from backend.config import is_owner
from backend.services.backup_service import create_backup, list_backups, prune_backups, restore_backup
from backend.services.audit_service import log_action

router = APIRouter(prefix="/api/backups", tags=["backups"])


def current_user(session_token: str | None = Cookie(default=None)):
    user = get_user_by_session(session_token)
    if user is None:
        raise HTTPException(status_code=401, detail="Не авторизован.")
    return user


def owner_only(user):
    if not is_owner(user):
        raise HTTPException(status_code=403, detail="Резервными копиями управляет только владелец системы.")


class RestoreRequest(BaseModel):
    filename: str


@router.get("")
def backups(user: dict = Depends(current_user)):
    owner_only(user)
    return {"success": True, "backups": list_backups()}


@router.post("/create")
def backup_now(user: dict = Depends(current_user)):
    owner_only(user)
    try:
        result = create_backup(reason="manual")
        prune_backups()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Backup не создан: {exc}")
    log_action(user["username"], user["role"], "backup_created", result["file"], f"reason={result['reason']}")
    return result


@router.post("/restore")
def restore(request: RestoreRequest, user: dict = Depends(current_user)):
    owner_only(user)
    try:
        result = restore_backup(request.filename, user)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Восстановление не выполнено: {exc}")
    log_action(user["username"], user["role"], "backup_restored", request.filename, f"pre_restore={result['pre_restore_backup']}")
    return result
