"""
Правка карточки самого регламента: название, вид продукции, описание,
плюс отправка в архив.

В regulation_service есть всё для этапов, параметров и версий, но сам
регламент после создания менять было нечем: ни переименовать, ни убрать
ошибочно заведённый. Отсюда разнобой в названиях — «1.4 НФ пустотелый»
и «Полнотелый» — и невозможность его исправить.

Что важно по смыслу:

Название и описание — это не нормы, а подпись на папке. Менять их можно
и у действующего регламента, новая версия для этого не нужна: цифры,
по которым работают в цеху, не меняются.

Вид продукции — другое дело. По нему регламенты группируются и ищется
действующий, поэтому у активного его трогать нельзя: сменишь — и цех
останется без регламента на свою марку.

Подключение в main.py:
    from backend.api.regulation_admin_routes import router as regulation_admin_router
    app.include_router(regulation_admin_router)
"""
import sqlite3

from fastapi import APIRouter, Cookie, Depends, HTTPException
from pydantic import BaseModel

from backend.config import DB_NAME
from backend.services.auth_service import get_user_by_session
from backend.services.regulation_rbac import can

router = APIRouter(tags=["regulations-admin"])


class RegulationEdit(BaseModel):
    name: str | None = None
    product_type: str | None = None
    description: str | None = None


def current_user(session_token: str | None = Cookie(default=None)):
    user = get_user_by_session(session_token)
    if user is None:
        raise HTTPException(status_code=401, detail="Не авторизован.")
    return user


def _db():
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _get(conn, regulation_id: int):
    row = conn.execute(
        "SELECT id, name, product_type, status, version FROM regulations WHERE id = ?",
        (regulation_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Регламент не найден.")
    return row


@router.put("/api/regulations/{regulation_id}")
def edit_regulation(regulation_id: int, request: RegulationEdit, user: dict = Depends(current_user)):
    if not can(user, "regulation.edit"):
        raise HTTPException(status_code=403, detail="Менять регламент может технолог.")

    conn = _db()
    try:
        row = _get(conn, regulation_id)

        fields, values = [], []

        if request.name is not None:
            name = request.name.strip()
            if not name:
                raise HTTPException(status_code=400, detail="Название не может быть пустым.")
            fields.append("name = ?")
            values.append(name)

        if request.description is not None:
            fields.append("description = ?")
            values.append(request.description.strip() or None)

        if request.product_type is not None:
            product_type = request.product_type.strip()
            if not product_type:
                raise HTTPException(status_code=400, detail="Укажите вид продукции.")
            if product_type != row["product_type"] and row["status"] == "active":
                raise HTTPException(
                    status_code=400,
                    detail="У действующего регламента вид продукции менять нельзя — "
                           "цех останется без норм на свою марку. Сначала снимите с действия.",
                )
            fields.append("product_type = ?")
            values.append(product_type)

        if not fields:
            return {"success": True, "changed": False}

        values.append(regulation_id)
        conn.execute(f"UPDATE regulations SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
    finally:
        conn.close()

    try:
        from backend.services.audit_service import log_action
        log_action(
            username=user.get("username"), role=user.get("role"),
            action="regulation_renamed", target=f"regulation:{regulation_id}",
            details=request.name or request.product_type or "описание",
        )
    except Exception:
        pass

    return {"success": True, "changed": True}


@router.delete("/api/regulations/{regulation_id}")
def archive_regulation(regulation_id: int, user: dict = Depends(current_user)):
    """
    В архив, а не в удаление: по регламенту могли работать, на него
    ссылаются замеры и подтверждения об ознакомлении. Исключение —
    черновик без содержимого: его удаляем совсем, чтобы ошибочно
    созданные пустышки не копились в списке.
    """
    if not can(user, "regulation.archive"):
        raise HTTPException(status_code=403, detail="Архивировать может технолог.")

    conn = _db()
    try:
        row = _get(conn, regulation_id)

        stages = conn.execute(
            "SELECT COUNT(*) AS n FROM regulation_stages WHERE regulation_id = ?",
            (regulation_id,),
        ).fetchone()["n"]
        params = conn.execute(
            "SELECT COUNT(*) AS n FROM regulation_parameters WHERE regulation_id = ?",
            (regulation_id,),
        ).fetchone()["n"]

        empty_draft = row["status"] == "draft" and stages == 0 and params == 0

        if empty_draft:
            conn.execute("DELETE FROM regulations WHERE id = ?", (regulation_id,))
            mode = "deleted"
        else:
            conn.execute(
                "UPDATE regulations SET status = 'archived' WHERE id = ?", (regulation_id,)
            )
            mode = "archived"

        conn.commit()
    finally:
        conn.close()

    try:
        from backend.services.audit_service import log_action
        log_action(
            username=user.get("username"), role=user.get("role"),
            action=f"regulation_{mode}", target=f"regulation:{regulation_id}",
            details=row["name"],
        )
    except Exception:
        pass

    return {"success": True, "mode": mode}
