"""
«Наблюдение» — страница для полчаса в цеху: подготовка телефона механика,
лента событий обращения с точными временами, заметки.

Логика и зачем — в backend/services/observation_service.py.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.api.common import require_roles, templates
from backend.services import observation_service as obs
from backend.services import push_service

router = APIRouter()

# Наблюдение за работой в цеху: смотрит ещё и аналитик — это его
# работа. Начинает и правит наблюдение по-прежнему руководство.
OBSERVE_ROLES = ("director", "chief_engineer", "analyst")


class ObservationUpdate(BaseModel):
    mechanic_id: int | None = None
    case_id: int | None = None
    test_received: str | None = None      # 'да' / 'нет'
    seen: str | None = None               # как увидел: 'уведомление' / 'сам зашёл' / 'сказали'
    notes: str | None = None
    finish: bool = False


@router.get("/observe")
def observe_page(request: Request):
    return templates.TemplateResponse(request=request, name="observe.html")


@router.post("/api/observe/start")
def observe_start(user: dict = Depends(require_roles(*OBSERVE_ROLES))):
    return {"success": True, "id": obs.start(user)}


@router.get("/api/observe/current")
def observe_current(user: dict = Depends(require_roles(*OBSERVE_ROLES))):
    return {"success": True, "id": obs.latest_open(user), "candidates": obs.candidates(),
            "push_configured": push_service.enabled()}


@router.get("/api/observe/{obs_id}")
def observe_state(obs_id: int, user: dict = Depends(require_roles(*OBSERVE_ROLES))):
    try:
        return {"success": True, **obs.state(obs_id)}
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))


@router.post("/api/observe/{obs_id}")
def observe_update(obs_id: int, payload: ObservationUpdate, user: dict = Depends(require_roles(*OBSERVE_ROLES))):
    fields = {}
    if payload.mechanic_id is not None:
        fields["mechanic_id"] = payload.mechanic_id
    if payload.case_id is not None:
        fields["case_id"] = payload.case_id
    if payload.test_received in ("да", "нет"):
        fields["test_received"] = payload.test_received
        fields["test_received_at"] = obs.now()
    if payload.seen:
        fields["seen_at"] = obs.now()
        fields["seen_how"] = payload.seen[:40]
    if payload.notes is not None:
        fields["notes"] = payload.notes[:20000]
    if payload.finish:
        fields["finished_at"] = obs.now()
    obs.update(obs_id, **fields)
    return {"success": True, **obs.state(obs_id)}


@router.post("/api/observe/{obs_id}/test-push")
def observe_test_push(obs_id: int, user: dict = Depends(require_roles(*OBSERVE_ROLES))):
    state = obs.state(obs_id)
    mechanic = state.get("mechanic")
    if not mechanic:
        raise HTTPException(status_code=400, detail="Сначала выберите механика.")
    if not mechanic.get("devices"):
        raise HTTPException(status_code=400, detail="У механика не включены уведомления ни на одном телефоне.")
    push_service.send_to_users(
        [mechanic["id"]], "🔔 Проверка связи ACAI",
        "Если видите это на экране — уведомления работают. Скажите об этом рядом стоящему.",
        url="/chat", tag=f"observe-{obs_id}", urgent=True,
    )
    obs.update(obs_id, test_sent_at=obs.now())
    return {"success": True}
