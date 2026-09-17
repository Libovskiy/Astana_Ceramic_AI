"""
Страницы сайта (HTML) и служебные файлы: favicon, service worker, манифест, сертификат.

Вынесено из main.py без изменений поведения.
"""

from fastapi import APIRouter
from backend.services.dashboard_service import get_dashboard_data
from fastapi import Depends, Request
from fastapi.responses import FileResponse

from backend.api.common import (
    DASHBOARD_ALLOWED_ROLES,
    require_roles,
    templates,
)

router = APIRouter()

# =========================================
# ИКОНКА САЙТА
# =========================================
# Браузер просит /favicon.ico на каждой странице. Без этого роута в
# консоли на каждой вкладке висит 404.

@router.get("/favicon.ico", include_in_schema=False)
@router.get("/favicon.svg", include_in_schema=False)
def favicon():
    from fastapi.responses import FileResponse
    from pathlib import Path as _P

    icon = _P("frontend/static/favicon.svg")

    if not icon.exists():
        from fastapi import Response
        return Response(status_code=204)

    return FileResponse(
        icon,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


# =========================================
# LOGIN PAGE
# =========================================

@router.get("/login")
def login_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="login.html"
    )


# =========================================
# HOME
# =========================================

@router.get("/")
def home(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="index.html"
    )


# =========================================
# DIAGNOSTICS PAGE
# =========================================

@router.get("/diagnostics")
def diagnostics(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="diagnostics.html"
    )


# =========================================
# TECHNOLOGIST PAGE
# =========================================

@router.get("/technolog")
def technolog_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="technolog.html"
    )


@router.get("/equipment")
def equipment_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="equipment.html"
    )


@router.get("/mechanics")
def mechanics_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="mechanics.html"
    )


@router.get("/electrical")
def electrical_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="electrical.html"
    )


@router.get("/events")
def events_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="events.html"
    )


@router.get("/analytics")
def analytics_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="analytics.html"
    )

@router.get("/messenger")
def messenger_page(request: Request):
    """Переписка между людьми — не путать с /chat, там обращения о поломках."""
    return templates.TemplateResponse(request=request, name="messenger.html")


@router.get("/cases")
def cases_page(request: Request):
    return templates.TemplateResponse(request=request, name="cases.html")

@router.get("/parts")
def parts_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="parts.html"
    )

@router.get("/reports")
def reports_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="reports.html"
    )

@router.get("/instructions")
def instructions_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="instructions.html"
    )


@router.get("/knowledge")
def knowledge_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="knowledge.html"
    )


@router.get("/settings")
def settings_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="settings.html"
    )


@router.get("/dashboard")
def dashboard(user: dict = Depends(require_roles(*DASHBOARD_ALLOWED_ROLES))):

    return get_dashboard_data()


# Страница-каркас, как и "/" — не защищена на сервере (та же логика:
# HTML открыт всем, а сами данные приходят через защищённый /dashboard
# API, к которому эта страница обращается через JS).
@router.get("/production")
def production_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="production.html"
    )


@router.get("/sw.js")
def service_worker():
    # Service worker должен лежать в корне сайта: из /static/ он
    # управлял бы только адресами внутри /static/.
    return FileResponse("frontend/static/sw.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@router.get("/manifest.webmanifest")
def web_manifest():
    return FileResponse("frontend/static/manifest.webmanifest", media_type="application/manifest+json")


@router.get("/cert")
def cert_page(request: Request):
    return templates.TemplateResponse(request=request, name="cert.html")


@router.get("/usage")
def usage_page(request: Request):

    return templates.TemplateResponse(request=request, name="usage.html")


@router.get("/audit")
def audit_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="audit.html"
    )


@router.get("/my-regulation")
def my_regulation_page(request: Request):
    return templates.TemplateResponse(request=request, name="my_regulation.html")


@router.get("/checklist")
def checklist_page(request: Request):
    return templates.TemplateResponse(request=request, name="checklist.html")


# ── График ТО ─────────────────────────────────────────────
@router.get("/maintenance")
def maintenance_page(request: Request):
    return templates.TemplateResponse(request=request, name="maintenance.html")
