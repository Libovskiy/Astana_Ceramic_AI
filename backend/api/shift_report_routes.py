"""
API сменного отчёта упаковки (вагонетки → слои → брак → согласование).

Права (см. docstring backend/services/shift_report_service.py):
    worker            — ведёт вагонетки своей бригады и сдаёт отчёт
    shift_supervisor  — проверяет отчёты своей бригады, возвращает или
                        передаёт гл. инженеру
    chief_engineer    — подтверждает; после этого отчёт идёт в аналитику
    director/analyst  — только смотрят
"""

from fastapi import APIRouter, Cookie, Depends, HTTPException
from pydantic import BaseModel

from backend.services.auth_service import get_user_by_session
from backend.services import shift_report_service as svc

router = APIRouter(prefix="/api/shift-report", tags=["shift-report"])


def current_user(session_token: str | None = Cookie(default=None)):
    user = get_user_by_session(session_token)
    if user is None:
        raise HTTPException(status_code=401, detail="Не авторизован.")
    return user


def _can_see_report(user: dict, report: dict) -> bool:
    if user["role"] in svc.VIEW_ALL_ROLES:
        return True
    # Рабочий и мастер смены видят свою бригаду: чужая смена — не их дело
    # (тот же принцип, что в уведомлениях).
    return bool(user.get("brigade")) and user["brigade"] == report.get("brigade")


def _require(role_set: set, user: dict, what: str):
    if user["role"] not in role_set:
        raise HTTPException(status_code=403, detail=f"Нет прав: {what}.")


class CarPayload(BaseModel):
    car_number: str
    brick_type: str = ""
    layer1_at: str = ""
    layer2_at: str = ""
    layer3_at: str = ""
    finished_at: str = ""
    pallets_good: int = 0
    pallets_defect: int = 0
    defect_reason: str = ""


class OpenPayload(BaseModel):
    report_date: str
    shift: str
    brigade: str | None = None


class ReturnPayload(BaseModel):
    comment: str


class NormsPayload(BaseModel):
    car_minutes: int
    layer_minutes: int


@router.get("/meta")
def meta(user: dict = Depends(current_user)):
    """Справочники и права для интерфейса — чтобы фронт не гадал."""
    return {
        "success": True,
        "shifts": svc.SHIFTS,
        "brigades": svc.BRIGADES,
        "norms": svc.get_norms(),
        "my_brigade": user.get("brigade"),
        "can_fill": user["role"] in svc.FILL_ROLES,
        "can_check": user["role"] in svc.CHECK_ROLES,
        "can_approve": user["role"] in svc.APPROVE_ROLES,
        "can_set_norms": user["role"] in svc.APPROVE_ROLES,
        "status_labels": svc.STATUS_LABELS,
    }


@router.post("/open")
def open_report(payload: OpenPayload, user: dict = Depends(current_user)):
    """Открыть (или создать) отчёт за смену — с него начинается работа оператора."""
    _require(svc.FILL_ROLES | svc.CHECK_ROLES | svc.APPROVE_ROLES, user, "вести сменный отчёт")

    brigade = payload.brigade or user.get("brigade")
    if not brigade:
        raise HTTPException(status_code=400, detail="У вас не указана бригада — обратитесь к администратору.")

    if user["role"] not in svc.VIEW_ALL_ROLES and user.get("brigade") and brigade != user["brigade"]:
        raise HTTPException(status_code=403, detail="Можно вести только отчёт своей бригады.")

    if payload.shift not in svc.SHIFTS:
        raise HTTPException(status_code=400, detail="Неизвестная смена.")

    report = svc.get_or_create_report(payload.report_date, payload.shift, brigade, user["username"])
    return {"success": True, "report": svc.report_with_cars(report["id"])}


@router.get("/list")
def list_reports(status: str | None = None, brigade: str | None = None,
                 only_approved: bool = False, limit: int = 50,
                 user: dict = Depends(current_user)):
    if user["role"] not in svc.VIEW_ALL_ROLES:
        brigade = user.get("brigade")

    return {
        "success": True,
        "reports": svc.list_reports(limit=limit, status=status, brigade=brigade,
                                    only_approved=only_approved),
    }


@router.get("/{report_id}")
def get_report(report_id: int, user: dict = Depends(current_user)):
    report = svc.report_with_cars(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Отчёт не найден.")
    if not _can_see_report(user, report):
        raise HTTPException(status_code=403, detail="Это отчёт другой бригады.")
    return {"success": True, "report": report}


@router.post("/{report_id}/cars")
def add_car(report_id: int, payload: CarPayload, user: dict = Depends(current_user)):
    _require(svc.FILL_ROLES | svc.CHECK_ROLES, user, "добавлять вагонетки")
    try:
        car = svc.add_car(report_id, payload.model_dump(), user["username"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"success": True, "car": car}


@router.put("/cars/{car_id}")
def update_car(car_id: int, payload: CarPayload, user: dict = Depends(current_user)):
    _require(svc.FILL_ROLES | svc.CHECK_ROLES, user, "править вагонетки")
    try:
        car = svc.update_car(car_id, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"success": True, "car": car}


@router.delete("/cars/{car_id}")
def delete_car(car_id: int, user: dict = Depends(current_user)):
    _require(svc.FILL_ROLES | svc.CHECK_ROLES, user, "убирать вагонетки")
    try:
        svc.delete_car(car_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"success": True}


@router.post("/{report_id}/submit")
def submit(report_id: int, user: dict = Depends(current_user)):
    _require(svc.FILL_ROLES | svc.CHECK_ROLES, user, "сдавать отчёт")
    try:
        return {"success": True, "report": svc.submit_report(report_id, user["username"])}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{report_id}/check")
def check(report_id: int, user: dict = Depends(current_user)):
    _require(svc.CHECK_ROLES, user, "проверять отчёт может начальник смены")
    try:
        return {"success": True, "report": svc.check_report(report_id, user["username"])}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{report_id}/approve")
def approve(report_id: int, user: dict = Depends(current_user)):
    _require(svc.APPROVE_ROLES, user, "подтверждать отчёт может гл. инженер")
    try:
        return {"success": True, "report": svc.approve_report(report_id, user["username"])}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{report_id}/return")
def send_back(report_id: int, payload: ReturnPayload, user: dict = Depends(current_user)):
    _require(svc.CHECK_ROLES | svc.APPROVE_ROLES, user, "возвращать отчёт")
    try:
        return {"success": True, "report": svc.return_report(report_id, user["username"], payload.comment)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/norms")
def set_norms(payload: NormsPayload, user: dict = Depends(current_user)):
    _require(svc.APPROVE_ROLES, user, "менять нормы может гл. инженер")
    try:
        return {"success": True, "norms": svc.set_norms(payload.car_minutes, payload.layer_minutes, user["username"])}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
