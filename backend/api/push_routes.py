"""
Уведомления на телефон (push) и скачивание заводского сертификата.

Вынесено из main.py без изменений поведения.
"""

from fastapi import APIRouter
from backend.services import push_service
from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.api.common import (
    get_current_user,
    require_roles,
)

router = APIRouter()

# =========================================
# AUDIT LOG PAGE
# =========================================

# ─── Уведомления на телефон (push) ────────────────────────

class PushSubscribeRequest(BaseModel):
    subscription: dict


class PushEndpointRequest(BaseModel):
    endpoint: str | None = None


@router.post("/api/push/status")
def push_status(request: PushEndpointRequest, user: dict = Depends(get_current_user)):
    return {"success": True, **push_service.status_for(user["id"], request.endpoint)}


@router.post("/api/push/subscribe")
def push_subscribe(payload: PushSubscribeRequest, request: Request, user: dict = Depends(get_current_user)):
    try:
        push_service.subscribe(user["id"], payload.subscription, request.headers.get("user-agent", ""))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return {"success": True}


@router.post("/api/push/unsubscribe")
def push_unsubscribe(request: PushEndpointRequest, user: dict = Depends(get_current_user)):
    push_service.unsubscribe(user["id"], request.endpoint)
    return {"success": True}


class PushClickRequest(BaseModel):
    tag: str


@router.post("/api/push/clicked")
def push_clicked(payload: PushClickRequest, user: dict = Depends(get_current_user)):
    from backend.services.observation_service import record_click
    record_click(user["id"], payload.tag[:100])
    return {"success": True}


@router.post("/api/push/test")
def push_test(user: dict = Depends(get_current_user)):
    """Проверка: прислать уведомление себе на все свои устройства."""
    push_service.send_to_users([user["id"]], "✅ Уведомления работают",
                               "Так будут приходить срочные оповещения ACAI.", url="/", tag="test", urgent=True)
    return {"success": True}


@router.get("/api/push/overview")
def push_overview(user: dict = Depends(require_roles("director", "chief_engineer"))):
    """Кто включил уведомления — для «Использования»."""
    return {"success": True, "configured": push_service.enabled(), "people": push_service.overview()}


@router.get("/cert/acai-ca.crt")
def cert_download():
    # Только открытая часть корневого сертификата — ключ не отдаётся
    return FileResponse("certs/ca.crt", media_type="application/x-x509-ca-cert",
                        filename="ACAI-Astana-Ceramic.crt")
