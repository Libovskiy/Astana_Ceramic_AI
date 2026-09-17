"""
Управление пользователями для администратора — из веба, без
терминала.

Зачем отдельный модуль: раньше админ мог завести сотрудника только
придумав ему пароль вручную, с требованиями "от 10 символов,
заглавная, строчная, цифра". На практике это значит одно из двух:
либо админ ставит слабый предсказуемый пароль, либо идёт к
владельцу системы. А кнопки сброса не было вовсе — забыл пароль,
и админ ничем помочь не может.

Теперь: пароль генерируется системой, показывается ОДИН РАЗ и
нигде не сохраняется. Админ передаёт его сотруднику лично.

Разместить: backend/api/admin_routes.py

Подключение в main.py, после app = FastAPI():

    from backend.api.admin_routes import router as admin_router
    app.include_router(admin_router)
"""

import secrets

from fastapi import APIRouter, Cookie, Depends, HTTPException
from pydantic import BaseModel

from backend.config import is_owner
from backend.services.audit_service import log_action
from backend.services.auth_service import (
    get_user_by_session,
    create_user,
    set_password,
    rename_user,
    get_user_by_username,
    VALID_ROLES
)


router = APIRouter(prefix="/api/admin", tags=["admin"])


# Кому доступно управление людьми.
#
# Директор и зам. директора включены по решению заказчика: на заводе
# они принимают людей на работу и должны сами выдавать доступ, не
# дожидаясь администратора.
#
# Но администраторов и владельца системы они не трогают: раньше
# директор мог сбросить пароль учётки владельца, получить новый пароль
# на экран и войти администратором (нашли проверки tests/
# test_access_denied.py, 17.09.2026). См. _guard_target.
ADMIN_ROLES = ("admin", "director", "chief_engineer")

# Роли, которые выдаёт и обслуживает только администратор
PRIVILEGED_ROLES = ("admin",)


class CreateUserRequest(BaseModel):
    username: str
    full_name: str
    role: str
    # Пароль можно не передавать — сгенерируем сами.
    password: str | None = None


class RenameRequest(BaseModel):
    username: str | None = None
    full_name: str | None = None


def admin_user(session_token: str | None = Cookie(default=None)):

    user = get_user_by_session(session_token)

    if user is None:
        raise HTTPException(status_code=401, detail="Не авторизован.")

    if user["role"] not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Управление пользователями доступно администратору.")

    return user


def generate_password(full_name: str = "") -> str:
    """
    Читаемый одноразовый пароль.

    Не случайная каша вроде "x7#kQ2$m": такой пароль человек в цеху
    запишет на бумажке и приклеит к станку — безопасность станет
    хуже, чем при простом. Здесь произносимая основа и случайные
    цифры, которые не даёт угадать чужой пароль.
    """

    return "Acai" + secrets.token_hex(2).upper() + str(secrets.randbelow(900) + 100)


def _guard_target(actor: dict, target_id: int) -> None:
    """
    Кого можно сбрасывать и переименовывать.

    - администраторов и скрытые технические учётки — только администратор;
    - владельца системы — только сам владелец.
    Иначе право «выдавать доступ сотрудникам» превращается в право
    стать администратором.
    """
    import sqlite3
    from backend.config import DB_NAME

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    target = conn.execute(
        "SELECT id, username, role, COALESCE(hidden, 0) AS hidden FROM users WHERE id = ?", (target_id,)
    ).fetchone()
    conn.close()

    if target is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден.")

    if is_owner(dict(target)) and not is_owner(actor):
        raise HTTPException(status_code=403, detail="Учётку владельца системы меняет только владелец.")

    if (target["role"] in PRIVILEGED_ROLES or target["hidden"]) and actor["role"] != "admin":
        raise HTTPException(status_code=403, detail="Учётки администраторов меняет только администратор.")


@router.post("/users")
def create(request: CreateUserRequest, user: dict = Depends(admin_user)):
    if request.role in PRIVILEGED_ROLES and user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Администратора может завести только администратор.")

    if request.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Недопустимая роль '{request.role}'.")

    if get_user_by_username(request.username.strip()):
        raise HTTPException(status_code=400, detail="Такой логин уже занят.")

    password = (request.password or "").strip() or generate_password()

    try:
        user_id = create_user(
            request.username.strip(),
            password,
            request.full_name.strip(),
            request.role
        )

    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    # кто кого завёл — в журнал (пароль, конечно, нет)
    log_action(username=user["username"], role=user["role"], action="user_created",
               target=f"user:{user_id}", details=f"{request.username.strip()} ({request.role})")

    return {
        "success": True,
        "user_id": user_id,
        "username": request.username.strip(),
        # Показывается ОДИН раз. В базе только хэш — второй раз
        # этот пароль взять будет неоткуда, только сбросить новый.
        "password": password
    }


@router.post("/users/{user_id}/reset-password")
def reset(user_id: int, user: dict = Depends(admin_user)):
    _guard_target(user, user_id)

    password = generate_password()

    try:
        set_password(user_id, password)

    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))

    # сброс чужого пароля — важное действие, без следа его не проверить
    log_action(username=user["username"], role=user["role"], action="user_password_reset",
               target=f"user:{user_id}")

    return {
        "success": True,
        "password": password,
        "note": "Все открытые сессии этого сотрудника закрыты."
    }


@router.put("/users/{user_id}")
def rename(user_id: int, request: RenameRequest, user: dict = Depends(admin_user)):
    _guard_target(user, user_id)

    try:
        rename_user(
            user_id,
            new_username=request.username,
            new_full_name=request.full_name
        )

    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    log_action(username=user["username"], role=user["role"], action="user_renamed",
               target=f"user:{user_id}", details=request.username or request.full_name)

    return {"success": True}
