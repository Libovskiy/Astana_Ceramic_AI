"""
Общее для маршрутов, вынесенных из main.py: шаблоны, проверка входа
и ролей, модели запросов, защита загрузок и входа.

Здесь только то, чем пользуются несколько файлов маршрутов. Если
что-то нужно одному файлу — пусть живёт в нём.
"""

from backend.services.auth_service import get_user_by_session
from fastapi import Cookie, Depends, HTTPException
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(
    directory="frontend/templates"
)

# =========================================
# AUTH DEPENDENCIES
# =========================================

def get_current_user(session_token: str | None = Cookie(default=None)):

    user = get_user_by_session(session_token)

    if user is None:
        raise HTTPException(status_code=401, detail="Не авторизован.")

    return user


def require_roles(*roles: str):
    """
    require_roles("worker", "shift_supervisor") пускает пользователей
    с одной из перечисленных ролей. Роль 'admin' проходит ВСЕГДА,
    независимо от списка — админ обходит все проверки прав.
    """

    def dependency(user: dict = Depends(get_current_user)):

        if user["role"] == "admin":
            return user

        if user["role"] not in roles:
            raise HTTPException(
                status_code=403,
                detail="Недостаточно прав для этого действия."
            )

        return user

    return dependency


SETTINGS_ALLOWED_ROLES = ("admin",)



# =========================================
# OFFICE DASHBOARD
# =========================================

# Роли, которым нужен общий дашборд завода. worker/technologist/
# lab_technician/mechanic/electrician намеренно исключены — у них
# своя зона, им не нужна (и не должна быть видна) общая статистика
# по всему заводу. Гл. механик/гл. электрик — видят (нужно для
# "Производство 👁️" по матрице прав), но управлять не могут.
DASHBOARD_ALLOWED_ROLES = (
    "admin", "director", "chief_engineer", "production_chief",
    "shift_supervisor", "analyst", "technologist",
    "chief_mechanic", "chief_electrician"
)


WORK_QUEUE_ROLES = (
    "chief_mechanic", "mechanic", "chief_electrician", "electrician",
    "chief_engineer", "admin",
    # Директору страницы «Механика» и «Электрика» открыты, и очередь
    # работ — их главный блок. Без него страница грузилась с дырой и
    # отказом в консоли. Данных тут меньше, чем в журнале обращений,
    # который он и так видит.
    "director",
)
