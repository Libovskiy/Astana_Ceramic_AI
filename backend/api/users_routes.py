"""
Сотрудники: список, создание, роль, доступ, сессии, закрепление станков (только admin).

Вынесено из main.py без изменений поведения.
"""

from fastapi import APIRouter
from backend.services.audit_service import log_action
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
    user: dict = Depends(require_roles(*SETTINGS_ALLOWED_ROLES))
):

    from backend.services.auth_service import user_traces

    users = get_all_users()

    # Удалять можно только пустую учётку (завели по ошибке). У того, кто
    # работал, история останется в обращениях и отчётах — ему «закрыть доступ».
    for item in users:
        try:
            item["traces"] = user_traces(item["id"])
        except ValueError:
            item["traces"] = {}
        item["can_delete"] = not item["traces"]

    return {
        "success": True,
        "users": users,
        "valid_roles": list(VALID_ROLES)
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

    try:

        update_user_role(user_id, request.role)

    except ValueError as error:

        return {
            "success": False,
            "message": str(error)
        }

    log_action(
        username=user["username"],
        role=user["role"],
        action="user_role_changed",
        target=f"user:{user_id}",
        details=request.role
    )

    return {
        "success": True
    }


@router.post("/api/settings/users/{user_id}/revoke-sessions")
def revoke_user_sessions_route(
    user_id: int,
    user: dict = Depends(require_roles(*SETTINGS_ALLOWED_ROLES))
):

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


@router.delete("/api/settings/users/{user_id}")
def delete_user_route(
    user_id: int,
    user: dict = Depends(require_roles(*SETTINGS_ALLOWED_ROLES))
):

    # Та же подстраховка, что и при смене роли — нельзя случайно
    # удалить самого себя и остаться без доступа к "Настройкам".
    if user_id == user["id"]:

        return {
            "success": False,
            "message": "Нельзя удалить свой собственный аккаунт."
        }

    try:

        delete_user(user_id)

    except ValueError as error:

        return {
            "success": False,
            "message": str(error)
        }

    log_action(
        username=user["username"],
        role=user["role"],
        action="user_deleted",
        target=f"user:{user_id}",
        details=None
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
