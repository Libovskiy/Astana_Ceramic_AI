from fastapi import FastAPI, Request, Depends, HTTPException, Response, Cookie, UploadFile, BackgroundTasks
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import sqlite3
from pathlib import Path

from backend.config import ALLOWED_ORIGINS, DB_NAME, ENVIRONMENT, MAX_AI_STEPS
from backend.services.search_service import search, continue_diagnosis
from backend.services.response_service import build_answer
from backend.services.chat_service import save_message
from backend.services.case_service import (
    draft_close_case,
    approve_close_case,
    get_case,
    set_step,
    set_case_equipment,
    get_cases_by_equipment,
    search_case_events,
    get_recurring_issues,
    init_cases_tables,
    take_case,
    complete_repair,
    get_work_queue
)
from backend.services.knowledge_service import (
    init_knowledge_base,
    add_resolution,
    get_all_resolutions
)
from backend.services.mix_service import (
    init_mix_table,
    create_mix_entry,
    get_mix_entries,
    update_outcome,
    find_similar_batches
)
from backend.services.production_log_service import (
    init_production_tables,
    BRICK_TYPES,
    set_monthly_plan,
    get_monthly_plans,
    log_shift_production,
    get_today_production,
    get_shift_history,
    get_shift_chart_data,
    check_plan_anomaly
)
from backend.services.downtime_service import (
    init_downtime_table,
    start_downtime,
    end_downtime,
    get_active_downtimes,
    get_downtime_history,
    get_total_downtime_today,
    try_auto_start_downtime,
    try_auto_end_downtime_for_case
)
from backend.services.notification_service import get_notifications
from backend.services.analytics_service import (
    get_performance_trend,
    get_downtime_by_period,
    get_biggest_loss_summary
)
from backend.services.procedures_service import (
    init_procedures_tables,
    create_procedure,
    get_procedures_by_equipment,
    get_procedure_with_steps,
    delete_procedure
)
from backend.services.equipment_service import create_equipment, update_equipment_details
from backend.services.ai_service import suggest_mix_proportion, ask_management_ai
from backend.services.audit_service import (
    init_audit_table,
    log_action,
    get_audit_log,
    get_audit_log_by_target
)
from backend.services.dashboard_service import get_dashboard_data, get_top_problems_for_analytics
from backend.services.task_service import (
    create_task,
    get_task,
    init_task_tables,
    list_tasks,
)
from backend.services.equipment_service import (
    init_equipment,
    get_all_equipment,
    get_equipment,
    find_equipment_by_machine
)
from backend.services.equipment_state_service import maintenance_completed
from backend.services.auth_service import (
    init_auth_tables,
    authenticate,
    create_session,
    get_user_by_session,
    delete_session,
    revoke_all_sessions,
    get_user_by_username,
    get_assigned_equipment_ids,
    get_all_users,
    update_user_role,
    create_user,
    assign_equipment,
    validate_password_strength,
    VALID_ROLES,
    delete_user,
    set_active,
    AccessDisabled
)
from backend.services.rate_limit_service import check_rate_limit
from backend.services.regulation_service import init_regulation_extensions


app = FastAPI()

@app.on_event("startup")
def start_webhmi_collector():
    # Коллектор ходит на панель WebHMI и получает 403: пароль в коде
    # не подходит. Каждые 30 секунд — строка ошибки в логе, и в этом
    # шуме тонут настоящие сбои.
    #
    # Данные при этом идут через расширение в браузере и пишутся в
    # базу. Включить обратно: ACAI_WEBHMI_COLLECTOR=1 в .env, когда
    # появится действующий доступ к панели.
    import os as _os

    if (_os.environ.get("ACAI_WEBHMI_COLLECTOR") or "0").strip() != "1":
        print("[webhmi] Серверный сбор выключен "
              "(ACAI_WEBHMI_COLLECTOR=1 — включить). "
              "Показания идут через расширение браузера.")
        return
    try:
        from backend.services.webhmi_collector import start_collector_thread
        start_collector_thread()
    except Exception as e:
        print(f"Коллектор WebHMI не запустился: {e}")

from backend.api.lab_routes import router as lab_router
app.include_router(lab_router)
from backend.api.conversation_routes import router as conversation_router
app.include_router(conversation_router)
from backend.api.admin_routes import router as admin_router
app.include_router(admin_router)
from backend.api.protected_routes import router as protected_router
app.include_router(protected_router)

from backend.api.regulation_routes import router as regulation_router
app.include_router(regulation_router)

# Структура: этапы, оборудование, части, документы
from backend.api.structure_routes import router as structure_router
app.include_router(structure_router)

from backend.api.backup_routes import router as backup_router
app.include_router(backup_router)

# ─── Модуль мониторинга ───────────────────────────────────────────
from backend.api.sensor_routes import router as sensor_router
from backend.api.stage_routes import router as stage_router
from backend.api.note_routes import router as note_router
from backend.api.audit_routes import router as audit_router
app.include_router(sensor_router)
app.include_router(stage_router)
app.include_router(note_router)
app.include_router(audit_router)

from backend.api.checklist_routes import router as checklist_router
app.include_router(checklist_router)

from backend.api.task_assign_routes import router as task_assign_router
app.include_router(task_assign_router)

from backend.api.maintenance_summary_routes import router as maintenance_summary_router
app.include_router(maintenance_summary_router)

from backend.api.equipment_health_routes import router as equipment_health_router
app.include_router(equipment_health_router)

from backend.api.plc_errors_routes import router as plc_errors_router
app.include_router(plc_errors_router)

from backend.api.shift_report_routes import router as shift_report_router
app.include_router(shift_report_router)

from backend.api.task_status_routes import router as task_status_router
app.include_router(task_status_router)

from backend.api.team_chat_routes import router as team_chat_router
app.include_router(team_chat_router)

from backend.api.docs_files_routes import router as docs_files_router
app.include_router(docs_files_router)

from backend.api.regulation_admin_routes import router as regulation_admin_router
app.include_router(regulation_admin_router)

from backend.api.doc_status_routes import router as doc_status_router
app.include_router(doc_status_router)

from backend.api.my_regulation_routes import router as my_regulation_router
app.include_router(my_regulation_router)

from backend.api.maintenance_confirm_routes import router as maintenance_confirm_router
app.include_router(maintenance_confirm_router)


# =========================================
# CORS
# =========================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# =========================================
# INITIALIZE EQUIPMENT
# =========================================

init_equipment()
init_cases_tables()
init_auth_tables()
init_knowledge_base()
init_mix_table()
init_audit_table()
init_production_tables()
init_downtime_table()
init_procedures_tables()
init_regulation_extensions()
init_task_tables()

from backend.services.plc_error_service import init_plc_error_table
init_plc_error_table()

from backend.services.shift_report_service import init_shift_report_tables
init_shift_report_tables()

from backend.services.team_chat_service import init_team_chat
init_team_chat()

from backend.services.equipment_state_service import (
    init_state_events
)

init_state_events()

# =========================================
# STATIC FILES
# =========================================

app.mount(
    "/static",
    StaticFiles(directory="frontend/static"),
    name="static"
)

# Раздача PDF-документации по станкам — та же папка docs/, из которой
# собирается база знаний ChromaDB, теперь ещё и доступна для скачивания
# напрямую через "паспорт" станка на странице "Оборудование".
# /docs-files теперь отдаётся через docs_files_routes с проверкой сессии.
# Открытый StaticFiles убран: он раздавал все руководства без авторизации.


# =========================================
# ИКОНКА САЙТА
# =========================================
# Браузер просит /favicon.ico на каждой странице. Без этого роута в
# консоли на каждой вкладке висит 404.

@app.get("/favicon.ico", include_in_schema=False)
@app.get("/favicon.svg", include_in_schema=False)
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


templates = Jinja2Templates(
    directory="frontend/templates"
)


# =========================================
# ДОСТУП К СТРАНИЦАМ
# =========================================
#
# Скрыть пункт в меню — это косметика: адрес страницы всё равно можно
# набрать руками. Поэтому те же списки ролей, что в NAV_ITEMS
# (frontend/static/acai_layout.js), продублированы здесь и проверяются
# на сервере. Меняешь роли в меню — меняй и тут, иначе человек увидит
# ссылку, которая ведёт в отказ.
#
# "*" — страница открыта любому, кто вошёл в систему.
# Роль admin проходит везде.

PAGE_ROLES: dict[str, tuple[str, ...] | str] = {
    "/": ("director", "chief_engineer", "engineer", "shift_supervisor",
          "analyst", "chief_mechanic", "chief_electrician"),
    "/chat": ("worker", "director", "chief_engineer", "engineer", "shift_supervisor",
              "chief_mechanic", "mechanic", "chief_electrician", "electrician"),
    "/diagnostics": ("worker", "shift_supervisor", "engineer", "chief_engineer",
                     "director", "chief_mechanic", "mechanic",
                     "chief_electrician", "electrician"),
    "/equipment": ("director", "chief_engineer", "engineer", "shift_supervisor",
                   "chief_mechanic", "chief_electrician"),
    "/mechanics": ("director", "chief_engineer", "chief_mechanic", "mechanic"),
    "/electrical": ("director", "chief_engineer", "chief_electrician", "electrician"),
    # worker здесь потому, что сменный отчёт упаковки заполняют бригады
    # А/Б/В/Г — у них роль worker, а отчёт живёт на этой странице.
    "/production": ("worker", "director", "chief_engineer", "engineer",
                    "shift_supervisor", "analyst", "chief_mechanic",
                    "chief_electrician"),
    "/checklist": ("director", "chief_engineer", "engineer", "shift_supervisor",
                   "chief_mechanic", "chief_electrician"),
    "/maintenance": ("director", "chief_engineer", "chief_mechanic",
                     "chief_electrician", "engineer"),
    "/analytics": ("director", "chief_engineer", "analyst"),
    "/cases": ("director", "chief_engineer", "engineer", "shift_supervisor",
               "chief_mechanic", "mechanic", "chief_electrician", "electrician"),
    "/events": ("director", "chief_engineer", "engineer", "shift_supervisor"),
    "/reports": ("director", "chief_engineer", "analyst"),
    "/instructions": "*",
    "/regulations": "*",
    "/my-regulation": "*",
    "/mobile": "*",
    # Переписка между людьми открыта всем: договориться о подмене или
    # позвать электрика нужно любому, независимо от должности.
    "/messenger": "*",
    "/knowledge": ("director", "chief_engineer", "engineer",
                   "chief_mechanic", "chief_electrician"),
    # lab_technician раньше отсутствовал: логин уводил лаборанта на /lab,
    # а ссылки на /lab у него в меню не было.
    "/lab": ("director", "chief_engineer", "analyst", "technologist", "lab_technician"),
    "/parts": ("director", "chief_engineer", "chief_mechanic",
               "chief_electrician", "mechanic", "engineer"),
    "/technolog": ("director", "chief_engineer", "technologist"),
    "/audit": ("director", "chief_engineer", "chief_mechanic", "chief_electrician"),
    "/settings": (),  # только admin
}

# Куда отправить человека, которому тут не место (совпадает с
# ROLE_HOME_PAGE в frontend/static/login.js).
ROLE_HOME_PAGE = {
    "worker": "/chat",
    "technologist": "/lab",
    "lab_technician": "/lab",
    "engineer": "/production",
    "shift_supervisor": "/production",
    "chief_mechanic": "/mechanics",
    "mechanic": "/mechanics",
    "chief_electrician": "/electrical",
    "electrician": "/electrical",
}

ROLE_LABELS = {
    "admin": "Администратор", "director": "Директор",
    "chief_engineer": "Гл. инженер", "engineer": "Инженер",
    "worker": "Рабочий", "shift_supervisor": "Мастер смены",
    "chief_mechanic": "Гл. механик", "mechanic": "Механик",
    "chief_electrician": "Гл. электрик", "electrician": "Электрик",
    "analyst": "Аналитик", "technologist": "Технолог",
    "lab_technician": "Лаборант",
}


@app.middleware("http")
async def page_access_guard(request: Request, call_next):
    """
    Пускает на страницу только те роли, у которых она есть в меню.
    Работает по точному совпадению адреса, поэтому API и статика идут
    мимо: их права проверяют сами обработчики.
    """

    if request.method != "GET":
        return await call_next(request)

    allowed = PAGE_ROLES.get(request.url.path)

    if allowed is None:
        return await call_next(request)

    user = get_user_by_session(request.cookies.get("session_token"))

    if user is None:
        return RedirectResponse(url="/login", status_code=302)

    role = user.get("role", "")

    if allowed != "*" and role != "admin" and role not in allowed:
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            status_code=403,
            context={
                "path": request.url.path,
                "full_name": user.get("full_name") or user.get("username") or "—",
                "role_label": ROLE_LABELS.get(role, role),
                "home": ROLE_HOME_PAGE.get(role, "/instructions"),
            },
        )

    return await call_next(request)


# =========================================
# REQUEST MODELS
# =========================================

class ChatRequest(BaseModel):

    message: str

    case_id: int | None = None

    completed_actions: list[str] = []


class DiagnosticRequest(BaseModel):

    equipment_id: int

    question: str


class DraftCloseCaseRequest(BaseModel):

    comment: str | None = None


class ApproveCloseCaseRequest(BaseModel):

    comment: str | None = None


class CaseFeedbackRequest(BaseModel):

    helped: bool


class MixCalculationRequest(BaseModel):

    batch_weight_kg: float

    clay_percent: float

    note: str | None = None

    shift: str | None = None

    clay_source: str | None = None

    clay_batch_number: str | None = None

    clay_moisture_before: float | None = None

    clay_moisture_after: float | None = None

    sand_source: str | None = None

    sand_batch_number: str | None = None

    sand_moisture: float | None = None


class SimilarBatchesRequest(BaseModel):

    clay_source: str

    sand_source: str


class MixSuggestRequest(BaseModel):

    note: str | None = None


class CreateUserRequest(BaseModel):

    username: str

    password: str

    full_name: str

    role: str


class UpdateUserRoleRequest(BaseModel):

    role: str


class CreateEquipmentRequest(BaseModel):

    name: str

    type: str | None = None

    stage: str | None = None

    discipline: str | None = None

    location: str | None = None


class UpdateEquipmentRequest(BaseModel):

    name: str

    type: str | None = None

    stage: str | None = None

    discipline: str | None = None

    location: str | None = None


class AssignEquipmentRequest(BaseModel):

    equipment_ids: list[int]


class CreateProcedureRequest(BaseModel):

    equipment_id: int

    title: str

    duration_minutes: int | None = None

    target_role: str | None = None

    requires_stop: bool = False

    steps: list[str]


class CompleteRepairRequest(BaseModel):

    resolution_comment: str


class MixOutcomeRequest(BaseModel):

    outcome: str


class ProductionPlanRequest(BaseModel):

    brick_type: str

    monthly_target: int

    confirmed: bool = False


class ProductionLogRequest(BaseModel):

    log_date: str

    shift: str

    brick_type: str

    pallets: int


class StartDowntimeRequest(BaseModel):

    reason: str | None = None


class LoginRequest(BaseModel):

    username: str

    password: str


class RevokeSessionsRequest(BaseModel):

    username: str

class CreateTaskRequest(BaseModel):
    title: str
    description: str | None = None
    task_type: str = "ordinary"
    priority: str = "normal"
    due_at: str | None = None
    visibility: str = "assignees"
    visibility_role: str | None = None
    equipment_id: int | None = None
    assignee_ids: list[int] = []

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


# =========================================
# БЕЗОПАСНОСТЬ ЗАГРУЗОК И ВХОДА
# =========================================

import re as _re
import time as _time
import unicodedata as _ud
from collections import defaultdict as _dd
from threading import Lock as _Lock

MAX_DOC_BYTES = 50 * 1024 * 1024          # потолок на документ
ALLOWED_DOC_EXT = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".txt", ".jpg", ".jpeg", ".png"}


def safe_filename(name: str, default: str = "document.pdf") -> str:
    """
    Оставляет только имя файла, без каких-либо путей.

    Клиент присылает произвольную строку, и «../../backend/api/main.py»
    в ней — рабочий способ перезаписать код. Поэтому режем всё до
    последнего разделителя, выбрасываем управляющие символы и проверяем
    расширение по белому списку.
    """
    raw = str(name or "").strip()
    raw = raw.replace("\\", "/").split("/")[-1]      # и windows-, и unix-пути
    raw = _ud.normalize("NFC", raw)
    raw = _re.sub(r"[\x00-\x1f]", "", raw)
    raw = raw.lstrip(".") or default                  # «.», «..», «.htaccess»

    ext = ("." + raw.rsplit(".", 1)[-1].lower()) if "." in raw else ""
    if ext not in ALLOWED_DOC_EXT:
        raise HTTPException(
            status_code=415,
            detail=f"Такой тип файла загружать нельзя. Разрешены: {', '.join(sorted(ALLOWED_DOC_EXT))}",
        )
    return raw[:150]


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


def require_roles_rate_limited(*roles: str, key_prefix: str):

    role_check = require_roles(*roles)

    def dependency(user: dict = Depends(role_check)):

        key = f"{key_prefix}:{user['id']}"

        if not check_rate_limit(key):
            raise HTTPException(
                status_code=429,
                detail=(
                    "Слишком много запросов. "
                    "Подождите немного и попробуйте снова."
                )
            )

        return user

    return dependency


# =========================================
# LOGIN PAGE
# =========================================

@app.get("/login")
def login_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="login.html"
    )


# =========================================
# AUTH: LOGIN
# =========================================

@app.post("/auth/login")
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

@app.post("/auth/logout")
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

@app.post("/auth/logout-all")
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

@app.post("/api/admin/revoke-user-sessions")
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

@app.get("/auth/me")
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


# =========================================
# HOME
# =========================================

@app.get("/")
def home(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="index.html"
    )


# =========================================
# DIAGNOSTICS PAGE
# =========================================

@app.get("/diagnostics")
def diagnostics(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="diagnostics.html"
    )


# =========================================
# TECHNOLOGIST PAGE
# =========================================

@app.get("/technolog")
def technolog_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="technolog.html"
    )


@app.get("/equipment")
def equipment_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="equipment.html"
    )


@app.get("/mechanics")
def mechanics_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="mechanics.html"
    )


@app.get("/electrical")
def electrical_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="electrical.html"
    )


# =========================================
# EQUIPMENT API
# =========================================
# Рабочий (role='worker') видит только назначенные ему станки
# (таблица worker_equipment). Все остальные роли видят всё оборудование.

@app.get("/api/equipment")
def equipment_list(user: dict = Depends(get_current_user)):

    equipment = get_all_equipment()

    if user["role"] == "worker":

        allowed_ids = set(get_assigned_equipment_ids(user["id"]))

        equipment = [
            item
            for item in equipment
            if item["id"] in allowed_ids
        ]

    return {
        "success": True,
        "equipment": equipment
    }


@app.get("/api/equipment/{equipment_id}")
def equipment_details(equipment_id: int, user: dict = Depends(get_current_user)):

    if user["role"] == "worker":

        allowed_ids = set(get_assigned_equipment_ids(user["id"]))

        if equipment_id not in allowed_ids:
            return {
                "success": False,
                "message": "У вас нет доступа к этому оборудованию."
            }

    equipment = get_equipment(equipment_id)

    if equipment is None:

        return {
            "success": False,
            "message": "Оборудование не найдено."
        }

    return {
        "success": True,
        "equipment": equipment
    }


# =========================================
# EQUIPMENT LIFE JOURNAL
# =========================================
# Объединяет обращения (диагностика/ремонт) и отметки обслуживания
# в единую хронологию по конкретному станку — "паспорт оборудования"
# в цифровом виде. Работает только для событий ПОСЛЕ подключения
# equipment_id к обращениям — более старая история недоступна.

@app.get("/api/equipment/{equipment_id}/journal")
def equipment_journal_route(
    equipment_id: int,
    user: dict = Depends(get_current_user)
):

    if user["role"] == "worker":

        allowed_ids = set(get_assigned_equipment_ids(user["id"]))

        if equipment_id not in allowed_ids:
            return {
                "success": False,
                "message": "У вас нет доступа к этому оборудованию."
            }

    equipment = get_equipment(equipment_id)

    if equipment is None:
        return {
            "success": False,
            "message": "Оборудование не найдено."
        }

    cases = get_cases_by_equipment(equipment_id)

    try:
        maintenance_events = get_audit_log_by_target(f"equipment:{equipment_id}")
        if not isinstance(maintenance_events, list):
            maintenance_events = []
    except Exception:
        maintenance_events = []

    events = []

    for case in cases:
        events.append({
            "type": "case",
            "date": str(case["created_at"] or ""),
            "status": str(case["status"] or ""),
            "symptom": str(case["worker_question"] or case["symptom"] or ""),
            "resolution": str(case["resolution_comment"] or ""),
            "case_id": int(case["id"])
        })

    for entry in maintenance_events:
        events.append({
            "type": "maintenance",
            "date": str(entry["created_at"] or ""),
            "username": str(entry["username"] or ""),
            "role": str(entry["role"] or "")
        })

    events.sort(key=lambda item: item["date"], reverse=True)

    def safe(v):
        if isinstance(v, bytes):
            return None
        if isinstance(v, (str, int, float, bool, type(None))):
            return v
        return str(v)

    safe_events = [{k: safe(v) for k, v in e.items()} for e in events]

    return {
        "success": True,
        "journal": safe_events,
        "events": safe_events
    }


# =========================================
# EQUIPMENT DOCUMENTS ("паспорт" — реальные PDF из docs/)
# =========================================
# Папка в docs/ должна называться ровно как станок в базе (см.
# find_equipment_by_machine — та же логика точного совпадения
# имени). Если папки нет или она пустая — просто пустой список,
# не ошибка: далеко не для всех 50 станков документация уже
# разложена.

@app.get("/api/equipment/{equipment_id}/documents")
def equipment_documents_route(
    equipment_id: int,
    user: dict = Depends(get_current_user)
):

    if user["role"] == "worker":

        allowed_ids = set(get_assigned_equipment_ids(user["id"]))

        if equipment_id not in allowed_ids:
            return {
                "success": False,
                "message": "У вас нет доступа к этому оборудованию."
            }

    equipment = get_equipment(equipment_id)

    if equipment is None:
        return {
            "success": False,
            "message": "Оборудование не найдено."
        }

    # Та же замена "/" → "-", что и в /diagnose — иначе слеш в имени
    # станка (например "FANUC M-410iB/700") интерпретируется как
    # вложенная папка, а не часть названия.
    safe_name = equipment["name"].replace("/", "-")

    docs_folder = Path("/Users/champ_01/Documents/FactoryAssistant") / "docs" / safe_name

    import sys
    print(f"DEBUG docs_folder={docs_folder} exists={docs_folder.is_dir()}", file=sys.stderr)

    documents = []

    if docs_folder.is_dir():

        for pdf_path in sorted(docs_folder.rglob("*.pdf")):

            relative_path = pdf_path.relative_to(Path("/Users/champ_01/Documents/FactoryAssistant") / "docs")

            documents.append({
                "name": pdf_path.name,
                "url": f"/docs-files/{relative_path.as_posix()}"
            })

    return {
        "success": True,
        "equipment_name": equipment["name"],
        "documents": documents
    }


@app.get("/events")
def events_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="events.html"
    )


@app.get("/analytics")
def analytics_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="analytics.html"
    )

@app.get("/mobile")
def mobile_page(request: Request):
    return templates.TemplateResponse(request=request, name="mobile.html")


@app.get("/messenger")
def messenger_page(request: Request):
    """Переписка между людьми — не путать с /chat, там обращения о поломках."""
    return templates.TemplateResponse(request=request, name="messenger.html")


@app.get("/cases")
def cases_page(request: Request):
    return templates.TemplateResponse(request=request, name="cases.html")

@app.get("/parts")
def parts_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="parts.html"
    )

@app.get("/reports")
def reports_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="reports.html"
    )

@app.get("/instructions")
def instructions_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="instructions.html"
    )


@app.get("/knowledge")
def knowledge_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="knowledge.html"
    )


@app.get("/api/knowledge")
def get_knowledge_route(
    user: dict = Depends(get_current_user)
):
    """Видно всем авторизованным — как и Инструкции, это то, что
    реально помогает на месте, не только руководству."""

    return {
        "success": True,
        "grouped": get_all_resolutions()
    }


@app.get("/settings")
def settings_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="settings.html"
    )


SETTINGS_ALLOWED_ROLES = ("admin",)


@app.get("/api/settings/users")
def get_users_route(
    user: dict = Depends(require_roles(*SETTINGS_ALLOWED_ROLES))
):

    return {
        "success": True,
        "users": get_all_users(),
        "valid_roles": list(VALID_ROLES)
    }


@app.post("/api/settings/users")
def create_user_route(
    request: CreateUserRequest,
    user: dict = Depends(require_roles(*SETTINGS_ALLOWED_ROLES))
):

    try:

        validate_password_strength(request.password)

        new_user_id = create_user(
            request.username,
            request.password,
            request.full_name,
            request.role
        )

    except ValueError as error:

        return {
            "success": False,
            "message": str(error)
        }

    log_action(
        username=user["username"],
        role=user["role"],
        action="user_created",
        target=f"user:{new_user_id}",
        details=f"{request.username} ({request.role})"
    )

    return {
        "success": True,
        "user_id": new_user_id
    }


@app.put("/api/settings/users/{user_id}/role")
def update_user_role_route(
    user_id: int,
    request: UpdateUserRoleRequest,
    user: dict = Depends(require_roles(*SETTINGS_ALLOWED_ROLES))
):

    # Подстраховка — админ не должен случайно снять роль admin
    # сам с себя и потерять доступ к "Настройкам".
    if user_id == user["id"] and request.role != "admin":

        return {
            "success": False,
            "message": "Нельзя снять с себя роль admin через этот интерфейс."
        }

    try:

        update_user_role(user_id, request.role)

    except ValueError as error:

        return {
            "success": False,
            "message": str(error)
        }

    log_action(
        username=user["username"],
        role=user["role"],
        action="user_role_changed",
        target=f"user:{user_id}",
        details=request.role
    )

    return {
        "success": True
    }


@app.post("/api/settings/users/{user_id}/revoke-sessions")
def revoke_user_sessions_route(
    user_id: int,
    user: dict = Depends(require_roles(*SETTINGS_ALLOWED_ROLES))
):

    count = revoke_all_sessions(user_id)

    log_action(
        username=user["username"],
        role=user["role"],
        action="admin_revoke_sessions",
        target=f"user:{user_id}",
        details=f"{count} сессий"
    )

    return {
        "success": True,
        "revoked_count": count
    }


@app.delete("/api/settings/users/{user_id}")
def delete_user_route(
    user_id: int,
    user: dict = Depends(require_roles(*SETTINGS_ALLOWED_ROLES))
):

    # Та же подстраховка, что и при смене роли — нельзя случайно
    # удалить самого себя и остаться без доступа к "Настройкам".
    if user_id == user["id"]:

        return {
            "success": False,
            "message": "Нельзя удалить свой собственный аккаунт."
        }

    try:

        delete_user(user_id)

    except ValueError as error:

        return {
            "success": False,
            "message": str(error)
        }

    log_action(
        username=user["username"],
        role=user["role"],
        action="user_deleted",
        target=f"user:{user_id}",
        details=None
    )

    return {
        "success": True
    }


@app.put("/api/settings/users/{user_id}/active")
def set_user_active_route(
    user_id: int,
    request: dict,
    user: dict = Depends(require_roles(*SETTINGS_ALLOWED_ROLES))
):
    """
    Закрыть или вернуть доступ. Это правильный способ проводить
    увольнение: удаление стирает человека из назначенных задач, а
    отключение оставляет его фамилию в истории смен.
    """

    active = bool(request.get("active"))

    if user_id == user["id"] and not active:

        return {
            "success": False,
            "message": "Нельзя закрыть доступ самому себе."
        }

    try:

        result = set_active(user_id, active)

    except ValueError as error:

        return {
            "success": False,
            "message": str(error)
        }

    log_action(
        username=user["username"],
        role=user["role"],
        action="user_enabled" if active else "user_disabled",
        target=f"user:{user_id}",
        details=None
    )

    return {
        "success": True,
        "user": result
    }


@app.put("/api/settings/users/{user_id}/equipment")
def assign_user_equipment_route(
    user_id: int,
    request: AssignEquipmentRequest,
    user: dict = Depends(require_roles(*SETTINGS_ALLOWED_ROLES))
):

    assign_equipment(user_id, request.equipment_ids)

    log_action(
        username=user["username"],
        role=user["role"],
        action="worker_equipment_assigned",
        target=f"user:{user_id}",
        details=f"{len(request.equipment_ids)} станков"
    )

    return {
        "success": True
    }


@app.post("/api/settings/equipment")
def create_equipment_route(
    request: CreateEquipmentRequest,
    user: dict = Depends(require_roles(*SETTINGS_ALLOWED_ROLES))
):

    try:

        equipment_id = create_equipment(
            request.name,
            request.type,
            request.stage,
            request.discipline,
            request.location
        )

    except ValueError as error:

        return {
            "success": False,
            "message": str(error)
        }

    log_action(
        username=user["username"],
        role=user["role"],
        action="equipment_created",
        target=f"equipment:{equipment_id}",
        details=request.name
    )

    return {
        "success": True,
        "equipment_id": equipment_id
    }


@app.put("/api/settings/equipment/{equipment_id}")
def update_equipment_route(
    equipment_id: int,
    request: UpdateEquipmentRequest,
    user: dict = Depends(require_roles(*SETTINGS_ALLOWED_ROLES))
):

    try:

        update_equipment_details(
            equipment_id,
            request.name,
            request.type,
            request.stage,
            request.discipline,
            request.location
        )

    except ValueError as error:

        return {
            "success": False,
            "message": str(error)
        }

    log_action(
        username=user["username"],
        role=user["role"],
        action="equipment_updated",
        target=f"equipment:{equipment_id}",
        details=request.name
    )

    return {
        "success": True
    }


PROCEDURE_WRITE_ROLES = ("chief_engineer", "chief_mechanic", "chief_electrician", "admin")


@app.get("/api/procedures")
def get_procedures_route(
    user: dict = Depends(get_current_user)
):
    """Видно всем авторизованным — особенно нужно рабочему/
    механику/электрику на местах, не только руководству."""

    return {
        "success": True,
        "grouped": get_procedures_by_equipment()
    }


@app.get("/api/procedures/{procedure_id}")
def get_procedure_route(
    procedure_id: int,
    user: dict = Depends(get_current_user)
):

    procedure = get_procedure_with_steps(procedure_id)

    if not procedure:
        return {
            "success": False,
            "message": "Инструкция не найдена."
        }

    return {
        "success": True,
        "procedure": procedure
    }


@app.delete("/api/procedures/{procedure_id}")
def delete_procedure_route(
    procedure_id: int,
    user: dict = Depends(require_roles(*PROCEDURE_WRITE_ROLES))
):
    """
    Удаление инструкции. Функция в сервисе была, наружу её не выводили —
    поэтому ошибочно заведённую инструкцию нельзя было убрать.
    """
    procedure = get_procedure_with_steps(procedure_id)

    if not procedure:
        return {"success": False, "message": "Инструкция не найдена."}

    delete_procedure(procedure_id)

    log_action(
        username=user["username"],
        role=user["role"],
        action="procedure_deleted",
        target=f"procedure:{procedure_id}",
        before=procedure,
    )

    return {"success": True}


@app.post("/api/procedures")
def create_procedure_route(
    request: CreateProcedureRequest,
    user: dict = Depends(require_roles(*PROCEDURE_WRITE_ROLES))
):

    try:

        procedure_id = create_procedure(
            equipment_id=request.equipment_id,
            title=request.title,
            duration_minutes=request.duration_minutes,
            target_role=request.target_role,
            requires_stop=request.requires_stop,
            steps=request.steps,
            created_by=user["full_name"] or user["username"]
        )

    except ValueError as error:

        return {
            "success": False,
            "message": str(error)
        }

    log_action(
        username=user["username"],
        role=user["role"],
        action="procedure_created",
        target=f"procedure:{procedure_id}",
        details=request.title
    )

    return {
        "success": True,
        "procedure_id": procedure_id
    }



# =========================================
# OFFICE DASHBOARD
# =========================================

# Роли, которым нужен общий дашборд завода. worker/technologist/
# lab_technician/mechanic/electrician намеренно исключены — у них
# своя зона, им не нужна (и не должна быть видна) общая статистика
# по всему заводу. Гл. механик/гл. электрик — видят (нужно для
# "Производство 👁️" по матрице прав), но управлять не могут.
DASHBOARD_ALLOWED_ROLES = (
    "admin", "director", "chief_engineer", "engineer",
    "shift_supervisor", "analyst", "chief_mechanic", "chief_electrician"
)


@app.get("/dashboard")
def dashboard(user: dict = Depends(require_roles(*DASHBOARD_ALLOWED_ROLES))):

    return get_dashboard_data()


# Страница-каркас, как и "/" — не защищена на сервере (та же логика:
# HTML открыт всем, а сами данные приходят через защищённый /dashboard
# API, к которому эта страница обращается через JS).
@app.get("/production")
def production_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="production.html"
    )


# =========================================
# CASE EVENTS (журнал событий — фильтруемый список обращений)
# =========================================
# Отдельно от audit_log ("Журнал действий" — кто что сделал):
# здесь про сами обращения/неисправности, а не про действия людей.

@app.get("/api/case-events")
def case_events_route(
    date_from: str | None = None,
    date_to: str | None = None,
    equipment_id: int | None = None,
    stage: str | None = None,
    status: str | None = None,
    user: dict = Depends(require_roles(*DASHBOARD_ALLOWED_ROLES))
):

    events = search_case_events(
        date_from=date_from,
        date_to=date_to,
        equipment_id=equipment_id,
        stage=stage,
        status=status
    )

    return {
        "success": True,
        "events": events
    }


@app.get("/api/recurring-issues")
def recurring_issues_route(
    user: dict = Depends(require_roles(*DASHBOARD_ALLOWED_ROLES))
):

    return {
        "success": True,
        "issues": get_recurring_issues()
    }


# =========================================
# MAINTENANCE COMPLETED
# =========================================
# Сбрасывает статус "Внимание"/maintenance_required после того, как
# специалист реально обслужил оборудование. Раньше этот функционал
# существовал в equipment_state_service.py, но не был подключён
# ни к одному роуту — оборудование навсегда оставалось "Внимание".

@app.post("/api/equipment/{equipment_id}/maintenance-completed")
def maintenance_completed_route(
    equipment_id: int,
    user: dict = Depends(
        require_roles(
            "shift_supervisor", "engineer", "chief_engineer",
            "chief_mechanic", "mechanic", "chief_electrician", "electrician"
        )
    )
):

    state = maintenance_completed(equipment_id)

    if state is None:
        return {
            "success": False,
            "message": "Оборудование не найдено."
        }

    log_action(
        username=user["username"],
        role=user["role"],
        action="maintenance_completed",
        target=f"equipment:{equipment_id}"
    )

    return {
        "success": True,
        "equipment": state
    }


# =========================================
# DOWNTIME (простой)
# =========================================
# Те же роли, что и для "Обслуживание выполнено" — кто чинит,
# тот и фиксирует простой/устранение.

DOWNTIME_ROLES = (
    "shift_supervisor", "engineer", "chief_engineer",
    "chief_mechanic", "mechanic", "chief_electrician", "electrician"
)


@app.post("/api/equipment/{equipment_id}/downtime/start")
def start_downtime_route(
    equipment_id: int,
    request: StartDowntimeRequest,
    user: dict = Depends(require_roles(*DOWNTIME_ROLES))
):

    try:

        downtime_id = start_downtime(
            equipment_id=equipment_id,
            reason=request.reason,
            started_by=user["full_name"] or user["username"]
        )

    except ValueError as error:

        return {
            "success": False,
            "message": str(error)
        }

    log_action(
        username=user["username"],
        role=user["role"],
        action="downtime_started",
        target=f"equipment:{equipment_id}",
        details=request.reason
    )

    return {
        "success": True,
        "downtime_id": downtime_id
    }


@app.post("/api/downtime/{downtime_id}/end")
def end_downtime_route(
    downtime_id: int,
    user: dict = Depends(require_roles(*DOWNTIME_ROLES))
):

    try:

        duration_minutes = end_downtime(
            downtime_id=downtime_id,
            ended_by=user["full_name"] or user["username"]
        )

    except ValueError as error:

        return {
            "success": False,
            "message": str(error)
        }

    log_action(
        username=user["username"],
        role=user["role"],
        action="downtime_ended",
        target=f"downtime:{downtime_id}",
        details=f"{duration_minutes} мин"
    )

    return {
        "success": True,
        "duration_minutes": duration_minutes
    }


# Роли, которым открыт «Журнал обращений» (/cases). Совпадают со
# списком этой страницы в PAGE_ROLES — механик и электрик тоже видят
# журнал, они по нему и работают.
CASES_OVERVIEW_ROLES = (
    "director", "chief_engineer", "engineer", "shift_supervisor",
    "chief_mechanic", "mechanic", "chief_electrician", "electrician",
)


@app.get("/api/cases/overview")
def cases_overview(user: dict = Depends(require_roles(*CASES_OVERVIEW_ROLES))):
    """
    Данные для страницы «Журнал обращений».

    Раньше страница брала их из /dashboard — а он закрыт для механика
    и электрика, потому что там сводка по всему заводу. В итоге
    журнал, который стоит у них в меню, вечно висел на «Загрузка…».

    Здесь отдаём только то, что нужно самому журналу: обращения,
    список оборудования для фильтра и среднее время решения. Сводки
    по заводу тут нет, поэтому список ролей шире.
    """

    data = get_dashboard_data()

    return {
        "success": True,
        "recent_cases": data.get("recent_cases", []),
        "equipment": data.get("equipment", []),
        "average_resolution_minutes": data.get("average_resolution_minutes"),
    }


WORK_QUEUE_ROLES = (
    "chief_mechanic", "mechanic", "chief_electrician", "electrician",
    "chief_engineer", "admin",
    # Директору страницы «Механика» и «Электрика» открыты, и очередь
    # работ — их главный блок. Без него страница грузилась с дырой и
    # отказом в консоли. Данных тут меньше, чем в журнале обращений,
    # который он и так видит.
    "director",
)


@app.get("/api/work-queue")
def get_work_queue_route(
    discipline: str | None = None,
    user: dict = Depends(require_roles(*WORK_QUEUE_ROLES))
):

    return {
        "success": True,
        "queue": get_work_queue(discipline=discipline)
    }


@app.post("/api/cases/{case_id}/take")
def take_case_route(
    case_id: int,
    user: dict = Depends(require_roles(*WORK_QUEUE_ROLES))
):

    try:

        take_case(case_id, assigned_to=user["full_name"] or user["username"])

    except ValueError as error:

        return {
            "success": False,
            "message": str(error)
        }

    log_action(
        username=user["username"],
        role=user["role"],
        action="case_taken",
        target=f"case:{case_id}",
        details=None
    )

    return {
        "success": True
    }


@app.post("/api/cases/{case_id}/complete-repair")
def complete_repair_route(
    case_id: int,
    request: CompleteRepairRequest,
    user: dict = Depends(require_roles(*WORK_QUEUE_ROLES))
):

    try:

        complete_repair(
            case_id,
            resolution_comment=request.resolution_comment,
            completed_by=user["full_name"] or user["username"]
        )

        # Автозавершение простоя — привязанного к этому обращению,
        # если он ещё идёт. Симметрично автостарту при создании.
        try_auto_end_downtime_for_case(
            case_id,
            ended_by=user["full_name"] or user["username"]
        )

    except ValueError as error:

        return {
            "success": False,
            "message": str(error)
        }

    log_action(
        username=user["username"],
        role=user["role"],
        action="repair_completed",
        target=f"case:{case_id}",
        details=request.resolution_comment
    )

    return {
        "success": True
    }

@app.get("/api/reports/summary")
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

# =========================================
# TASK CENTER
# =========================================

TASK_CREATE_ROLES = (
    "director",
    "chief_engineer",
    "engineer",
    "shift_supervisor",
    "technologist",
    "chief_mechanic",
    "chief_electrician",
    "analyst",
)

TASK_VIEW_ROLES = (
    "director",
    "chief_engineer",
    "engineer",
    "shift_supervisor",
    "technologist",
    "lab_technician",
    "chief_mechanic",
    "mechanic",
    "chief_electrician",
    "electrician",
    "analyst",
    "worker",
)


@app.get("/api/tasks")
def get_tasks_route(
    status: str | None = None,
    task_type: str | None = None,
    limit: int = 100,
    user: dict = Depends(require_roles(*TASK_VIEW_ROLES)),
):
    if limit < 1:
        limit = 1

    if limit > 200:
        limit = 200

    try:
        tasks = list_tasks(
            user_id=user["id"],
            status=status,
            task_type=task_type,
            limit=limit,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        )

    return {
        "success": True,
        "tasks": tasks,
    }

@app.post("/api/tasks")
def create_task_route(
    request: CreateTaskRequest,
    user: dict = Depends(require_roles(*TASK_CREATE_ROLES)),
):
    try:
        task_id = create_task(
            title=request.title,
            description=request.description,
            task_type=request.task_type,
            priority=request.priority,
            due_at=request.due_at,
            created_by=user["id"],
            visibility=request.visibility,
            visibility_role=request.visibility_role,
            equipment_id=request.equipment_id,
            assignee_ids=request.assignee_ids,
        )
    except ValueError as error:
        return {
            "success": False,
            "message": str(error),
        }

    log_action(
        username=user["username"],
        role=user["role"],
        action="task_created",
        target=f"task:{task_id}",
        details=request.title,
    )

    return {
        "success": True,
        "task_id": task_id,
    }

@app.get("/api/tasks/{task_id}")
def get_task_route(
    task_id: int,
    user: dict = Depends(require_roles(*TASK_VIEW_ROLES)),
):
    task = get_task(task_id)

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Задача не найдена.",
        )

    return {
        "success": True,
        "task": task,
    }

@app.get("/api/downtime/active")
def get_active_downtimes_route(
    user: dict = Depends(require_roles(*DASHBOARD_ALLOWED_ROLES, *WORK_QUEUE_ROLES))
):

    return {
        "success": True,
        "downtimes": get_active_downtimes()
    }


@app.get("/api/notifications")
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


@app.get("/api/equipment/{equipment_id}/downtime")
def get_equipment_downtime_route(
    equipment_id: int,
    user: dict = Depends(get_current_user)
):

    if user["role"] == "worker":

        allowed_ids = set(get_assigned_equipment_ids(user["id"]))

        if equipment_id not in allowed_ids:
            return {
                "success": False,
                "message": "У вас нет доступа к этому оборудованию."
            }

    return {
        "success": True,
        "history": get_downtime_history(equipment_id=equipment_id)
    }


# =========================================
# MIX LOG (технолог — расчёт глина/песок)
# =========================================

MIX_WRITE_ROLES = ("technologist", "lab_technician")
MIX_READ_ROLES = (
    "technologist", "lab_technician", "director", "chief_engineer",
    "analyst"
)


@app.post("/api/mix")
def create_mix_entry_route(
    request: MixCalculationRequest,
    user: dict = Depends(require_roles(*MIX_WRITE_ROLES))
):

    try:

        entry = create_mix_entry(
            created_by=user["full_name"] or user["username"],
            batch_weight_kg=request.batch_weight_kg,
            clay_percent=request.clay_percent,
            note=request.note,
            shift=request.shift,
            clay_source=request.clay_source,
            clay_batch_number=request.clay_batch_number,
            clay_moisture_before=request.clay_moisture_before,
            clay_moisture_after=request.clay_moisture_after,
            sand_source=request.sand_source,
            sand_batch_number=request.sand_batch_number,
            sand_moisture=request.sand_moisture
        )

    except ValueError as error:

        return {
            "success": False,
            "message": str(error)
        }

    log_action(
        username=user["username"],
        role=user["role"],
        action="mix_entry_created",
        target=f"mix:{entry['id']}",
        details=f"{request.batch_weight_kg}кг, глина {request.clay_percent}%"
    )

    return {
        "success": True,
        "entry": entry
    }


@app.get("/api/mix")
def get_mix_entries_route(
    user: dict = Depends(require_roles(*MIX_READ_ROLES))
):

    return {
        "success": True,
        "entries": get_mix_entries()
    }


@app.post("/api/mix/suggest")
def suggest_mix_route(
    request: MixSuggestRequest,
    user: dict = Depends(require_roles(*MIX_WRITE_ROLES))
):
    """
    ИИ-подсказка процента глины по заметке + истории замесов с
    результатами. Реализация принципа "ИИ предлагает, а не просто
    записывает" применительно к модулю технолога.
    """

    history = get_mix_entries(limit=20)

    suggested_percent = suggest_mix_proportion(
        note=request.note,
        history=history
    )

    if suggested_percent is None:
        return {
            "success": False,
            "message": (
                "ИИ не может дать рекомендацию — либо не настроен ключ "
                "OpenAI, либо пока недостаточно данных в истории. "
                "Решите пропорцию самостоятельно."
            )
        }

    return {
        "success": True,
        "suggested_clay_percent": suggested_percent
    }


@app.post("/api/mix/{entry_id}/outcome")
def update_mix_outcome_route(
    entry_id: int,
    request: MixOutcomeRequest,
    user: dict = Depends(require_roles(*MIX_WRITE_ROLES))
):

    updated = update_outcome(entry_id, request.outcome)

    if not updated:
        return {
            "success": False,
            "message": "Запись не найдена."
        }

    log_action(
        username=user["username"],
        role=user["role"],
        action="mix_outcome_set",
        target=f"mix:{entry_id}",
        details=request.outcome
    )

    return {
        "success": True
    }


@app.post("/api/mix/similar")
def find_similar_batches_route(
    request: SimilarBatchesRequest,
    user: dict = Depends(require_roles(*MIX_WRITE_ROLES))
):
    """
    "Похожие партии" — по точному совпадению источника глины и
    источника песка. Возвращает историю + честную статистику
    (без "делай X" от ИИ, только "было раньше так").
    """

    result = find_similar_batches(
        clay_source=request.clay_source,
        sand_source=request.sand_source
    )

    return {
        "success": True,
        "entries": result["entries"],
        "stats": result["stats"]
    }


# =========================================
# PRODUCTION LOG (учёт выпуска по поддонам)
# =========================================
# Кто вводит поддоны: начальник смены и выше (гл. инженер,
# директор, админ) — как согласовано с пользователем.
# Кто меняет месячный план: гл. инженер/директор/админ — начальник
# смены плана не задаёт, только отчитывается по факту.

PRODUCTION_LOG_ROLES = ("shift_supervisor", "chief_engineer", "director", "admin")
PRODUCTION_PLAN_ROLES = ("chief_engineer", "director", "admin")


@app.get("/api/production/meta")
def production_meta(user: dict = Depends(get_current_user)):
    """
    Что этой должности доступно на странице «Производство».

    Раньше страница показывала всем всё подряд и ловила отказы:
    рабочий видел «Не удалось загрузить историю» — как будто система
    сломалась, хотя ему просто не положено. Теперь она спрашивает
    заранее и не рисует то, чем человек всё равно не воспользуется.

    Списки ролей берутся отсюда же, из одного места с проверками —
    чтобы не разъехались, как это уже было с меню и страницами.
    """

    role = user["role"]
    is_admin = role == "admin"

    return {
        "success": True,
        "role": role,
        "can_read_plan": is_admin or role in DASHBOARD_ALLOWED_ROLES,
        "can_edit_plan": is_admin or role in PRODUCTION_PLAN_ROLES,
        "can_log_output": is_admin or role in PRODUCTION_LOG_ROLES,
    }



@app.get("/api/production/plan")
def get_production_plan_route(
    user: dict = Depends(require_roles(*DASHBOARD_ALLOWED_ROLES))
):

    return {
        "success": True,
        "plans": get_monthly_plans(),
        "brick_types": list(BRICK_TYPES.keys())
    }


@app.post("/api/production/plan")
def set_production_plan_route(
    request: ProductionPlanRequest,
    user: dict = Depends(require_roles(*PRODUCTION_PLAN_ROLES))
):

    anomaly = check_plan_anomaly(request.brick_type, request.monthly_target)

    # Не блокируем жёстко — пользователь может действительно менять
    # план так резко. Но при подозрительном отклонении требуем явное
    # подтверждение (confirmed=true), а не сохраняем молча.
    if anomaly["severity"] != "ok" and not request.confirmed:

        return {
            "success": False,
            "needs_confirmation": True,
            "anomaly": anomaly
        }

    try:

        set_monthly_plan(
            request.brick_type,
            request.monthly_target,
            updated_by=user["full_name"] or user["username"]
        )

    except ValueError as error:

        return {
            "success": False,
            "message": str(error)
        }

    log_action(
        username=user["username"],
        role=user["role"],
        action="production_plan_updated",
        target=request.brick_type,
        details=f"{request.monthly_target} шт/мес" + (
            f" (подтверждено при отклонении {anomaly['change_percent']:+d}%)"
            if anomaly["severity"] != "ok"
            else ""
        )
    )

    return {
        "success": True,
        "plans": get_monthly_plans()
    }


@app.post("/api/production/log")
def log_production_route(
    request: ProductionLogRequest,
    user: dict = Depends(require_roles(*PRODUCTION_LOG_ROLES))
):

    try:

        pieces = log_shift_production(
            log_date=request.log_date,
            shift=request.shift,
            brick_type=request.brick_type,
            pallets=request.pallets,
            entered_by=user["full_name"] or user["username"]
        )

    except ValueError as error:

        return {
            "success": False,
            "message": str(error)
        }

    log_action(
        username=user["username"],
        role=user["role"],
        action="production_logged",
        target=f"{request.shift}:{request.brick_type}",
        details=f"{request.pallets} поддонов = {pieces} шт"
    )

    return {
        "success": True,
        "pieces": pieces,
        "today": get_today_production()
    }


@app.get("/api/production/today")
def get_production_today_route(
    user: dict = Depends(require_roles(*DASHBOARD_ALLOWED_ROLES))
):

    return {
        "success": True,
        **get_today_production()
    }


@app.get("/api/production/history")
def get_production_history_route(
    date_from: str | None = None,
    date_to: str | None = None,
    user: dict = Depends(require_roles(*DASHBOARD_ALLOWED_ROLES))
):

    return {
        "success": True,
        **get_shift_history(date_from=date_from, date_to=date_to)
    }


@app.get("/api/production/shift-chart")
def get_production_shift_chart_route(
    log_date: str,
    shift: str,
    user: dict = Depends(require_roles(*DASHBOARD_ALLOWED_ROLES))
):

    return {
        "success": True,
        **get_shift_chart_data(log_date=log_date, shift=shift)
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


@app.get("/api/audit-log")
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


# =========================================
# AUDIT LOG PAGE
# =========================================

@app.get("/audit")
def audit_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="audit.html"
    )



# =========================================
# MANAGEMENT AI
# =========================================

@app.post("/management-ai")
def management_ai(
    request: ChatRequest,
    user: dict = Depends(
        require_roles_rate_limited(
            "admin", "director", "chief_engineer", "engineer",
            "shift_supervisor", "analyst", "chief_mechanic",
            "chief_electrician",
            key_prefix="management-ai"
        )
    )
):
    """
    Управленческий AI не является рабочим обращением.
    Он читает текущий dashboard-контекст и только отвечает на вопрос.
    """
    question = (request.message or "").strip()

    if not question:
        return {
            "success": False,
            "answer": "Введите вопрос."
        }

    dashboard_data = get_dashboard_data()
    answer = ask_management_ai(question, dashboard_data)

    if answer is None:
        return {
            "success": False,
            "answer": (
                "ACAI не смог получить AI-ответ. "
                "Проверьте OPENAI_API_KEY и подключение к сервису."
            )
        }

    return {
        "success": True,
        "answer": answer
    }


# =========================================
# CHAT / WORKER REQUEST
# =========================================

CHAT_ALLOWED_ROLES = (
    "worker", "shift_supervisor", "engineer", "chief_engineer", "director",
    "chief_mechanic", "mechanic", "chief_electrician", "electrician"
)


@app.post("/chat")
def chat(
    request: ChatRequest,
    user: dict = Depends(
        require_roles_rate_limited(*CHAT_ALLOWED_ROLES, key_prefix="chat")
    )
):

    result = search(
        request.message
    )


    if not result["success"]:

        return {
            "answer": result["message"],
            "case_id": None,
            "machine": None,
            "symptom": None,
            "recommendation": result["message"],
            "actions": []
        }


    machine = result["machine"]["machine"]


    # -------------------------------------
    # Ищем оборудование по machine ДЛЯ ВСЕХ ролей (не только worker) —
    # нужно, чтобы проставить equipment_id обращению для журнала
    # жизни оборудования. Раньше это делалось только для worker
    # (проверка доступа), из-за чего у обращений от остальных ролей
    # equipment_id оставался пустым.
    # -------------------------------------

    matched_equipment = find_equipment_by_machine(machine)

    if matched_equipment:

        set_case_equipment(result["case_id"], matched_equipment["id"])

        # Автостарт простоя — как и в /diagnose, безопасно вызывать
        # повторно (например на каждое следующее сообщение в том же
        # обращении) — если простой уже идёт, ничего не делает.
        try_auto_start_downtime(
            matched_equipment["id"],
            reason=machine,
            started_by=user["full_name"] or user["username"],
            case_id=result["case_id"]
        )


    # -------------------------------------
    # Рабочий может диагностировать только СВОЁ оборудование.
    # Известное ограничение: к этому моменту search() уже создал
    # обращение и мог сдвинуть readiness — обращение просто останется
    # "осиротевшим" в базе, это на будущее стоит вынести раньше в pipeline.
    # -------------------------------------

    if user["role"] == "worker":

        allowed_ids = set(get_assigned_equipment_ids(user["id"]))

        if not matched_equipment or matched_equipment["id"] not in allowed_ids:

            return {
                "answer": "У вас нет доступа к диагностике этого оборудования.",
                "case_id": None,
                "machine": None,
                "symptom": None,
                "recommendation": "У вас нет доступа к диагностике этого оборудования.",
                "actions": []
            }


    save_message(
        result["case_id"],
        "worker",
        request.message
    )


    answer_data = build_answer(
        result["case_id"],
        machine,
        result["results"],
        question=request.message,
        equipment_id=matched_equipment["id"] if matched_equipment else None
    )


    # -------------------------------------
    # Предложить нечего сразу на первом шаге —
    # эскалируем, не показывая кнопки "Помогло"/"Не помогло" в пустоту.
    # -------------------------------------

    if not answer_data["recommendation"]:

        from backend.services.case_service import escalate_case

        escalate_case(result["case_id"])

        message = (
            "ACAI не нашёл подходящего решения. "
            "Требуется более опытный специалист."
        )

        return {
            "case_id": result["case_id"],
            "machine": machine.capitalize(),
            "symptom": (
                result["symptom"]["name"]
                if result["symptom"]
                else request.message
            ),
            "recommendation": message,
            "actions": [],
            "escalated": True,
            "awaiting_feedback": False
        }


    set_step(result["case_id"], 1)

    save_message(
        result["case_id"],
        "assistant",
        answer_data["recommendation"]
    )


    return {

        "case_id":
            result["case_id"],

        "machine":
            machine.capitalize(),

        "symptom":
            (
                result["symptom"]["name"]
                if result["symptom"]
                else request.message
            ),

        "recommendation":
            answer_data["recommendation"],

        "actions":
            answer_data["actions"],

        "explanation":
            answer_data.get("explanation"),

        "step": 1,

        "max_steps": MAX_AI_STEPS,

        "awaiting_feedback": True,

        "escalated": False
    }


# =========================================
# REAL EQUIPMENT DIAGNOSTICS
# =========================================

@app.post("/diagnose")
def diagnose(
    request: DiagnosticRequest,
    user: dict = Depends(
        require_roles_rate_limited(*CHAT_ALLOWED_ROLES, key_prefix="diagnose")
    )
):

    # -------------------------------------
    # Рабочий может диагностировать только назначенные ему станки —
    # equipment_id известен заранее, проверяем ДО любых побочных эффектов.
    # -------------------------------------

    if user["role"] == "worker":

        allowed_ids = set(get_assigned_equipment_ids(user["id"]))

        if request.equipment_id not in allowed_ids:

            return {
                "success": False,
                "message": "У вас нет доступа к диагностике этого оборудования."
            }


    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            id,
            name,
            type,
            status,
            location
        FROM equipment
        WHERE id = ?
        """,
        (request.equipment_id,)
    )

    equipment = cursor.fetchone()

    conn.close()

    if not equipment:
        return {
            "success": False,
            "message": "Оборудование не найдено."
        }

    question = (
        f"{equipment['name']}. "
        f"{request.question}"
    )

    # Оборудование уже выбрано явно (equipment_id из выпадающего
    # списка) — не нужно угадывать его по ключевым словам в тексте
    # вопроса, как раньше. Без этой строки диагностика ошибочно
    # отвечала "не удалось определить оборудование" для любого
    # станка, чьё название не совпадало с захардкоженными
    # ключевыми словами (messersi/fanuc_loader) — то есть для
    # 48 из 50 реальных станков линии.
    # .replace("/", "-") — у нескольких станков в названии есть "/"
    # (например "FANUC M-410iB/700"), а слеш в файловой системе
    # означает вложенную папку, а не часть имени. Без этой замены
    # поиск документации для таких станков не будет совпадать с
    # реальной структурой папок в docs/.
    machine_key = equipment["name"].strip().lower().replace("/", "-")

    result = search(
        question,
        selected_machine=machine_key,
        equipment_id=equipment["id"]
    )

    if not result["success"]:
        return {
            "success": False,
            "message": result["message"]
        }

    # Автостарт простоя — по решению пользователя, простой теперь
    # связан с обращением автоматически, не требует отдельной ручной
    # кнопки "Начать простой" каждый раз. Безопасно (не падает),
    # если простой для этого станка уже идёт.
    try_auto_start_downtime(
        equipment["id"],
        reason=result["machine"]["machine"] if result.get("machine") else "Обращение",
        started_by=user["full_name"] or user["username"],
        case_id=result.get("case_id")
    )

    machine = result["machine"]["machine"]

    answer_data = build_answer(
        result["case_id"],
        machine,
        result["results"],
        question=request.question,
        equipment_id=equipment["id"]
    )

    if not answer_data["recommendation"]:

        from backend.services.case_service import escalate_case

        escalate_case(result["case_id"])

        message = (
            "ACAI не нашёл подходящего решения. "
            "Требуется более опытный специалист."
        )

        return {
            "success": True,
            "case_id": result["case_id"],
            "equipment": {
                "id": equipment["id"],
                "name": equipment["name"],
                "type": equipment["type"],
                "status": equipment["status"],
                "location": equipment["location"]
            },
            "machine": machine.capitalize(),
            "symptom": (
                result["symptom"]["name"]
                if result["symptom"]
                else request.question
            ),
            "recommendation": message,
            "actions": [],
            "escalated": True,
            "awaiting_feedback": False
        }

    set_step(result["case_id"], 1)

    save_message(
        result["case_id"],
        "worker",
        request.question
    )

    save_message(
        result["case_id"],
        "assistant",
        answer_data["recommendation"]
    )

    return {
        "success": True,

        "case_id": result["case_id"],

        "equipment": {
            "id": equipment["id"],
            "name": equipment["name"],
            "type": equipment["type"],
            "status": equipment["status"],
            "location": equipment["location"]
        },

        "machine": machine.capitalize(),

        "symptom": (
            result["symptom"]["name"]
            if result["symptom"]
            else request.question
        ),

        "recommendation":
            answer_data["recommendation"],

        "actions":
            answer_data["actions"],

        "explanation":
            answer_data.get("explanation"),

        "step": 1,

        "max_steps": MAX_AI_STEPS,

        "awaiting_feedback": True,

        "escalated": False
    }


# =========================================
# CASE FEEDBACK ("Помогло" / "Не помогло")
# =========================================

@app.post("/case/{case_id}/feedback")
def case_feedback_route(
    case_id: int,
    request: CaseFeedbackRequest,
    user: dict = Depends(
        require_roles_rate_limited(*CHAT_ALLOWED_ROLES, key_prefix="feedback")
    )
):

    return continue_diagnosis(case_id, request.helped)


# =========================================
# DRAFT CLOSE CASE (черновик — начальник смены)
# =========================================

@app.post("/case/{case_id}/draft-close")
def draft_close_case_route(
    case_id: int,
    request: DraftCloseCaseRequest,
    user: dict = Depends(require_roles("shift_supervisor"))
):

    case = get_case(case_id)

    if case is None:
        return {
            "success": False,
            "message": "Обращение не найдено."
        }

    draft_close_case(
        case_id,
        drafted_by=user["full_name"] or user["username"],
        draft_comment=request.comment
    )

    log_action(
        username=user["username"],
        role=user["role"],
        action="case_draft_close",
        target=f"case:{case_id}",
        details=request.comment
    )

    return {
        "success": True,
        "case": get_case(case_id)
    }


# =========================================
# APPROVE CLOSE CASE (финал — главный инженер / админ)
# =========================================

@app.post("/case/{case_id}/approve-close")
def approve_close_case_route(
    case_id: int,
    request: ApproveCloseCaseRequest,
    user: dict = Depends(require_roles("chief_engineer"))
):

    case = get_case(case_id)

    if case is None:
        return {
            "success": False,
            "message": "Обращение не найдено."
        }

    approve_close_case(
        case_id,
        approved_by=user["full_name"] or user["username"],
        final_comment=request.comment
    )

    # Подстраховка — если специалист забыл нажать "Завершить ремонт"
    # (или обращение шло через черновик начальника смены, не через
    # очередь работ), простой всё равно не должен остаться висеть
    # после финального закрытия.
    try_auto_end_downtime_for_case(
        case_id,
        ended_by=user["full_name"] or user["username"]
    )

    updated_case = get_case(case_id)

    # -------------------------------------
    # Решение специалиста (не ИИ) — новое знание, которого
    # не было в документации/базе. Сохраняем на будущее.
    # -------------------------------------

    add_resolution(
        machine=updated_case["machine"],
        symptom_text=updated_case["worker_question"] or updated_case["symptom"],
        resolution_comment=updated_case["resolution_comment"],
        case_id=case_id,
        confirmed_by=user["full_name"] or user["username"]
    )

    log_action(
        username=user["username"],
        role=user["role"],
        action="case_approve_close",
        target=f"case:{case_id}",
        details=request.comment
    )

    return {
        "success": True,
        "case": updated_case
    }


# =========================================
# NEXT DIAGNOSTIC STEP
# =========================================

@app.post("/diagnostic/next")
def next_diagnostic(
    request: ChatRequest,
    user: dict = Depends(require_roles(*CHAT_ALLOWED_ROLES))
):

    return {

        "success": True,

        "case_id":
            request.case_id,

        "recommendation":
            (
                "Базовая проверка не устранила "
                "проблему. Переходим к следующему "
                "этапу диагностики."
            ),

        "actions": []
    }


@app.patch("/api/settings/equipment/{equipment_id}/archive")
def archive_equipment_route(
    equipment_id: int,
    user: dict = Depends(require_roles("admin", "director"))
):
    """Мягкое удаление — is_active=0. Только admin/director."""
    import sqlite3 as _sq
    from backend.config import DB_NAME as _db
    conn = _sq.connect(_db)
    conn.execute("UPDATE equipment SET is_active = 0 WHERE id = ?", (equipment_id,))
    conn.commit()
    conn.close()
    log_action(username=user["username"], role=user["role"],
               action="equipment_archived", target=f"equipment:{equipment_id}")
    return {"success": True}


@app.patch("/api/settings/equipment/{equipment_id}/restore")
def restore_equipment_route(
    equipment_id: int,
    user: dict = Depends(require_roles("admin", "director"))
):
    """Восстановить архивированное оборудование."""
    import sqlite3 as _sq
    from backend.config import DB_NAME as _db
    conn = _sq.connect(_db)
    conn.execute("UPDATE equipment SET is_active = 1 WHERE id = ?", (equipment_id,))
    conn.commit()
    conn.close()
    log_action(username=user["username"], role=user["role"],
               action="equipment_restored", target=f"equipment:{equipment_id}")
    return {"success": True}


# ── Смена статуса оборудования ────────────────────────────
@app.post("/api/equipment/{equipment_id}/status")
def set_equipment_status(
    equipment_id: int,
    request: dict,
    user: dict = Depends(get_current_user)
):
    from backend.services.equipment_service import update_equipment_status
    status = request.get("status")
    if not status:
        return {"success": False, "message": "Статус не указан"}
    update_equipment_status(equipment_id, status)
    log_action(username=user["username"], role=user["role"],
               action="equipment_status_changed",
               target=f"equipment:{equipment_id}", details=status)
    return {"success": True}


# ── Архивирование оборудования ────────────────────────────
@app.patch("/api/settings/equipment/{equipment_id}/archive")
def archive_equipment(
    equipment_id: int,
    user: dict = Depends(require_roles("admin", "director"))
):
    import sqlite3 as _sq
    conn = _sq.connect(DB_NAME)
    conn.execute("UPDATE equipment SET is_active = 0 WHERE id = ?", (equipment_id,))
    conn.commit(); conn.close()
    log_action(username=user["username"], role=user["role"],
               action="equipment_archived", target=f"equipment:{equipment_id}")
    return {"success": True}


@app.patch("/api/settings/equipment/{equipment_id}/restore")
def restore_equipment(
    equipment_id: int,
    user: dict = Depends(require_roles("admin", "director"))
):
    import sqlite3 as _sq
    conn = _sq.connect(DB_NAME)
    conn.execute("UPDATE equipment SET is_active = 1 WHERE id = ?", (equipment_id,))
    conn.commit(); conn.close()
    log_action(username=user["username"], role=user["role"],
               action="equipment_restored", target=f"equipment:{equipment_id}")
    return {"success": True}


@app.post("/api/equipment/{equipment_id}/set-status")
def set_equipment_status_route(
    equipment_id: int,
    request: dict,
    user: dict = Depends(get_current_user)
):
    from backend.services.equipment_service import update_equipment_status
    from backend.services.downtime_service import (
        get_active_downtime_for_equipment,
        end_downtime,
    )

    status = request.get("status")
    if not status:
        raise HTTPException(status_code=400, detail="Статус не указан")

    update_equipment_status(equipment_id, status)

    # Станок вернули в работу — простой закончился. Раньше он закрывался
    # только вместе с обращением, а оно может висеть неделями, пока
    # станок давно крутится: простой копился и врал в аналитике.
    closed_minutes = None
    if status == "Работает":
        active = get_active_downtime_for_equipment(equipment_id)
        if active:
            try:
                closed_minutes = end_downtime(
                    active["id"],
                    ended_by=user.get("full_name") or user["username"],
                )
            except Exception:
                closed_minutes = None

    log_action(username=user["username"], role=user["role"],
        action="equipment_status_changed",
        target=f"equipment:{equipment_id}", details=status)

    if closed_minutes is not None:
        log_action(username=user["username"], role=user["role"],
            action="downtime_closed_by_status",
            target=f"equipment:{equipment_id}",
            details=f"простой закрыт: {closed_minutes} мин")

    return {"success": True, "downtime_closed_minutes": closed_minutes}


# ── Загрузка документа для оборудования ──────────────────
@app.post("/api/equipment/{equipment_id}/documents/upload")
async def upload_equipment_doc(
    background_tasks: BackgroundTasks,
    equipment_id: int,
    file: UploadFile,
    user: dict = Depends(require_roles("admin", "director", "chief_engineer", "chief_mechanic", "chief_electrician"))
):
    import shutil
    from pathlib import Path as _Path
    equipment = get_equipment(equipment_id)
    if not equipment:
        raise HTTPException(status_code=404, detail="Оборудование не найдено")
    safe_name = equipment["name"].replace("/", "-")
    folder = _Path("docs") / safe_name
    folder.mkdir(parents=True, exist_ok=True)

    # имя от клиента — только имя, без путей, и с проверкой расширения
    clean_name = safe_filename(file.filename)
    dest = folder / clean_name

    written = 0
    with dest.open("wb") as f:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > MAX_DOC_BYTES:
                f.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Файл больше 50 МБ")
            f.write(chunk)
    try:
        log_action(username=user["username"], role=user["role"],
            action="document_uploaded",
            target=f"equipment:{equipment_id}", details=str(file.filename))
    except Exception:
        pass
    # В базу знаний — фоном. Без этого ИИ не увидит документ: файл
    # окажется на диске, в карточке, но не в поиске.
    from backend.services.quick_ingest import index_uploaded_pdf
    background_tasks.add_task(index_uploaded_pdf, dest, safe_name)

    return {"success": True, "name": clean_name, "url": f"/docs-files/{safe_name}/{clean_name}"}


# ── Смена своего пароля ───────────────────────────────────
@app.post("/api/auth/change-password")
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


# ── Смена пароля другому пользователю (только admin) ─────
@app.put("/api/settings/users/{user_id}/password")
def set_user_password_route(user_id: int, request: dict, user: dict = Depends(require_roles("admin"))):
    from backend.services.auth_service import set_password, validate_password_strength
    new_p = request.get("password", "")
    try:
        validate_password_strength(new_p)
    except ValueError as e:
        return {"success": False, "message": str(e)}
    set_password(user_id, new_p)
    log_action(username=user["username"], role=user["role"], action="user_password_changed", target=f"user:{user_id}")
    return {"success": True}


@app.get("/my-regulation")
def my_regulation_page(request: Request):
    return templates.TemplateResponse(request=request, name="my_regulation.html")


@app.get("/checklist")
def checklist_page(request: Request):
    return templates.TemplateResponse(request=request, name="checklist.html")


# ── График ТО ─────────────────────────────────────────────
@app.get("/maintenance")
def maintenance_page(request: Request):
    return templates.TemplateResponse(request=request, name="maintenance.html")

@app.get("/api/maintenance/schedule")
def get_maintenance_schedule(year: int = 2026, user: dict = Depends(get_current_user)):
    import sqlite3 as _sq
    conn = _sq.connect(DB_NAME); conn.row_factory = _sq.Row
    rows = conn.execute("SELECT ms.*, e.name as equipment_name, e.location FROM maintenance_schedule ms LEFT JOIN equipment e ON e.id=ms.equipment_id WHERE ms.year=? ORDER BY e.location, e.name, ms.work_name", (year,)).fetchall()
    logs = conn.execute("SELECT * FROM maintenance_log WHERE year=?", (year,)).fetchall()
    conn.close()
    return {"success": True, "schedule": [dict(r) for r in rows], "logs": [dict(l) for l in logs]}

@app.post("/api/maintenance/schedule")
def create_maintenance_schedule(request: dict, user: dict = Depends(require_roles("admin","director","chief_engineer","chief_mechanic","chief_electrician"))):
    import sqlite3 as _sq
    conn = _sq.connect(DB_NAME)
    cur = conn.execute("INSERT INTO maintenance_schedule (equipment_id,work_name,work_type,months,duration_hours,responsible,year,created_by) VALUES (?,?,?,?,?,?,?,?)",
        (request["equipment_id"], request["work_name"], request.get("work_type","monthly"),
         request.get("months","1,2,3,4,5,6,7,8,9,10,11,12"), request.get("duration_hours",0.5),
         request.get("responsible"), request.get("year",2026), user["username"]))
    conn.commit(); conn.close()
    return {"success": True, "id": cur.lastrowid}

@app.delete("/api/maintenance/schedule/{schedule_id}")
def delete_maintenance_schedule(schedule_id: int, user: dict = Depends(require_roles("admin","director","chief_engineer","chief_mechanic"))):
    import sqlite3 as _sq
    conn = _sq.connect(DB_NAME)
    conn.execute("DELETE FROM maintenance_schedule WHERE id=?", (schedule_id,))
    conn.commit(); conn.close()
    return {"success": True}

@app.post("/api/maintenance/log")
def log_maintenance_done(request: dict, user: dict = Depends(get_current_user)):
    import sqlite3 as _sq
    from datetime import datetime as _dt
    conn = _sq.connect(DB_NAME, timeout=10)
    conn.execute("INSERT INTO maintenance_log (plan_id,schedule_id,equipment_id,work_name,month,year,done_at,done_by,note) VALUES (?,?,?,?,?,?,?,?,?)",
        (request["schedule_id"], request["schedule_id"], request["equipment_id"], request["work_name"],
         request["month"], request["year"], _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
         user["full_name"] or user["username"], request.get("note","")))
    conn.commit(); conn.close()
    return {"success": True}

@app.delete("/api/maintenance/log")
def unlog_maintenance(request: dict, user: dict = Depends(get_current_user)):
    import sqlite3 as _sq
    conn = _sq.connect(DB_NAME)
    conn.execute("DELETE FROM maintenance_log WHERE schedule_id=? AND month=? AND year=?",
        (request["schedule_id"], request["month"], request["year"]))
    conn.commit(); conn.close()
    return {"success": True}


@app.post("/api/equipment/{equipment_id}/documents/upload-b64")
async def upload_doc_b64(equipment_id: int, request: dict, background_tasks: BackgroundTasks, user: dict = Depends(require_roles("admin","director","chief_engineer","chief_mechanic","chief_electrician"))):
    import base64 as _b64
    from pathlib import Path as _Path
    equipment = get_equipment(equipment_id)
    if not equipment:
        return {"success": False, "message": "Оборудование не найдено"}
    safe_name = str(equipment["name"]).replace("/", "-")
    folder = _Path("docs") / safe_name
    folder.mkdir(parents=True, exist_ok=True)
    filename = safe_filename(request.get("filename"))
    data = request.get("data", "")
    try:
        file_bytes = _b64.b64decode(data)
        if len(file_bytes) > MAX_DOC_BYTES:
            raise HTTPException(status_code=413, detail="Файл больше 50 МБ")
        (folder / filename).write_bytes(file_bytes)
    except Exception as e:
        return {"success": False, "message": str(e)}
    # записываем в БД
    try:
        import sqlite3 as _sq
        from datetime import datetime as _dt
        file_path = f"{safe_name}/{filename}"
        conn2 = _sq.connect(DB_NAME)
        conn2.execute(
            "INSERT INTO equipment_documents (equipment_id, title, file_path, doc_type, added_by, added_at, is_active) VALUES (?,?,?,?,?,?,1)",
            (equipment_id, filename, file_path, "manual", user["username"], _dt.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        conn2.commit()
        conn2.close()
    except Exception as e:
        pass
    from backend.services.quick_ingest import index_uploaded_pdf
    background_tasks.add_task(index_uploaded_pdf, folder / filename, safe_name)

    return {"success": True, "name": filename, "url": f"/docs-files/{safe_name}/{filename}"}


@app.delete("/api/equipment/{equipment_id}/documents/{doc_id}")
def delete_equipment_doc(equipment_id: int, doc_id: int, user: dict = Depends(require_roles("admin","director","chief_engineer","chief_mechanic","chief_electrician"))):
    import sqlite3 as _sq
    conn = _sq.connect(DB_NAME)
    row = conn.execute("SELECT file_path FROM equipment_documents WHERE id=? AND equipment_id=?", (doc_id, equipment_id)).fetchone()
    if row:
        conn.execute("UPDATE equipment_documents SET is_active=0 WHERE id=?", (doc_id,))
        conn.commit()
    conn.close()
    return {"success": True}


@app.get("/api/technolog/params")
def get_technolog_params(user: dict = Depends(get_current_user)):
    import sqlite3 as _sq
    conn = _sq.connect(DB_NAME, timeout=10)
    conn.row_factory = _sq.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS technolog_params (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        stage TEXT NOT NULL, param_name TEXT NOT NULL, unit TEXT,
        min_val REAL, max_val REAL, target_val REAL,
        updated_by TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(stage, param_name))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS technolog_params_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, param_id INTEGER,
        stage TEXT, param_name TEXT,
        old_min REAL, old_max REAL, old_target REAL,
        new_min REAL, new_max REAL, new_target REAL,
        changed_by TEXT, changed_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    conn.commit()
    rows = conn.execute("SELECT * FROM technolog_params ORDER BY stage, param_name").fetchall()
    conn.close()
    return {"success": True, "params": [dict(r) for r in rows]}

@app.put("/api/technolog/params/{param_id}")
def update_technolog_param(param_id: int, request: dict, user: dict = Depends(require_roles("admin","director","chief_engineer","technologist"))):
    import sqlite3 as _sq
    from datetime import datetime as _dt
    conn = _sq.connect(DB_NAME, timeout=10)
    conn.row_factory = _sq.Row
    old = conn.execute("SELECT * FROM technolog_params WHERE id=?", (param_id,)).fetchone()
    if not old:
        conn.close()
        return {"success": False, "message": "Не найден"}
    conn.execute("""INSERT INTO technolog_params_log
        (param_id,stage,param_name,old_min,old_max,old_target,new_min,new_max,new_target,changed_by,changed_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (param_id,old["stage"],old["param_name"],old["min_val"],old["max_val"],old["target_val"],
         request.get("min_val"),request.get("max_val"),request.get("target_val"),
         user["full_name"] or user["username"],_dt.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.execute("UPDATE technolog_params SET min_val=?,max_val=?,target_val=?,updated_by=?,updated_at=? WHERE id=?",
        (request.get("min_val"),request.get("max_val"),request.get("target_val"),
         user["full_name"] or user["username"],_dt.now().strftime("%Y-%m-%d %H:%M:%S"),param_id))
    conn.commit()
    conn.close()
    return {"success": True}

@app.get("/api/technolog/params/{param_id}/history")
def get_param_history(param_id: int, user: dict = Depends(get_current_user)):
    import sqlite3 as _sq
    conn = _sq.connect(DB_NAME, timeout=10)
    conn.row_factory = _sq.Row
    rows = conn.execute("SELECT * FROM technolog_params_log WHERE param_id=? ORDER BY changed_at DESC LIMIT 20",(param_id,)).fetchall()
    conn.close()
    return {"success": True, "history": [dict(r) for r in rows]}

@app.post("/api/technolog/params/seed")
def seed_technolog_params(user: dict = Depends(get_current_user)):
    import sqlite3 as _sq
    from datetime import datetime as _dt
    conn = _sq.connect(DB_NAME, timeout=10)
    defaults = [
        ("Массаподготовка","Влажность массы","%",18,22,20),
        ("Массаподготовка","Зернистость помола","мм",0,3,1.5),
        ("Массаподготовка","Загрузка питателя PL024-1","%",60,95,80),
        ("Массаподготовка","Загрузка питателя PL024-2","%",60,95,80),
        ("Массаподготовка","Частота питателя PL024-1","Гц",30,50,40),
        ("Массаподготовка","Частота питателя PL024-2","Гц",30,50,40),
        ("Массаподготовка","Частота KP-10","Гц",20,45,35),
        ("Массаподготовка","Влажность добавки (уголь)","%",8,14,11),
        ("Формовка","Давление в экструдере","бар",25,45,35),
        ("Формовка","Влажность сырца","%",16,20,18),
        ("Формовка","Длина кирпича-сырца","мм",248,252,250),
        ("Формовка","Ширина кирпича-сырца","мм",118,122,120),
        ("Формовка","Высота кирпича-сырца","мм",63,67,65),
        ("Формовка","Скорость экструдера","м/мин",8,14,11),
        ("Сушка","Температура зона 1","°C",40,70,55),
        ("Сушка","Температура зона 2","°C",60,90,75),
        ("Сушка","Температура зона 3","°C",80,110,95),
        ("Сушка","Влажность на выходе","%",1,4,2),
        ("Сушка","Время сушки","час",20,30,24),
        ("Обжиг","Температура обжига (макс)","°C",950,1050,1000),
        ("Обжиг","Скорость вагонеток","мин/толч",12,20,15),
        ("Обжиг","Расход угля","кг/час",80,140,110),
        ("Обжиг","Температура дымовых газов","°C",100,180,140),
        ("Упаковка","Брак (норма)","%",0,3,1),
    ]
    for stage,name,unit,mn,mx,tgt in defaults:
        try:
            conn.execute("INSERT OR IGNORE INTO technolog_params (stage,param_name,unit,min_val,max_val,target_val,updated_by,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (stage,name,unit,mn,mx,tgt,user["username"],_dt.now().strftime("%Y-%m-%d %H:%M:%S")))
        except: pass
    conn.commit()
    conn.close()
    return {"success": True}


@app.post("/api/technolog/params")
def create_technolog_param(request: dict, user: dict = Depends(require_roles("admin","director","chief_engineer","technologist"))):
    import sqlite3 as _sq
    from datetime import datetime as _dt
    conn = _sq.connect(DB_NAME, timeout=10)
    try:
        cur = conn.execute("""INSERT INTO technolog_params
            (stage,param_name,unit,min_val,max_val,target_val,updated_by,updated_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            (request["stage"], request["param_name"], request.get("unit"),
             request.get("min_val"), request.get("max_val"), request.get("target_val"),
             user["full_name"] or user["username"], _dt.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        return {"success": True, "id": cur.lastrowid}
    except Exception as e:
        return {"success": False, "message": str(e)}
    finally:
        conn.close()

@app.delete("/api/technolog/params/{param_id}")
def delete_technolog_param(param_id: int, user: dict = Depends(require_roles("admin","director","chief_engineer","technologist"))):
    import sqlite3 as _sq
    conn = _sq.connect(DB_NAME, timeout=10)
    conn.execute("DELETE FROM technolog_params WHERE id=?", (param_id,))
    conn.commit()
    conn.close()
    return {"success": True}


@app.post("/api/technolog/params")
def create_technolog_param(request: dict, user: dict = Depends(require_roles("admin","director","chief_engineer","technologist"))):
    import sqlite3 as _sq
    from datetime import datetime as _dt
    conn = _sq.connect(DB_NAME, timeout=10)
    try:
        cur = conn.execute("""INSERT INTO technolog_params
            (stage,param_name,unit,min_val,max_val,target_val,updated_by,updated_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            (request["stage"], request["param_name"], request.get("unit"),
             request.get("min_val"), request.get("max_val"), request.get("target_val"),
             user["full_name"] or user["username"], _dt.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        return {"success": True, "id": cur.lastrowid}
    except Exception as e:
        return {"success": False, "message": str(e)}
    finally:
        conn.close()

@app.delete("/api/technolog/params/{param_id}")
def delete_technolog_param(param_id: int, user: dict = Depends(require_roles("admin","director","chief_engineer","technologist"))):
    import sqlite3 as _sq
    conn = _sq.connect(DB_NAME, timeout=10)
    conn.execute("DELETE FROM technolog_params WHERE id=?", (param_id,))
    conn.commit()
    conn.close()
    return {"success": True}


# ── Склад запчастей ───────────────────────────────────────
@app.get("/parts")
def parts_page(request: Request):
    return templates.TemplateResponse(request=request, name="parts.html")

@app.get("/api/parts")
def get_parts(user: dict = Depends(get_current_user)):
    import sqlite3 as _sq
    conn = _sq.connect(DB_NAME, timeout=10); conn.row_factory = _sq.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS parts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, part_number TEXT, category TEXT DEFAULT 'other',
        equipment_id INTEGER, equipment_name TEXT,
        unit TEXT DEFAULT 'шт', quantity REAL DEFAULT 0,
        min_quantity REAL DEFAULT 1,
        last_used_at TEXT, created_by TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS parts_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, part_id INTEGER,
        quantity_change REAL, direction TEXT,
        changed_by TEXT, changed_at TEXT DEFAULT CURRENT_TIMESTAMP, note TEXT)""")
    conn.commit()
    rows = conn.execute("""SELECT p.*, e.name as eq_name FROM parts p
        LEFT JOIN equipment e ON e.id=p.equipment_id ORDER BY p.quantity<=p.min_quantity DESC, p.name""").fetchall()
    conn.close()
    parts=[dict(r) for r in rows]
    for p in parts:
        p['equipment_name']=p.pop('eq_name',None) or p.get('equipment_name')
    return {"success": True, "parts": parts}

@app.post("/api/parts")
def create_part(request: dict, user: dict = Depends(require_roles("admin","director","chief_engineer","chief_mechanic","chief_electrician"))):
    import sqlite3 as _sq
    from datetime import datetime as _dt
    conn = _sq.connect(DB_NAME, timeout=10)
    cur = conn.execute("""INSERT INTO parts (name,part_number,category,equipment_id,unit,quantity,min_quantity,created_by,created_at)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (request["name"], request.get("part_number"), request.get("category","other"),
         request.get("equipment_id"), request.get("unit","шт"),
         request.get("quantity",0), request.get("min_quantity",1),
         user["full_name"] or user["username"], _dt.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit(); conn.close()
    return {"success": True, "id": cur.lastrowid}

@app.post("/api/parts/{part_id}/move")
def move_part(part_id: int, request: dict, user: dict = Depends(get_current_user)):
    import sqlite3 as _sq
    from datetime import datetime as _dt
    conn = _sq.connect(DB_NAME, timeout=10); conn.row_factory = _sq.Row
    part = conn.execute("SELECT * FROM parts WHERE id=?", (part_id,)).fetchone()
    if not part: conn.close(); return {"success": False, "message": "Не найдено"}
    qty_change = float(request.get("quantity", 0))
    new_qty = max(0, float(part["quantity"]) + qty_change)
    now = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE parts SET quantity=?,last_used_at=? WHERE id=?", (new_qty, now, part_id))
    conn.execute("INSERT INTO parts_log (part_id,quantity_change,direction,changed_by,changed_at) VALUES (?,?,?,?,?)",
        (part_id, abs(qty_change), "in" if qty_change>0 else "out",
         user["full_name"] or user["username"], now))
    conn.commit(); conn.close()
    return {"success": True, "new_quantity": new_qty}


@app.get("/parts")
def parts_page(request: Request):
    return templates.TemplateResponse(request=request, name="parts.html")

@app.get("/api/parts")
def get_parts(user: dict = Depends(get_current_user)):
    import sqlite3 as _sq
    conn = _sq.connect(DB_NAME, timeout=10); conn.row_factory = _sq.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS parts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, part_number TEXT, category TEXT DEFAULT 'other',
        equipment_id INTEGER, unit TEXT DEFAULT 'шт',
        quantity REAL DEFAULT 0, min_quantity REAL DEFAULT 1,
        last_used_at TEXT, created_by TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS parts_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, part_id INTEGER,
        quantity_change REAL, direction TEXT,
        changed_by TEXT, changed_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    conn.commit()
    rows = conn.execute("""SELECT p.*, e.name as eq_name FROM parts p
        LEFT JOIN equipment e ON e.id=p.equipment_id ORDER BY p.name""").fetchall()
    conn.close()
    parts=[{**dict(r), 'equipment_name': r['eq_name']} for r in rows]
    return {"success": True, "parts": parts}

@app.post("/api/parts")
def create_part(request: dict, user: dict = Depends(require_roles("admin","director","chief_engineer","chief_mechanic","chief_electrician"))):
    import sqlite3 as _sq
    from datetime import datetime as _dt
    conn = _sq.connect(DB_NAME, timeout=10)
    cur = conn.execute("INSERT INTO parts (name,part_number,category,equipment_id,unit,quantity,min_quantity,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (request["name"], request.get("part_number"), request.get("category","other"),
         request.get("equipment_id"), request.get("unit","шт"),
         request.get("quantity",0), request.get("min_quantity",1),
         user["full_name"] or user["username"], _dt.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit(); conn.close()
    return {"success": True, "id": cur.lastrowid}

@app.post("/api/parts/{part_id}/move")
def move_part(part_id: int, request: dict, user: dict = Depends(get_current_user)):
    import sqlite3 as _sq
    from datetime import datetime as _dt
    conn = _sq.connect(DB_NAME, timeout=10); conn.row_factory = _sq.Row
    part = conn.execute("SELECT * FROM parts WHERE id=?", (part_id,)).fetchone()
    if not part: conn.close(); return {"success": False, "message": "Не найдено"}
    new_qty = max(0, float(part["quantity"]) + float(request.get("quantity",0)))
    now = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE parts SET quantity=?,last_used_at=? WHERE id=?", (new_qty, now, part_id))
    conn.execute("INSERT INTO parts_log (part_id,quantity_change,direction,changed_by,changed_at) VALUES (?,?,?,?,?)",
        (part_id, abs(float(request.get("quantity",0))), "in" if float(request.get("quantity",0))>0 else "out",
         user["full_name"] or user["username"], now))
    conn.commit(); conn.close()
    return {"success": True, "new_quantity": new_qty}
