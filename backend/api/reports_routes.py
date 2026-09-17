"""
Сводки: отчёты, колокольчик, журнал действий, использование системы.

Вынесено из main.py без изменений поведения.
"""

from fastapi import APIRouter
from backend.services import usage_service
from backend.services.analytics_service import get_biggest_loss_summary, get_downtime_by_period, get_performance_trend
from backend.services.audit_service import get_audit_log
from backend.services.notification_service import get_notifications
from fastapi import Depends, HTTPException

from backend.api.common import (
    get_current_user,
    require_roles,
)

router = APIRouter()

@router.get("/api/reports/summary")
def reports_summary(
    period: str = "week",
    # Сводка по всему заводу: план, простои, худшее оборудование.
    # Её зовут только /reports и /analytics, а они закрыты для цеха —
    # значит и сам запрос не должен отвечать рабочему или лаборанту.
    user: dict = Depends(require_roles("director", "chief_engineer", "analyst"))
):
    """
    Сводные данные для раздела «Отчёты».

    Использует существующую аналитику:
    - выполнение производственного плана;
    - простои;
    - оборудование с максимальным простоем.

    Данные не генерируются и не рассчитываются
    на фронтенде — используются существующие сервисы.
    """

    if period not in ("today", "week", "month"):
        raise HTTPException(
            status_code=400,
            detail="Допустимый период: today, week, month."
        )

    days = {
        "today": 1,
        "week": 7,
        "month": 30
    }[period]

    performance = get_performance_trend()
    downtime = get_downtime_by_period(days=days)
    biggest_loss = get_biggest_loss_summary(days=days)

    # График ТО и обходы смены раньше в сводку не попадали, хотя данные
    # для них давно лежат в базе: 78 работ в графике и статусы по
    # каждому пункту обхода. Директор узнавал о просроченном ТО из
    # разговора, а не из отчёта.
    from backend.services.analytics_service import (
        get_maintenance_summary,
        get_checklist_summary,
    )

    return {
        "success": True,
        "period": period,
        "performance": performance.get(period, {}),
        "downtime": downtime,
        "biggest_loss": biggest_loss,
        "maintenance": get_maintenance_summary(),
        "checklist": get_checklist_summary(days=days),
    }


@router.get("/api/notifications")
def get_notifications_route(
    user: dict = Depends(get_current_user)
):
    """
    Доступно любому авторизованному — фильтрация по роли (оператор
    видит своё оборудование, механик — механическое, электрик —
    электрическое, руководство — всё) происходит внутри
    get_notifications(), не на уровне доступа к роуту.
    """

    return {
        "success": True,
        "notifications": get_notifications(user)
    }


# =========================================
# AUDIT LOG (кто что сделал)
# =========================================
# admin — видит абсолютно всё.
# director/chief_engineer — видят всё, КРОМЕ действий самого admin
# (админ — техническая роль, директору его лог не нужен).
# engineer — видит только действия worker/technologist
# (те, кто непосредственно на производстве), больше ничего.

AUDIT_LOG_ALLOWED_ROLES = (
    "admin", "director", "chief_engineer", "engineer",
    "chief_mechanic", "chief_electrician"
)


@router.get("/api/audit-log/{entry_id}")
def get_audit_entry_route(
    entry_id: int,
    user: dict = Depends(require_roles(*AUDIT_LOG_ALLOWED_ROLES))
):
    """
    Одна запись журнала с разобранной разницей «было → стало».

    Нужна, чтобы по записи можно было понять, ЧТО именно поменяли, а
    не только что «регламент изменён». Сырой JSON наружу не отдаём: в
    нём пути к файлам и внутренние идентификаторы.
    """

    from backend.services.audit_service import get_audit_entry

    entry = get_audit_entry(entry_id)

    if not entry:
        raise HTTPException(status_code=404, detail="Запись не найдена.")

    return {"success": True, "entry": entry}


@router.get("/api/audit-log")
def get_audit_log_route(
    action: str | None = None,
    role: str | None = None,
    search: str | None = None,
    limit: int = 200,
    user: dict = Depends(require_roles(*AUDIT_LOG_ALLOWED_ROLES))
):

    entries = get_audit_log(limit=limit, action=action, role=role, search=search)

    if user["role"] == "engineer":

        entries = [
            entry
            for entry in entries
            if entry["role"] in ("worker", "technologist")
        ]

    elif user["role"] != "admin":

        entries = [
            entry
            for entry in entries
            if entry["role"] != "admin"
        ]

    return {
        "success": True,
        "entries": entries
    }


@router.get("/api/usage/summary")
def usage_summary(days: int = 7, user: dict = Depends(require_roles("director", "chief_engineer"))):
    return {"success": True, **usage_service.summary(days)}
