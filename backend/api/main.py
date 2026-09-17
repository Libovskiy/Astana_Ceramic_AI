"""
Точка входа ACAI: приложение, подключение маршрутов, общие настройки.

Здесь только то, что касается всего сайта сразу:
  - создание таблиц при запуске (init_*),
  - CORS, /static,
  - PAGE_ROLES и page_access_guard — кто на какую страницу допущен
    (списки дублируются в NAV_ITEMS, frontend/static/acai_layout.js;
    совпадение проверяет tests/test_page_roles.py),
  - подключение роутеров.

Сами маршруты — в backend/api/*_routes.py, общие зависимости (вход,
роли, шаблоны) — в backend/api/common.py. Раньше всё лежало здесь,
почти 4000 строк; разнесено 17.09.2026 без изменения поведения.
"""

from backend.config import ALLOWED_ORIGINS
from backend.services.audit_service import init_audit_table
from backend.services.auth_service import get_user_by_session, init_auth_tables
from backend.services.case_service import init_cases_tables
from backend.services.downtime_service import init_downtime_table
from backend.services.equipment_service import init_equipment
from backend.services.knowledge_service import init_knowledge_base
from backend.services.mix_service import init_mix_table
from backend.services.procedures_service import init_procedures_tables
from backend.services.production_log_service import init_production_tables
from backend.services.regulation_service import init_regulation_extensions
from backend.services.task_service import init_task_tables
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.api.common import templates


app = FastAPI()


from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    """
    Ошибка формата запроса — без копии присланных данных в ответе.

    Стандартный ответ FastAPI возвращает поле input: пароль из неудачного
    входа уходил обратно открытым текстом, а на двоичном файле ответ
    вообще падал с ошибкой 500 (нашли tests/test_files.py).
    """
    errors = [{k: v for k, v in error.items() if k not in ("input", "ctx")} for error in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})

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

# ─── Датчики WebHMI ───────────────────────────────────────────────
# Здесь же раньше подключались /api/stages, /api/notes и /api/audit —
# остатки отдельной подсистемы «мониторинга» с JWT-авторизацией. Их
# звал только monitoring.js, который не подключала ни одна страница, а
# выдать JWT было нечем: create_access_token нигде не вызывалась.
# Эндпоинты висели недостижимыми для всех и убраны.
from backend.api.sensor_routes import router as sensor_router
app.include_router(sensor_router)

from backend.api.voice_routes import router as voice_router
app.include_router(voice_router)

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

# Запросы на удаление важных данных (решает владелец). Функцию
# импортировали, но не вызывали — таблицы не было, и список запросов
# у администратора падал с ошибкой 500.
from backend.services.protection_service import init_protection_tables
init_protection_tables()

from backend.services.shift_report_service import init_shift_report_tables
init_shift_report_tables()

from backend.services.team_chat_service import init_team_chat
init_team_chat()

import os as _os_env
from backend.services import usage_service
usage_service.init_usage()

from backend.services import push_service
push_service.init_push()

from backend.services.observation_service import init_observation
init_observation()

# Проверки состояния (датчики, бэкап) — только в основном экземпляре
# (порт 8000); HTTPS-экземпляр запущен с ACAI_LIVE_PROXY.
if not _os_env.environ.get("ACAI_LIVE_PROXY"):
    push_service.start_checks()

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
# /docs-files отдаётся через docs_files_routes с проверкой сессии:
# открытый StaticFiles раздавал все руководства без авторизации.


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
    # Переписка между людьми открыта всем: договориться о подмене или
    # позвать электрика нужно любому, независимо от должности.
    "/messenger": "*",
    "/knowledge": ("director", "chief_engineer", "engineer",
                   "chief_mechanic", "chief_electrician"),
    # lab_technician раньше отсутствовал: логин уводил лаборанта на /lab,
    # а ссылки на /lab у него в меню не было.
    "/lab": ("director", "chief_engineer", "analyst", "technologist", "lab_technician"),
    "/parts": ("director", "chief_engineer", "chief_mechanic",
               "chief_electrician", "mechanic", "engineer", "electrician"),
    "/technolog": ("director", "chief_engineer", "technologist"),
    "/audit": ("director", "chief_engineer", "chief_mechanic", "chief_electrician"),
    # Пользуются ли системой: кто заходит, какие разделы, сколько работы
    "/usage": ("director", "chief_engineer"),
    # полчаса в цеху: подготовка телефона механика, времена, заметки
    "/observe": ("director", "chief_engineer"),
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

    # Учёт использования: кто какой раздел открыл
    usage_service.record_page_view(user["id"], request.url.path)

    return await call_next(request)


# =========================================
# МАРШРУТЫ, ВЫНЕСЕННЫЕ ИЗ main.py
# =========================================
# Порядок подключения важен: при совпадении адресов отвечает тот,
# кто подключён раньше. Он повторяет порядок, в котором маршруты
# стояли в main.py.

from backend.api.pages_routes import router as pages_router
app.include_router(pages_router)

from backend.api.auth_routes import router as auth_router
app.include_router(auth_router)

from backend.api.equipment_routes import router as equipment_router
app.include_router(equipment_router)

from backend.api.knowledge_routes import router as knowledge_router
app.include_router(knowledge_router)

from backend.api.users_routes import router as users_router
app.include_router(users_router)

from backend.api.cases_routes import router as cases_router
app.include_router(cases_router)

from backend.api.reports_routes import router as reports_router
app.include_router(reports_router)

from backend.api.tasks_routes import router as tasks_router
app.include_router(tasks_router)

from backend.api.production_routes import router as production_router
app.include_router(production_router)

from backend.api.push_routes import router as push_router
app.include_router(push_router)

from backend.api.maintenance_routes import router as maintenance_router
app.include_router(maintenance_router)

from backend.api.technolog_routes import router as technolog_router
app.include_router(technolog_router)

from backend.api.parts_routes import router as parts_router
app.include_router(parts_router)

from backend.api.observe_routes import router as observe_router
app.include_router(observe_router)
