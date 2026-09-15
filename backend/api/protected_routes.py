"""Критические удаления ACAI: запрос -> решение владельца -> backup -> delete."""

import sqlite3
from datetime import datetime
from fastapi import APIRouter, Cookie, Depends, HTTPException
from pydantic import BaseModel

from backend.config import DB_NAME, is_owner
from backend.services.auth_service import get_user_by_session
from backend.services.protection_service import (
    ProtectionError,
    PROTECTED,
    DELETE_REQUEST_ROLES,
    get_connection,
    init_protection_tables,
    request_delete,
    list_delete_requests,
    decide_delete,
    owners_info,
    backup_database,
)
from backend.services.procedures_service import get_procedure_with_steps

router = APIRouter(prefix="/api/protected", tags=["protected"])


def current_user(session_token: str | None = Cookie(default=None)):
    user = get_user_by_session(session_token)
    if user is None:
        raise HTTPException(status_code=401, detail="Не авторизован.")
    return user


class DecisionRequest(BaseModel):
    comment: str | None = None


@router.get("/info")
def info(user: dict = Depends(current_user)):
    return {
        "success": True,
        "you_are_owner": is_owner(user),
        "can_request_delete": user.get("role") in DELETE_REQUEST_ROLES or is_owner(user),
        **owners_info(),
    }


@router.get("/delete-requests")
def delete_requests(status: str | None = "pending", user: dict = Depends(current_user)):
    if not is_owner(user):
        raise HTTPException(status_code=403, detail="Очередь критических удалений доступна только владельцу.")
    return {"success": True, "requests": list_delete_requests(status=status)}


@router.post("/delete-requests/{request_id}/reject")
def reject_delete(request_id: int, request: DecisionRequest, user: dict = Depends(current_user)):
    try:
        result = decide_delete(request_id, user, approve=False, comment=request.comment)
    except ProtectionError as error:
        raise HTTPException(status_code=403, detail=str(error))
    return {"success": True, **result}


@router.post("/delete-requests/{request_id}/approve")
def approve_delete(request_id: int, request: DecisionRequest, user: dict = Depends(current_user)):
    try:
        result = decide_delete(request_id, user, approve=True, comment=request.comment)
    except ProtectionError as error:
        raise HTTPException(status_code=403, detail=str(error))
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Не удалось выполнить удаление: {error}")
    return {"success": True, **result}


# =========================================================
# БАЗА ЗНАНИЙ
# =========================================================

@router.post("/knowledge/{entry_id}/delete-request")
def request_knowledge_delete(
    entry_id: int,
    request: DecisionRequest,
    user: dict = Depends(current_user),
):
    """
    Старый механизм удаления БЗ отключён.

    База знаний теперь удаляется только через:
    1. archive
    2. permanent delete для admin/director
    """
    raise HTTPException(
        status_code=410,
        detail=(
            "Старый механизм удаления базы знаний отключён. "
            "Сначала архивируйте запись, затем используйте "
            "окончательное удаление из архива."
        ),
    )



# =========================================================
# БАЗА ЗНАНИЙ — АРХИВ
# =========================================================

KNOWLEDGE_ARCHIVE_ROLES = {
    "admin",
    "director",
    "chief_engineer",
    "technologist",
    "chief_mechanic",
    "chief_electrician",
}


def can_archive_knowledge(user):
    """
    Архивировать записи базы знаний могут только
    руководящие роли.
    """
    return user.get("role") in KNOWLEDGE_ARCHIVE_ROLES or is_owner(user)


def can_manage_knowledge_archive(user):
    """
    Просматривать архив, восстанавливать и удалять навсегда
    могут только admin и director.
    """
    return user.get("role") in {"admin", "director"} or is_owner(user)


@router.post("/knowledge/{entry_id}/archive")
def archive_knowledge(
    entry_id: int,
    request: DecisionRequest,
    user: dict = Depends(current_user)
):
    """
    Мягкое удаление БЗ.

    Физически запись НЕ удаляется.
    Она переводится в archived.
    """
    if not can_archive_knowledge(user):
        raise HTTPException(
            status_code=403,
            detail="Архивировать базу знаний могут только руководящие роли."
        )

    conn = get_connection()

    row = conn.execute(
        "SELECT * FROM resolution_knowledge_base WHERE id = ?",
        (entry_id,)
    ).fetchone()

    if not row:
        conn.close()
        raise HTTPException(
            status_code=404,
            detail="Запись базы знаний не найдена."
        )

    if row["status"] == "archived":
        conn.close()
        raise HTTPException(
            status_code=409,
            detail="Запись уже находится в архиве."
        )

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    columns = {
        r[1]
        for r in conn.execute(
            "PRAGMA table_info(resolution_knowledge_base)"
        ).fetchall()
    }

    # Добавляем служебные поля миграцией, если их ещё нет.
    if "archived_by" not in columns:
        conn.execute(
            "ALTER TABLE resolution_knowledge_base "
            "ADD COLUMN archived_by TEXT"
        )

    if "archived_at" not in columns:
        conn.execute(
            "ALTER TABLE resolution_knowledge_base "
            "ADD COLUMN archived_at TEXT"
        )

    if "archive_reason" not in columns:
        conn.execute(
            "ALTER TABLE resolution_knowledge_base "
            "ADD COLUMN archive_reason TEXT"
        )

    conn.execute(
        """
        UPDATE resolution_knowledge_base
        SET
            status = 'archived',
            archived_by = ?,
            archived_at = ?,
            archive_reason = ?
        WHERE id = ?
        """,
        (
            user.get("username"),
            now,
            request.comment,
            entry_id,
        )
    )

    conn.commit()
    conn.close()

    _log_archive = None

    try:
        from backend.services.audit_service import log_action

        log_action(
            username=user.get("username"),
            role=user.get("role"),
            action="knowledge_archived",
            target=f"knowledge:{entry_id}",
            details=(
                f"Запись БЗ архивирована. "
                f"Причина: {request.comment or 'не указана'}"
            ),
        )
    except Exception:
        pass

    return {
        "success": True,
        "id": entry_id,
        "status": "archived",
    }


@router.get("/knowledge/archived")
def get_archived_knowledge(
    user: dict = Depends(current_user)
):
    """
    Архив БЗ доступен только admin/director.
    """
    if not can_manage_knowledge_archive(user):
        raise HTTPException(
            status_code=403,
            detail="Архив базы знаний доступен только администратору и директору."
        )

    conn = get_connection()

    columns = {
        r[1]
        for r in conn.execute(
            "PRAGMA table_info(resolution_knowledge_base)"
        ).fetchall()
    }

    if "archived_by" not in columns:
        conn.execute(
            "ALTER TABLE resolution_knowledge_base "
            "ADD COLUMN archived_by TEXT"
        )

    if "archived_at" not in columns:
        conn.execute(
            "ALTER TABLE resolution_knowledge_base "
            "ADD COLUMN archived_at TEXT"
        )

    if "archive_reason" not in columns:
        conn.execute(
            "ALTER TABLE resolution_knowledge_base "
            "ADD COLUMN archive_reason TEXT"
        )

    conn.commit()

    rows = conn.execute(
        """
        SELECT *
        FROM resolution_knowledge_base
        WHERE status = 'archived'
        ORDER BY archived_at DESC, id DESC
        """
    ).fetchall()

    conn.close()

    return {
        "success": True,
        "entries": [dict(row) for row in rows],
    }


@router.post("/knowledge/{entry_id}/restore")
def restore_knowledge(
    entry_id: int,
    user: dict = Depends(current_user)
):
    """
    Восстановление из архива.
    Только admin/director.
    """
    if not can_manage_knowledge_archive(user):
        raise HTTPException(
            status_code=403,
            detail="Восстановление доступно только администратору и директору."
        )

    conn = get_connection()

    row = conn.execute(
        "SELECT * FROM resolution_knowledge_base WHERE id = ?",
        (entry_id,)
    ).fetchone()

    if not row:
        conn.close()
        raise HTTPException(
            status_code=404,
            detail="Запись базы знаний не найдена."
        )

    if row["status"] != "archived":
        conn.close()
        raise HTTPException(
            status_code=409,
            detail="Запись не находится в архиве."
        )

    conn.execute(
        """
        UPDATE resolution_knowledge_base
        SET
            status = 'active',
            archived_by = NULL,
            archived_at = NULL,
            archive_reason = NULL
        WHERE id = ?
        """,
        (entry_id,)
    )

    conn.commit()
    conn.close()

    try:
        from backend.services.audit_service import log_action

        log_action(
            username=user.get("username"),
            role=user.get("role"),
            action="knowledge_restored",
            target=f"knowledge:{entry_id}",
            details="Запись БЗ восстановлена из архива.",
        )
    except Exception:
        pass

    return {
        "success": True,
        "id": entry_id,
        "status": "active",
    }


@router.delete("/knowledge/{entry_id}/permanent")
def permanently_delete_knowledge(
    entry_id: int,
    user: dict = Depends(current_user)
):
    """
    ФИЗИЧЕСКОЕ удаление БЗ.

    Только admin/director.
    Только для уже архивированной записи.
    Перед удалением создаётся backup.
    """
    if not can_manage_knowledge_archive(user):
        raise HTTPException(
            status_code=403,
            detail="Окончательное удаление доступно только администратору и директору."
        )

    conn = get_connection()

    row = conn.execute(
        "SELECT * FROM resolution_knowledge_base WHERE id = ?",
        (entry_id,)
    ).fetchone()

    if not row:
        conn.close()
        raise HTTPException(
            status_code=404,
            detail="Запись базы знаний не найдена."
        )

    if row["status"] != "archived":
        conn.close()
        raise HTTPException(
            status_code=409,
            detail=(
                "Нельзя удалить активную запись напрямую. "
                "Сначала архивируйте её."
            )
        )

    snapshot = dict(row)

    # Backup ДО физического удаления.
    backup_path = backup_database("before_knowledge_delete")

    try:
        conn.execute(
            "DELETE FROM resolution_knowledge_base WHERE id = ?",
            (entry_id,)
        )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    # Само содержимое удалено, но факт операции остаётся в audit.
    try:
        from backend.services.audit_service import log_action

        log_action(
            username=user.get("username"),
            role=user.get("role"),
            action="knowledge_deleted_permanently",
            target=f"knowledge:{entry_id}",
            details=(
                "Запись БЗ окончательно удалена. "
                f"Backup: {backup_path}. "
                f"Snapshot: {snapshot}"
            ),
        )
    except Exception:
        pass

    return {
        "success": True,
        "id": entry_id,
        "status": "deleted",
        "backup": backup_path,
    }


# =========================================================
# ИНСТРУКЦИИ — старый прямой DELETE больше не разрешаем.
# =========================================================

@router.post("/procedures/{procedure_id}/delete-request")
def request_procedure_delete(procedure_id: int, request: DecisionRequest, user: dict = Depends(current_user)):
    procedure = get_procedure_with_steps(procedure_id)
    if not procedure:
        raise HTTPException(status_code=404, detail="Инструкция не найдена.")
    try:
        request_id = request_delete(
            "procedures", procedure_id, user, procedure,
            object_label=procedure.get("title") or f"Инструкция #{procedure_id}",
            reason=request.comment,
        )
    except ProtectionError as error:
        raise HTTPException(status_code=403, detail=str(error))
    return {"success": True, "request_id": request_id, "status": "pending"}


# Совместимость: старый endpoint больше не удаляет напрямую.
@router.delete("/procedures/{procedure_id}")
def legacy_remove_procedure(procedure_id: int, user: dict = Depends(current_user)):
    raise HTTPException(
        status_code=409,
        detail="Прямое удаление отключено. Используйте «Запросить удаление» — оно требует подтверждения владельца.",
    )


# Совместимость: старый endpoint БЗ тоже не удаляет напрямую.
@router.delete("/knowledge/{entry_id}")
def legacy_remove_knowledge(entry_id: int, user: dict = Depends(current_user)):
    raise HTTPException(
        status_code=409,
        detail="Прямое удаление отключено. Для базы знаний используйте архивацию, затем окончательное удаление из архива.",
    )
