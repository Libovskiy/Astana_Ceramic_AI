"""
Уведомления на телефон (push) и скачивание заводского сертификата.

Вынесено из main.py без изменений поведения.
"""

import io
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
def push_overview(
    user: dict = Depends(require_roles("director", "chief_engineer", "analyst"))
):
    """Кто включил уведомления — для «Использования»."""
    return {"success": True, "configured": push_service.enabled(), "people": push_service.overview()}


@router.get("/cert/acai-ca.crt")
def cert_download():
    # Только открытая часть корневого сертификата — ключ не отдаётся
    return FileResponse("certs/ca.crt", media_type="application/x-x509-ca-cert",
                        filename="ACAI-Astana-Ceramic.crt")


@router.get("/cert/qr.svg")
def cert_qr(url: str = ""):
    """
    QR-код со ссылкой на эту же страницу.

    Набирать «https://acai.local:8443/cert» на чужом телефоне в цеху
    неудобно и все ошибаются. Код рисуется на сервере, интернет для
    этого не нужен — в цеху его может и не быть.
    """
    from fastapi import HTTPException
    from fastapi.responses import Response
    import segno

    target = (url or "").strip()

    # Ссылку принимаем только на наш же сайт: иначе страницу можно
    # было бы использовать как генератор чужих QR-кодов.
    if not target.startswith("https://") and not target.startswith("http://"):
        raise HTTPException(status_code=400, detail="Нужен адрес сайта.")
    if len(target) > 300:
        raise HTTPException(status_code=400, detail="Слишком длинный адрес.")

    buffer = io.BytesIO()
    segno.make(target, error="m").save(buffer, kind="svg", scale=5, border=2, dark="#111827")

    return Response(
        content=buffer.getvalue(),
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/api/cert/address")
def cert_address():
    """
    Адреса сервера для страницы сертификата.

    Открыт без входа: страницу открывают с нового устройства, которое
    ещё не доверяет серверу и не вошло в систему. Отдаются только
    адреса в локальной сети — их и так видно всем, кто в этой сети.
    """
    import subprocess

    ip = None
    try:
        ports = subprocess.run(["networksetup", "-listallhardwareports"],
                               capture_output=True, text=True, timeout=5).stdout
        for line in ports.splitlines():
            if not line.startswith("Device:"):
                continue
            device = line.split(":", 1)[1].strip()
            found = subprocess.run(["ipconfig", "getifaddr", device],
                                   capture_output=True, text=True, timeout=5).stdout.strip()
            if found:
                ip = found
                break
    except Exception as error:
        print(f"[cert] адрес не определён: {error}")

    return {"success": True, "ip": ip, "name": "acai.local", "port": 8443}
