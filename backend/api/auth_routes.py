"""
Вход, выход, текущий пользователь, смена пароля.

Вынесено из main.py без изменений поведения.
"""

from fastapi import APIRouter
import time as _time
from backend.config import ENVIRONMENT
from backend.services.audit_service import log_action
from backend.services.auth_service import (
    AccessDisabled,
    authenticate,
    create_session,
    delete_session,
    get_user_by_session,
    get_user_by_username,
    revoke_all_sessions,
)
from collections import defaultdict as _dd
from fastapi import (
    Cookie,
    Depends,
    Request,
    Response,
)
from pydantic import BaseModel
from threading import Lock as _Lock

from backend.api.common import (
    get_current_user,
    require_roles,
)

router = APIRouter()

class LoginRequest(BaseModel):

    username: str

    password: str


class RevokeSessionsRequest(BaseModel):

    username: str


# Ограничение попыток входа. Отдельный счётчик, а не общий
# rate_limit_service: у подбора пароля своя цена ошибки, и окно тут
# длиннее, чем минута.
LOGIN_MAX_ATTEMPTS = 10
LOGIN_WINDOW_SECONDS = 300
_login_attempts = _dd(list)
_login_lock = _Lock()


def login_allowed(key: str) -> bool:
    now = _time.time()
    with _login_lock:
        marks = _login_attempts[key]
        marks[:] = [t for t in marks if t > now - LOGIN_WINDOW_SECONDS]
        return len(marks) < LOGIN_MAX_ATTEMPTS


def login_failed(key: str) -> None:
    with _login_lock:
        _login_attempts[key].append(_time.time())


def login_succeeded(key: str) -> None:
    with _login_lock:
        _login_attempts.pop(key, None)


# =========================================
# AUTH: LOGIN
# =========================================

@router.post("/auth/login")
def login(data: LoginRequest, response: Response, request: Request):

    # Ключ по адресу: перебор идёт с одной машины по списку логинов,
    # поэтому считать только по имени пользователя бесполезно.
    client_ip = request.client.host if request.client else "unknown"

    if not login_allowed(client_ip):
        log_action(username=data.username, role=None, action="login_blocked")
        return {
            "success": False,
            "message": "Слишком много попыток входа. Подождите 5 минут.",
        }

    try:
        user = authenticate(data.username, data.password)

    except AccessDisabled:

        # Пароль верный, но доступ закрыт. Попытку не считаем подбором:
        # это свой человек, которому отключили учётку.
        log_action(username=data.username, role=None, action="login_disabled")

        return {
            "success": False,
            "message": "Доступ к системе закрыт. Обратитесь к руководителю.",
        }

    if user is None:

        login_failed(client_ip)

        # Неуспешная попытка входа — важно для отслеживания
        # подбора пароля. username берём из введённого значения
        # (не из БД — пользователя могло вообще не существовать).
        log_action(
            username=data.username,
            role=None,
            action="login_failed"
        )

        return {
            "success": False,
            "message": "Неверный логин или пароль."
        }

    login_succeeded(client_ip)

    token = create_session(user["id"])

    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=(ENVIRONMENT == "production"),
        max_age=12 * 60 * 60
    )

    log_action(
        username=user["username"],
        role=user["role"],
        action="login_success"
    )

    return {
        "success": True,
        "user": {
            "username": user["username"],
            "full_name": user["full_name"],
            "role": user["role"]
        }
    }


# =========================================
# AUTH: LOGOUT
# =========================================

@router.post("/auth/logout")
def logout(
    response: Response,
    session_token: str | None = Cookie(default=None)
):

    # Не требуем строго валидную сессию — logout должен отрабатывать
    # (очищать куку) даже если токен уже истёк. Для лога просто
    # смотрим, кто это был, если получится.
    user = get_user_by_session(session_token)

    if user is not None:
        log_action(
            username=user["username"],
            role=user["role"],
            action="logout"
        )

    delete_session(session_token)

    response.delete_cookie("session_token")

    return {"success": True}


# =========================================
# AUTH: LOGOUT EVERYWHERE (самообслуживание)
# =========================================
# Отзывает ВСЕ сессии текущего пользователя, не только эту —
# полезно, если забыли выйти на чужом/общем компьютере.

@router.post("/auth/logout-all")
def logout_all(
    response: Response,
    session_token: str | None = Cookie(default=None),
    user: dict = Depends(get_current_user)
):

    count = revoke_all_sessions(user["id"])

    log_action(
        username=user["username"],
        role=user["role"],
        action="logout_all_devices",
        details=f"{count} сессий отозвано"
    )

    response.delete_cookie("session_token")

    return {
        "success": True,
        "revoked_count": count
    }


# =========================================
# ADMIN: FORCE LOGOUT A SPECIFIC USER
# =========================================
# Принудительный разлогин конкретного сотрудника по логину —
# для случаев увольнения / подозрения на компрометацию аккаунта.
# Не ждём истечения его текущей сессии.

@router.post("/api/admin/revoke-user-sessions")
def revoke_user_sessions_route(
    request: RevokeSessionsRequest,
    admin_user: dict = Depends(require_roles("admin"))
):

    target_user = get_user_by_username(request.username)

    if target_user is None:
        return {
            "success": False,
            "message": "Пользователь не найден."
        }

    count = revoke_all_sessions(target_user["id"])

    log_action(
        username=admin_user["username"],
        role=admin_user["role"],
        action="admin_revoke_sessions",
        target=f"user:{request.username}",
        details=f"{count} сессий отозвано"
    )

    return {
        "success": True,
        "revoked_count": count
    }


# =========================================
# AUTH: CURRENT USER
# =========================================

@router.get("/auth/me")
def me(user: dict = Depends(get_current_user)):

    return {
        "success": True,
        "user": {
            # id нужен переписке: по нему страница отличает свои
            # сообщения от чужих и находит собеседника в диалоге.
            # Без него всё выглядело чужим, а в шапке личного
            # диалога стояла должность самого себя.
            "id": user["id"],
            "username": user["username"],
            "full_name": user["full_name"],
            "role": user["role"]
        }
    }


# ── Смена своего пароля ───────────────────────────────────
@router.post("/api/auth/change-password")
def change_password_route(request: dict, user: dict = Depends(get_current_user)):
    from backend.services.auth_service import authenticate, set_password, validate_password_strength
    curr = request.get("current_password", "")
    new_p = request.get("new_password", "")
    if not authenticate(user["username"], curr):
        return {"success": False, "message": "Неверный текущий пароль"}
    try:
        validate_password_strength(new_p)
    except ValueError as e:
        return {"success": False, "message": str(e)}
    set_password(user["id"], new_p)
    log_action(username=user["username"], role=user["role"], action="password_changed", target=f"user:{user['id']}")
    return {"success": True}


# ── Смена пароля подчинённому ─────────────────────────────
# Раньше это мог только администратор, и забытый пароль электрика в
# ночную смену ждал до утра. Теперь — начальник своего участка:
# гл. механик слесарю, начальник смены оператору СВОЕЙ бригады.
# Кто кого ведёт, решает staff_rbac.can_manage, а не эта ручка.
@router.put("/api/settings/users/{user_id}/password")
def set_user_password_route(user_id: int, request: dict,
                            user: dict = Depends(get_current_user)):
    from backend.services.auth_service import get_all_users
    from backend.services.staff_rbac import can_manage

    target = next((item for item in get_all_users() if item["id"] == user_id), None)
    if not target:
        return {"success": False, "message": "Сотрудник не найден."}

    if not can_manage(user, target):
        return {"success": False,
                "message": "Этот сотрудник не в вашем подчинении — "
                           "пароль ему меняет его начальник или главный инженер."}

    from backend.services.auth_service import set_password, validate_password_strength
    new_p = request.get("password", "")
    try:
        validate_password_strength(new_p)
    except ValueError as e:
        return {"success": False, "message": str(e)}
    set_password(user_id, new_p)
    log_action(username=user["username"], role=user["role"], action="user_password_changed", target=f"user:{user_id}")
    return {"success": True}
