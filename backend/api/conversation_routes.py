"""
Роуты переписки по обращению.

Отдельный модуль-роутер, чтобы не править main.py на 2500 строк.
Подключается двумя строками (см. инструкцию в конце файла).

Свою зависимость авторизации объявляем здесь же: она берёт
session_token из cookie и проверяет его через auth_service —
ровно как get_current_user в main.py. Импортировать её ИЗ main.py
нельзя: main.py импортирует этот модуль, получилось бы кольцо.

Разместить: backend/api/conversation_routes.py
"""

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from backend.services.auth_service import (
    get_user_by_session,
    get_assigned_equipment_ids
)
from backend.services.case_service import (
    get_case,
    take_case,
    complete_repair,
    draft_close_case,
    approve_close_case
)
from backend.services.audit_service import log_action
from backend.services.knowledge_service import add_resolution
from backend.services.downtime_service import try_auto_end_downtime_for_case
from backend.services.conversation_service import (
    get_messages,
    post_message,
    resolve_by_worker,
    get_conversations,
    get_case_card,
    generate_reply,
    add_message,
    SPECIALIST_ROLES,
    ACTIVE_STATUSES,
    APPROVER_ROLES
)


router = APIRouter(tags=["conversation"])

# Тот же каталог шаблонов, что и в main.py
templates = Jinja2Templates(directory="frontend/templates")


# =========================================================
# СТРАНИЦА
# =========================================================

@router.get("/chat")
def chat_page(request: Request):
    """Мессенджер обращений: слева список, справа переписка."""

    return templates.TemplateResponse(request=request, name="chat.html")


class MessageRequest(BaseModel):
    text: str


class CommentRequest(BaseModel):
    comment: str = ""


# Кто может брать обращение в работу и завершать ремонт
REPAIR_ROLES = (
    "chief_mechanic", "mechanic",
    "chief_electrician", "electrician",
    "chief_engineer", "engineer", "admin"
)

# Кто составляет черновик закрытия
DRAFT_ROLES = ("shift_supervisor", "admin")


def current_user(session_token: str | None = Cookie(default=None)):

    user = get_user_by_session(session_token)

    if user is None:
        raise HTTPException(status_code=401, detail="Не авторизован.")

    return user


def _check_access(case_id: int, user: dict):
    """
    Рабочий видит переписку только по своим станкам. Остальные роли
    видят все обращения — они и должны отвечать на эскалации.
    """

    case = get_case(case_id)

    if case is None:
        raise HTTPException(status_code=404, detail="Обращение не найдено.")

    if user["role"] == "worker":

        allowed = set(get_assigned_equipment_ids(user["id"]))

        if case.get("equipment_id") not in allowed:
            raise HTTPException(status_code=403, detail="Это обращение не по вашему оборудованию.")

    return case


@router.get("/api/conversation/{case_id}")
def read_conversation(case_id: int, user: dict = Depends(current_user)):

    case = _check_access(case_id, user)

    status = case["status"]

    # Название станка берём из справочника оборудования, а не из
    # текстового поля machine: там лежит строка запроса вроде
    # "упаковочная машина" с маленькой буквы, и в шапке переписки
    # это выглядит неряшливо.
    equipment_name = None

    if case.get("equipment_id"):

        from backend.services.equipment_service import get_equipment

        equipment = get_equipment(case["equipment_id"])

        if equipment:
            equipment_name = equipment["name"]

    # Какие действия доступны ЭТОМУ человеку по ЭТОМУ обращению
    # именно сейчас. Считаем на сервере, а не в браузере: скрытая
    # кнопка не защита, проверки всё равно продублированы в роутах.
    actions = {
        "take": (
            user["role"] in REPAIR_ROLES
            and status in ("Открыто", "Требует специалиста")
        ),
        "complete": (
            user["role"] in REPAIR_ROLES
            and status in ("Открыто", "Требует специалиста", "В работе")
        ),
        "draft": (
            user["role"] in DRAFT_ROLES
            and status in ("Открыто", "Требует специалиста", "В работе")
        ),
        "approve": (
            user["role"] in APPROVER_ROLES
            and status in ("Черновик закрытия", "Требует специалиста", "В работе", "Открыто")
        ),
        "resolve": (
            user["role"] == "worker"
            and status in ("Открыто", "Требует специалиста", "В работе")
        )
    }

    return {
        "success": True,
        "case": {
            "id": case["id"],
            "status": status,
            "machine": equipment_name or case.get("machine"),
            "symptom": case.get("symptom"),
            "equipment_id": case.get("equipment_id"),
            "created_at": case.get("created_at"),
            "assigned_to": case.get("assigned_to"),
            "draft_closed_by": case.get("draft_closed_by"),
            "draft_resolution_comment": case.get("draft_resolution_comment")
        },
        "messages": get_messages(case_id),
        "can_write": status in ACTIVE_STATUSES,
        "is_specialist": user["role"] in SPECIALIST_ROLES,
        "role": user["role"],
        "actions": actions
    }


@router.post("/api/conversation/{case_id}/message")
def send_message(
    case_id: int,
    request: MessageRequest,
    user: dict = Depends(current_user)
):

    _check_access(case_id, user)

    result = post_message(case_id, user, request.text)

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message"))

    return result


@router.post("/api/conversation/{case_id}/resolve")
def resolve(case_id: int, user: dict = Depends(current_user)):

    _check_access(case_id, user)

    result = resolve_by_worker(case_id, user)

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message"))

    return result


@router.post("/api/conversation/{case_id}/retry")
def retry(case_id: int, user: dict = Depends(current_user)):
    """
    Попросить ИИ ещё раз — когда он был недоступен (нет квоты,
    пропал интернет) и рабочий остался без ответа.
    """

    _check_access(case_id, user)

    return {"success": True, "reply": generate_reply(case_id)}


@router.get("/api/conversation")
def conversations(
    scope: str = "active",
    user: dict = Depends(current_user)
):
    """
    scope=active    — открытые и переданные специалисту
    scope=approval  — черновики закрытия (только тем, кто подтверждает)
    scope=closed    — архив
    """

    if scope == "approval" and user["role"] not in APPROVER_ROLES:
        raise HTTPException(status_code=403, detail="Подтверждение закрытия — не ваша роль.")

    items = get_conversations(user, scope=scope)

    if user["role"] == "worker":

        allowed = set(get_assigned_equipment_ids(user["id"]))

        items = [item for item in items if item.get("equipment_id") in allowed]

    return {
        "success": True,
        "conversations": items,
        "can_approve": user["role"] in APPROVER_ROLES,
        "can_draft": user["role"] in ("shift_supervisor", "admin")
    }


@router.get("/api/case-card/{case_id}")
def case_card(case_id: int, user: dict = Depends(current_user)):
    """
    Вся жизнь обращения: когда открыто, сколько стоял станок, вся
    переписка, черновик закрытия с комментарием, кто подтвердил.

    Рабочему доступна только карточка по его станкам, остальным —
    любая: главному инженеру она нужна для подтверждения, директору
    для разбора задним числом.
    """

    _check_access(case_id, user)

    card = get_case_card(case_id)

    if card is None:
        raise HTTPException(status_code=404, detail="Обращение не найдено.")

    card["success"] = True
    card["can_approve"] = user["role"] in APPROVER_ROLES
    card["can_draft"] = user["role"] in ("shift_supervisor", "admin")

    return card



# =========================================================
# ДЕЙСТВИЯ ПРЯМО ИЗ ПЕРЕПИСКИ
# =========================================================
# Раньше специалист, начальник смены и главный инженер работали на
# отдельных страницах, а рабочий — в переписке. Обращение до них
# доходило, но ответить в ту же ветку они не могли, и рабочий не
# видел, что вообще происходит. Теперь все действия делаются здесь
# же и оставляют в ветке служебную запись.


def _who(user):
    return user.get("full_name") or user.get("username")


@router.post("/api/conversation/{case_id}/take")
def take(case_id: int, user: dict = Depends(current_user)):
    """Специалист забирает обращение себе."""

    if user["role"] not in REPAIR_ROLES:
        raise HTTPException(status_code=403, detail="Брать обращения в работу — не ваша роль.")

    _check_access(case_id, user)

    try:
        take_case(case_id, assigned_to=_who(user))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    add_message(
        case_id,
        "system",
        f"{_who(user)} взял обращение в работу.",
        author=_who(user),
        author_role=user["role"]
    )

    log_action(
        username=user["username"], role=user["role"],
        action="case_take", target=f"case:{case_id}"
    )

    return {"success": True, "messages": get_messages(case_id)}


@router.post("/api/conversation/{case_id}/complete")
def complete(case_id: int, request: CommentRequest, user: dict = Depends(current_user)):
    """
    Специалист описывает, что сделал. Обращение НЕ закрывается —
    уходит в черновик и ждёт главного инженера. Специалист не должен
    сам объявлять станок исправным.
    """

    if user["role"] not in REPAIR_ROLES:
        raise HTTPException(status_code=403, detail="Завершать ремонт — не ваша роль.")

    if not request.comment.strip():
        raise HTTPException(status_code=400, detail="Опишите, что было сделано.")

    _check_access(case_id, user)

    try:
        complete_repair(case_id, resolution_comment=request.comment, completed_by=_who(user))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    add_message(
        case_id, "specialist",
        f"Ремонт выполнен: {request.comment}",
        author=_who(user), author_role=user["role"]
    )

    add_message(
        case_id, "system",
        "Ожидает подтверждения главного инженера.",
        author=_who(user), author_role=user["role"]
    )

    log_action(
        username=user["username"], role=user["role"],
        action="case_complete_repair", target=f"case:{case_id}",
        details=request.comment
    )

    return {"success": True, "messages": get_messages(case_id)}


@router.post("/api/conversation/{case_id}/draft-close")
def draft(case_id: int, request: CommentRequest, user: dict = Depends(current_user)):
    """Черновик закрытия от начальника смены."""

    if user["role"] not in DRAFT_ROLES:
        raise HTTPException(status_code=403, detail="Черновик закрытия составляет начальник смены.")

    _check_access(case_id, user)

    draft_close_case(case_id, drafted_by=_who(user), draft_comment=request.comment)

    add_message(
        case_id, "system",
        f"{_who(user)} составил черновик закрытия. Ожидает главного инженера.",
        author=_who(user), author_role=user["role"]
    )

    log_action(
        username=user["username"], role=user["role"],
        action="case_draft_close", target=f"case:{case_id}",
        details=request.comment
    )

    return {"success": True, "messages": get_messages(case_id)}


@router.post("/api/conversation/{case_id}/approve")
def approve(case_id: int, request: CommentRequest, user: dict = Depends(current_user)):
    """
    Финальное закрытие главным инженером. Здесь же решение попадает
    в базу знаний — только подтверждённое человеком знание, которого
    не было в документации.
    """

    if user["role"] not in APPROVER_ROLES:
        raise HTTPException(status_code=403, detail="Подтверждать закрытие — не ваша роль.")

    _check_access(case_id, user)

    approve_close_case(case_id, approved_by=_who(user), final_comment=request.comment)

    # Подстраховка: простой не должен остаться висеть, даже если
    # специалист забыл нажать "Завершить ремонт".
    try_auto_end_downtime_for_case(case_id, ended_by=_who(user))

    updated = get_case(case_id)

    add_resolution(
        machine=updated["machine"],
        symptom_text=updated["worker_question"] or updated["symptom"],
        resolution_comment=updated["resolution_comment"],
        case_id=case_id,
        confirmed_by=_who(user)
    )

    add_message(
        case_id, "system",
        f"Обращение закрыто. Подтвердил: {_who(user)}.",
        author=_who(user), author_role=user["role"]
    )

    log_action(
        username=user["username"], role=user["role"],
        action="case_approve_close", target=f"case:{case_id}",
        details=request.comment
    )

    return {"success": True, "messages": get_messages(case_id)}


# =========================================================
# КАК ПОДКЛЮЧИТЬ
# =========================================================
#
# В backend/api/main.py, ПОСЛЕ строки app = FastAPI(), добавить:
#
#     from backend.api.conversation_routes import router as conversation_router
#     app.include_router(conversation_router)
#
# Перед первым запуском выполнить миграцию:
#     python migrate_chat_author.py
