"""
Сотрудники: список, создание, роль, доступ, сессии, закрепление станков (только admin).

Вынесено из main.py без изменений поведения.
"""

from fastapi import APIRouter
from backend.services.audit_service import log_action, log_edit
from backend.services.auth_service import (
    VALID_ROLES,
    assign_equipment,
    create_user,
    delete_user,
    get_all_users,
    revoke_all_sessions,
    set_active,
    update_user_role,
    validate_password_strength,
)
from fastapi import Depends
from pydantic import BaseModel

from backend.api.common import (
    SETTINGS_ALLOWED_ROLES,
    SETTINGS_PAGE_ROLES,
    require_roles,
)

router = APIRouter()

class CreateUserRequest(BaseModel):

    username: str

    password: str

    full_name: str

    role: str


class UpdateUserRoleRequest(BaseModel):

    role: str


class AssignEquipmentRequest(BaseModel):

    equipment_ids: list[int]


@router.get("/api/settings/users")
def get_users_route(
    user: dict = Depends(require_roles(*SETTINGS_PAGE_ROLES))
):
    """
    Сотрудники, которых этот человек ведёт.

    Главный механик видит слесарей, начальник смены — операторов своей
    бригады, директор и главный инженер — всех. Список фильтрует
    СЕРВЕР, а не страница: иначе чужие фамилии уходили бы в браузер и
    достаточно было бы открыть консоль, чтобы их прочитать.
    """
    from backend.services.auth_service import user_traces
    from backend.services.staff_rbac import full_access, manageable_users, scope_text

    users = manageable_users(user, get_all_users())
    boss = full_access(user["role"])

    # Удалять можно только пустую учётку (завели по ошибке). У того, кто
    # работал, история останется в обращениях и отчётах — ему «закрыть доступ».
    for item in users:
        if boss:
            try:
                item["traces"] = user_traces(item["id"])
            except ValueError:
                item["traces"] = {}
            item["can_delete"] = not item["traces"]
        else:
            # Начальник участка учётки не удаляет и роли не меняет —
            # не показываем ему того, чего он всё равно не сможет.
            item["traces"] = {}
            item["can_delete"] = False

    return {
        "success": True,
        "users": users,
        "valid_roles": list(VALID_ROLES) if boss else [],
        "full_access": boss,
        "scope": scope_text(user),
    }


@router.post("/api/settings/users")
def create_user_route(
    request: CreateUserRequest,
    user: dict = Depends(require_roles(*SETTINGS_ALLOWED_ROLES))
):

    try:

        validate_password_strength(request.password)

        new_user_id = create_user(
            request.username,
            request.password,
            request.full_name,
            request.role
        )

    except ValueError as error:

        return {
            "success": False,
            "message": str(error)
        }

    log_action(
        username=user["username"],
        role=user["role"],
        action="user_created",
        target=f"user:{new_user_id}",
        details=f"{request.username} ({request.role})"
    )

    return {
        "success": True,
        "user_id": new_user_id
    }


@router.put("/api/settings/users/{user_id}/role")
def update_user_role_route(
    user_id: int,
    request: UpdateUserRoleRequest,
    user: dict = Depends(require_roles(*SETTINGS_ALLOWED_ROLES))
):

    # Подстраховка — админ не должен случайно снять роль admin
    # сам с себя и потерять доступ к "Настройкам".
    if user_id == user["id"] and request.role != "admin":

        return {
            "success": False,
            "message": "Нельзя снять с себя роль admin через этот интерфейс."
        }

    # Что было до смены должности: в журнале нужна пара «было → стало»,
    # иначе строка «Изменена должность · mechanic» не говорит, кем
    # человек был вчера.
    import sqlite3
    from backend.config import DB_NAME

    def snapshot():
        try:
            conn = sqlite3.connect(DB_NAME, timeout=10)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT role, full_name FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            conn.close()
            return dict(row) if row else {}
        except Exception:
            return {}

    before = snapshot()

    try:

        update_user_role(user_id, request.role)

    except ValueError as error:

        return {
            "success": False,
            "message": str(error)
        }

    after = snapshot()
    changes = log_edit(
        entity_type="user", entity_id=user_id,
        before=before, after=after, user=user,
        action="user_role_changed",
        name=after.get("full_name"),
    )

    return {
        "success": True,
        "changed": [c["label"] for c in changes],
    }


@router.post("/api/settings/users/{user_id}/revoke-sessions")
def revoke_user_sessions_route(
    user_id: int,
    user: dict = Depends(require_roles(*SETTINGS_PAGE_ROLES))
):
    """Выкинуть человека из системы. Своих — может и начальник участка."""
    from backend.services.staff_rbac import can_manage

    target = next((item for item in get_all_users() if item["id"] == user_id), None)
    if not target or not can_manage(user, target):
        return {"success": False,
                "message": "Этот сотрудник не в вашем подчинении."}

    count = revoke_all_sessions(user_id)

    log_action(
        username=user["username"],
        role=user["role"],
        action="admin_revoke_sessions",
        target=f"user:{user_id}",
        details=f"{count} сессий"
    )

    return {
        "success": True,
        "revoked_count": count
    }


@router.get("/api/settings/users/{user_id}/traces")
def user_traces_route(
    user_id: int,
    user: dict = Depends(require_roles(*SETTINGS_ALLOWED_ROLES))
):
    """
    Что останется без автора, если удалить учётку навсегда.

    Спрашивается ДО удаления: вернуть человека потом будет нечем, и
    список «обращения: 12, обходы: 4» — единственный способ понять
    цену решения заранее.
    """
    from backend.services.auth_service import user_traces

    try:
        traces = user_traces(user_id)
    except ValueError as error:
        return {"success": False, "message": str(error)}

    return {"success": True, "traces": traces, "total": sum(traces.values())}


@router.delete("/api/settings/users/{user_id}")
def delete_user_route(
    user_id: int,
    force: bool = False,
    user: dict = Depends(require_roles(*SETTINGS_ALLOWED_ROLES))
):

    # Та же подстраховка, что и при смене роли — нельзя случайно
    # удалить самого себя и остаться без доступа к "Настройкам".
    if user_id == user["id"]:

        return {
            "success": False,
            "message": "Нельзя удалить свой собственный аккаунт."
        }

    # Что именно осиротеет — записываем в журнал ДО удаления: после
    # него посчитать будет не по кому.
    from backend.services.auth_service import get_connection, user_traces

    conn = get_connection()
    row = conn.execute("SELECT username, full_name FROM users WHERE id = ?",
                       (user_id,)).fetchone()
    conn.close()
    victim = dict(row) if row else {}
    traces = user_traces(user_id) if victim else {}

    try:

        delete_user(user_id, force=force)

    except ValueError as error:

        return {
            "success": False,
            "message": str(error)
        }

    left = ", ".join(f"{label}: {count}" for label, count in traces.items())

    log_action(
        username=user["username"],
        role=user["role"],
        action="user_deleted",
        target=f"user:{user_id}",
        details=(f"{victim.get('full_name') or victim.get('username') or user_id}"
                 + (" — удалён навсегда" if force else "")
                 + (f"; без автора осталось — {left}" if left else "; следов в системе не было"))
    )

    return {
        "success": True
    }


@router.put("/api/settings/users/{user_id}/active")
def set_user_active_route(
    user_id: int,
    request: dict,
    user: dict = Depends(require_roles(*SETTINGS_ALLOWED_ROLES))
):
    """
    Закрыть или вернуть доступ. Это правильный способ проводить
    увольнение: удаление стирает человека из назначенных задач, а
    отключение оставляет его фамилию в истории смен.
    """

    active = bool(request.get("active"))

    if user_id == user["id"] and not active:

        return {
            "success": False,
            "message": "Нельзя закрыть доступ самому себе."
        }

    try:

        result = set_active(user_id, active)

    except ValueError as error:

        return {
            "success": False,
            "message": str(error)
        }

    log_action(
        username=user["username"],
        role=user["role"],
        action="user_enabled" if active else "user_disabled",
        target=f"user:{user_id}",
        details=None
    )

    return {
        "success": True,
        "user": result
    }


@router.put("/api/settings/users/{user_id}/equipment")
def assign_user_equipment_route(
    user_id: int,
    request: AssignEquipmentRequest,
    user: dict = Depends(require_roles(*SETTINGS_ALLOWED_ROLES))
):

    assign_equipment(user_id, request.equipment_ids)

    log_action(
        username=user["username"],
        role=user["role"],
        action="worker_equipment_assigned",
        target=f"user:{user_id}",
        details=f"{len(request.equipment_ids)} станков"
    )

    return {
        "success": True
    }


# =========================================
# СТОИМОСТЬ ЧАСА ПРОСТОЯ
# =========================================
# Сколько стоит час простоя, знает только директор. Пока не задал —
# система нигде не показывает денег: придуманная цифра хуже
# отсутствующей.

RATE_ROLES = ("director", "admin")


@router.get("/api/settings/downtime-rates")
def get_downtime_rates(user: dict = Depends(require_roles(*RATE_ROLES))):
    from backend.services.downtime_cost_service import SECTIONS, get_rates, rates_history

    return {
        "success": True,
        "sections": [{"section": key, "title": title} for key, title in SECTIONS.items()],
        "rates": get_rates(),
        "history": rates_history(20),
    }


@router.put("/api/settings/downtime-rates")
def set_downtime_rate(request: dict, user: dict = Depends(require_roles(*RATE_ROLES))):
    from fastapi import HTTPException

    from backend.services.downtime_cost_service import set_rate

    who = user.get("full_name") or user.get("username")

    try:
        saved = set_rate(
            section=(request.get("section") or "").strip(),
            rate_per_hour=request.get("rate_per_hour"),
            who=who,
            note=(request.get("note") or "").strip(),
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    log_action(
        username=user["username"], role=user["role"],
        action="downtime_rate_set", target=f"section:{request.get('section')}",
        details=f"{saved.get('rate_per_hour')} ₸/ч",
    )

    return {"success": True, "rate": saved}
