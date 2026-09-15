"""
Назначение исполнителей на задачи.

В task_service есть assign_task, но наружу он нигде не выведен — главный
инженер видит заявку с обхода и не может передать её специалисту. Этот
роутер закрывает дыру.

Подключение в main.py (рядом с остальными include_router):
    from backend.api.task_assign_routes import router as task_assign_router
    app.include_router(task_assign_router)
"""
import sqlite3

from fastapi import APIRouter, Cookie, Depends, HTTPException

from backend.config import DB_NAME
from backend.services.auth_service import get_user_by_session

router = APIRouter(prefix="/api/tasks", tags=["tasks-assign"])

# кто вправе раздавать работу
ASSIGNER_ROLES = (
    "admin", "director",
    "chief_engineer", "chief_mechanic", "chief_electrician",
    "shift_supervisor",
)

# кого имеет смысл ставить исполнителем
WORKER_ROLES = (
    "technician", "worker", "engineer", "electrician", "mechanic",
    "chief_engineer", "chief_mechanic", "chief_electrician",
    "shift_supervisor", "technologist",
)


def current_user(session_token: str | None = Cookie(default=None)):
    user = get_user_by_session(session_token)
    if user is None:
        raise HTTPException(status_code=401, detail="Не авторизован.")
    return user


def assigner(user: dict = Depends(current_user)):
    if user.get("role") not in ASSIGNER_ROLES:
        raise HTTPException(status_code=403, detail="Назначать исполнителей может руководитель.")
    return user


def _db():
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


@router.get("/assignable")
def assignable_users(user: dict = Depends(assigner)):
    """
    Кого можно поставить на задачу, с текущей загрузкой — чтобы инженер
    не сваливал всё на одного человека.
    """
    placeholders = ",".join("?" * len(WORKER_ROLES))
    conn = _db()
    rows = conn.execute(
        f"""SELECT u.id, u.username, u.full_name, u.role, u.brigade,
                   (SELECT COUNT(*) FROM task_assignees ta
                    JOIN tasks t ON t.id = ta.task_id
                    WHERE ta.user_id = u.id
                      AND t.status IN ('new','in_progress')) AS open_tasks
            FROM users u
            WHERE COALESCE(u.hidden, 0) = 0
              AND u.role IN ({placeholders})
            ORDER BY open_tasks ASC, u.full_name""",
        WORKER_ROLES,
    ).fetchall()
    conn.close()
    return {"success": True, "users": [dict(r) for r in rows]}


@router.get("/{task_id}/assignees")
def task_assignees(task_id: int, user: dict = Depends(current_user)):
    conn = _db()
    rows = conn.execute(
        """SELECT u.id, u.full_name, u.username, u.role, ta.assigned_at
           FROM task_assignees ta
           JOIN users u ON u.id = ta.user_id
           WHERE ta.task_id = ?
           ORDER BY ta.assigned_at""",
        (task_id,),
    ).fetchall()
    conn.close()
    return {"success": True, "assignees": [dict(r) for r in rows]}


@router.post("/{task_id}/assign")
def set_assignees(task_id: int, request: dict, user: dict = Depends(assigner)):
    """
    Полный список исполнителей: кого нет в списке — снимаем, кого нет в
    задаче — назначаем. Так кнопка работает и на добавление, и на снятие.
    """
    from backend.services.task_service import assign_task

    wanted = {int(x) for x in (request.get("user_ids") or [])}

    conn = _db()
    try:
        if conn.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Задача не найдена")
        current = {
            r["user_id"] for r in conn.execute(
                "SELECT user_id FROM task_assignees WHERE task_id = ?", (task_id,)
            )
        }
        for uid in current - wanted:
            conn.execute(
                "DELETE FROM task_assignees WHERE task_id = ? AND user_id = ?",
                (task_id, uid),
            )
        conn.commit()
    finally:
        conn.close()

    added = []
    for uid in wanted - current:
        try:
            assign_task(task_id, uid, user["id"])
            added.append(uid)
        except ValueError:
            pass  # уже назначен или пользователя нет — не роняем остальных

    try:
        from backend.services.audit_service import log_action
        log_action(
            username=user.get("username"), role=user.get("role"),
            action="task_assignees_changed", target=f"task:{task_id}",
            details=f"назначено={len(added)} снято={len(current - wanted)}",
        )
    except Exception:
        pass

    return {
        "success": True,
        "assigned": len(added),
        "removed": len(current - wanted),
    }
