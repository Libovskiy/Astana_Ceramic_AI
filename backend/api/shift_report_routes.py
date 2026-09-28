"""
API сменного отчёта упаковки (вагонетки → слои → брак → согласование).

Права (см. docstring backend/services/shift_report_service.py):
    worker            — ведёт вагонетки своей бригады и сдаёт отчёт
    shift_supervisor  — проверяет отчёты своей бригады, возвращает или
                        передаёт гл. инженеру
    chief_engineer    — подтверждает; после этого отчёт идёт в аналитику
    director/analyst  — только смотрят
"""

from backend.services.audit_service import log_action
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
    defect_note: str = ""


class CarPatch(BaseModel):
    """
    Правка вагонетки: всё необязательно.

    Отдельная модель от CarPayload нарочно. В CarPayload у полей есть
    значения по умолчанию («» и 0) — для создания это удобно, а для
    правки смертельно: поле, которого нет в запросе, приходило в UPDATE
    пустым и затирало выпуск смены. Здесь по умолчанию нет ничего, и
    вместе с exclude_unset в правку уходит ровно то, что прислали.
    """
    car_number: str | None = None
    brick_type: str | None = None
    layer1_at: str | None = None
    layer2_at: str | None = None
    layer3_at: str | None = None
    finished_at: str | None = None
    pallets_good: int | None = None
    pallets_defect: int | None = None
    defect_reason: str | None = None
    defect_note: str | None = None


class ReasonPayload(BaseModel):
    name: str


class OpenPayload(BaseModel):
    report_date: str
    shift: str
    brigade: str | None = None


class ReturnPayload(BaseModel):
    comment: str


class NormsPayload(BaseModel):
    car_minutes: int
    layer_minutes: int



# ── Что из сменного отчёта попадает в журнал ────────────────────────
#
# По этому отчёту считают выпуск смены, поэтому след нужен. Но писать
# в журнал каждую вагонетку нельзя: за смену их десятки, и журнал, в
# котором сейчас 281 запись, перестанет читаться за неделю.
#
# Поэтому по-разному:
#   • открыт, сдан, проверен, подтверждён, возвращён — одной строкой,
#     это и есть то, за что отвечают люди;
#   • нормы — «было → стало»: они меняют счёт по всем отчётам сразу;
#   • удаление вагонетки — «было → стало»: данные исчезают;
#   • правка вагонетки — только после того, как отчёт возвращали с
#     проверки. Пока идёт смена и отчёт в черновике, правки — это ввод
#     данных, а не изменение записи, которую кто-то уже видел.

CAR_FIELDS = ("car_number", "brick_type", "layer1_at", "layer2_at", "layer3_at",
              "finished_at", "pallets_good", "pallets_defect",
              "defect_reason", "defect_note")


def _report_line(report: dict) -> str:
    """«28.09, смена 2, бригада А» — чтобы строка журнала читалась без базы."""
    bits = [str(report.get("report_date") or "")]
    if report.get("shift"):
        bits.append(f'смена {report["shift"]}')
    if report.get("brigade"):
        bits.append(f'бригада {report["brigade"]}')
    return ", ".join(b for b in bits if b)


def _note(user: dict, action: str, report: dict, details: str = "",
          before=None, after=None) -> None:
    log_action(
        username=user.get("full_name") or user["username"], role=user["role"],
        action=action, target=f"shift_report:{report.get('id')}",
        details=f"{_report_line(report)}{(' — ' + details) if details else ''}",
        before=before, after=after,
    )


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
        "defect_reasons": [r["name"] for r in svc.list_defect_reasons()],
        "can_edit_reasons": user["role"] in svc.APPROVE_ROLES,
    }


@router.get("/defect-reasons")
def defect_reasons(user: dict = Depends(current_user)):
    return {"success": True, "reasons": svc.list_defect_reasons()}


@router.post("/defect-reasons")
def add_defect_reason(payload: ReasonPayload, user: dict = Depends(current_user)):
    _require(svc.APPROVE_ROLES, user, "править справочник причин может гл. инженер")
    try:
        reason = svc.create_defect_reason(payload.name, user["username"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Справочник причин брака решает, из чего оператор выбирает в конце
    # смены. Появилась причина или исчезла — это меняет то, как завод
    # объясняет свой брак, и должно быть видно в журнале.
    log_action(
        username=user["username"], role=user["role"],
        action="defect_reason_added",
        target=f"defect_reason:{(reason or {}).get('id')}",
        details=payload.name,
        after={"name": payload.name},
    )

    return {"success": True, "reason": reason}


@router.delete("/defect-reasons/{reason_id}")
def remove_defect_reason(reason_id: int, user: dict = Depends(current_user)):
    _require(svc.APPROVE_ROLES, user, "править справочник причин может гл. инженер")

    was = next((r for r in svc.list_defect_reasons() if r["id"] == reason_id), None)
    svc.archive_defect_reason(reason_id)

    log_action(
        username=user["username"], role=user["role"],
        action="defect_reason_archived",
        target=f"defect_reason:{reason_id}",
        details=(was or {}).get("name"),
        before={"name": (was or {}).get("name"), "is_active": 1},
        after={"name": (was or {}).get("name"), "is_active": 0},
    )

    return {"success": True}


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

    before = svc.find_report(payload.report_date, payload.shift, brigade)
    report = svc.get_or_create_report(payload.report_date, payload.shift, brigade, user["username"])
    if before is None:
        # Открытие пишем один раз: возвращение на ту же страницу в
        # середине смены журнал засорять не должно.
        _note(user, "shift_report_opened", report)
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


@router.get("/analytics")
def analytics(date_from: str | None = None, date_to: str | None = None,
              user: dict = Depends(current_user)):
    """Сводка для совещаний — только по подтверждённым отчётам."""
    if user["role"] not in svc.VIEW_ALL_ROLES | svc.CHECK_ROLES:
        raise HTTPException(status_code=403, detail="Нет доступа к сводке.")
    return {"success": True, "analytics": svc.analytics(date_from, date_to)}


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
def update_car(car_id: int, payload: CarPatch, user: dict = Depends(current_user)):
    _require(svc.FILL_ROLES | svc.CHECK_ROLES, user, "править вагонетки")

    was = svc.get_car(car_id)
    try:
        # exclude_unset: в правку уходит только то, что действительно
        # прислали. Иначе значения по умолчанию из модели затирали бы
        # соседние поля пустотой.
        car = svc.update_car(car_id, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    report = svc.get_report(was["report_id"]) if was else None
    if was and report and report.get("status") == svc.STATUS_RETURNED:
        before = {f: was.get(f) for f in CAR_FIELDS}
        after = {f: car.get(f) for f in CAR_FIELDS}
        if before != after:
            _note(user, "shift_report_car_updated", report,
                  f'вагонетка {was.get("car_number")} исправлена после возврата',
                  before=before, after=after)

    return {"success": True, "car": car}


@router.delete("/cars/{car_id}")
def delete_car(car_id: int, user: dict = Depends(current_user)):
    _require(svc.FILL_ROLES | svc.CHECK_ROLES, user, "убирать вагонетки")

    was = svc.get_car(car_id)
    try:
        svc.delete_car(car_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    report = svc.get_report(was["report_id"]) if was else None
    if was and report:
        _note(user, "shift_report_car_deleted", report,
              f'убрана вагонетка {was.get("car_number")} '
              f'({was.get("pallets_good") or 0} поддонов годных, '
              f'{was.get("pallets_defect") or 0} в брак)',
              before={f: was.get(f) for f in CAR_FIELDS}, after=None)

    return {"success": True}


@router.post("/{report_id}/submit")
def submit(report_id: int, user: dict = Depends(current_user)):
    _require(svc.FILL_ROLES | svc.CHECK_ROLES, user, "сдавать отчёт")
    try:
        report = svc.submit_report(report_id, user["username"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    full = svc.report_with_cars(report_id) or {}
    total = (full.get("totals") or {})
    _note(user, "shift_report_submitted", report,
          f'сдан: вагонеток {len(full.get("cars") or [])}, '
          f'годных поддонов {total.get("pallets_good", "—")}, '
          f'в брак {total.get("pallets_defect", "—")}')
    return {"success": True, "report": report}


@router.post("/{report_id}/check")
def check(report_id: int, user: dict = Depends(current_user)):
    _require(svc.CHECK_ROLES, user, "проверять отчёт может начальник смены")
    try:
        report = svc.check_report(report_id, user["username"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _note(user, "shift_report_checked", report, "проверен мастером смены")
    return {"success": True, "report": report}


@router.post("/{report_id}/approve")
def approve(report_id: int, user: dict = Depends(current_user)):
    _require(svc.APPROVE_ROLES, user, "подтверждать отчёт может гл. инженер")
    try:
        report = svc.approve_report(report_id, user["username"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # После подтверждения отчёт идёт в аналитику — с этой минуты по
    # нему считают выпуск завода. Кто именно подтвердил, должно быть
    # видно без разбирательств.
    _note(user, "shift_report_approved", report, "подтверждён — ушёл в аналитику")
    return {"success": True, "report": report}


@router.post("/{report_id}/return")
def send_back(report_id: int, payload: ReturnPayload, user: dict = Depends(current_user)):
    _require(svc.CHECK_ROLES | svc.APPROVE_ROLES, user, "возвращать отчёт")
    try:
        report = svc.return_report(report_id, user["username"], payload.comment)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _note(user, "shift_report_returned", report,
          f"возвращён на доработку: {payload.comment.strip()[:200]}")
    return {"success": True, "report": report}


@router.put("/norms")
def set_norms(payload: NormsPayload, user: dict = Depends(current_user)):
    _require(svc.APPROVE_ROLES, user, "менять нормы может гл. инженер")

    was = svc.get_norms()
    try:
        norms = svc.set_norms(payload.car_minutes, payload.layer_minutes, user["username"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Нормы пересчитывают ВСЕ отчёты сразу: вчерашняя смена, уложившаяся
    # в норматив, назавтра может оказаться отстающей. Поэтому «было →
    # стало», а не одна строка.
    before = {"car_minutes": was.get("car_minutes"), "layer_minutes": was.get("layer_minutes")}
    after = {"car_minutes": norms.get("car_minutes"), "layer_minutes": norms.get("layer_minutes")}
    if before != after:
        log_action(
            username=user.get("full_name") or user["username"], role=user["role"],
            action="shift_report_norms_changed", target="shift_report_norms",
            details=f'Норма на вагонетку {before["car_minutes"]} → {after["car_minutes"]} мин, '
                    f'на слой {before["layer_minutes"]} → {after["layer_minutes"]} мин',
            before=before, after=after,
        )
    return {"success": True, "norms": norms}
