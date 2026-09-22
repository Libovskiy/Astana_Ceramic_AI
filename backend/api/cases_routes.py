"""
Обращения и диагностика: создание (/diagnose, /chat), шаги ИИ, отзыв, черновик и подтверждение закрытия, очередь работ, журнал событий, ИИ для руководства.

Вынесено из main.py без изменений поведения.
"""

from fastapi import APIRouter
import sqlite3
from backend.config import DB_NAME, MAX_AI_STEPS
from backend.services.ai_service import ask_management_ai
from backend.services.audit_service import log_action
from backend.services.auth_service import get_assigned_equipment_ids
from backend.services.case_service import (
    approve_close_case,
    complete_repair,
    draft_close_case,
    get_case,
    get_recurring_issues,
    get_work_queue,
    search_case_events,
    set_case_equipment,
    set_step,
    take_case,
)
from backend.services.chat_service import save_message
from backend.services.dashboard_service import get_dashboard_data
from backend.services.downtime_service import try_auto_end_downtime_for_case, try_auto_start_downtime
from backend.services.equipment_service import find_equipment_by_machine
from backend.services.knowledge_service import add_resolution
from backend.services.rate_limit_service import check_rate_limit
from backend.services.response_service import build_answer
from backend.services.search_service import continue_diagnosis, search
from fastapi import Depends, HTTPException
from pydantic import BaseModel

from backend.api.common import (
    DASHBOARD_ALLOWED_ROLES,
    WORK_QUEUE_ROLES,
    require_roles,
)

router = APIRouter()

# =========================================
# REQUEST MODELS
# =========================================

class ChatRequest(BaseModel):

    message: str

    case_id: int | None = None

    completed_actions: list[str] = []

    # Период для управленческого помощника: кнопки «сегодня / неделя /
    # месяц» присылают его явно, иначе угадываем по тексту вопроса.
    period: str | None = None


class DiagnosticRequest(BaseModel):

    equipment_id: int

    question: str


class DraftCloseCaseRequest(BaseModel):

    comment: str | None = None


class ApproveCloseCaseRequest(BaseModel):

    comment: str | None = None


class CaseFeedbackRequest(BaseModel):

    helped: bool


class CompleteRepairRequest(BaseModel):

    resolution_comment: str


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
# CASE EVENTS (журнал событий — фильтруемый список обращений)
# =========================================
# Отдельно от audit_log ("Журнал действий" — кто что сделал):
# здесь про сами обращения/неисправности, а не про действия людей.

@router.get("/api/case-events")
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


@router.get("/api/recurring-issues")
def recurring_issues_route(
    user: dict = Depends(require_roles(*DASHBOARD_ALLOWED_ROLES))
):

    return {
        "success": True,
        "issues": get_recurring_issues()
    }


# Роли, которым открыт «Журнал обращений» (/cases). Совпадают со
# списком этой страницы в PAGE_ROLES — механик и электрик тоже видят
# журнал, они по нему и работают.
CASES_OVERVIEW_ROLES = (
    "director", "chief_engineer", "production_chief", "shift_supervisor",
    "chief_mechanic", "mechanic", "chief_electrician", "electrician",
)


@router.get("/api/cases/overview")
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


@router.get("/api/work-queue")
def get_work_queue_route(
    discipline: str | None = None,
    user: dict = Depends(require_roles(*WORK_QUEUE_ROLES))
):

    return {
        "success": True,
        "queue": get_work_queue(discipline=discipline)
    }


@router.post("/api/cases/{case_id}/take")
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


@router.post("/api/cases/{case_id}/complete-repair")
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



# =========================================
# MANAGEMENT AI
# =========================================

@router.post("/management-ai")
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

    # Простои и деньги считает сервер и передаёт готовыми строками:
    # модель их только пересказывает. Период берём из вопроса — у
    # помощника есть кнопки «за сегодня / неделю / месяц».
    from backend.services.downtime_cost_service import losses_text

    period = (request.period or "").strip().lower()
    if period not in ("today", "week", "month"):
        low = question.lower()
        period = ("today" if "сегодня" in low
                  else "month" if ("месяц" in low or "30 дн" in low)
                  else "week")

    try:
        losses = losses_text(period)
    except Exception as error:
        print(f"[management-ai] простои не посчитаны: {error}")
        losses = None

    answer = ask_management_ai(question, dashboard_data, losses=losses)

    if answer is None:
        # Директору «проверьте OPENAI_API_KEY» не говорит ничего: ключ
        # не его забота. Называем причину так, как он может с ней
        # что-то сделать, — и отдельно говорим, что цифры по простоям
        # посчитал сервер и они верные, молчит только пересказ.
        from backend.services.ai_service import unavailable_reason

        outage = unavailable_reason() or "ИИ не ответил"
        tail = (" Цифры по простоям считает сервер, они ниже и не зависят от ИИ."
                if losses else "")

        return {
            "success": False,
            "answer": f"Помощник сейчас не работает — {outage}.{tail}",
            "reason": outage,
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


@router.post("/chat")
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

        from backend.services.conversation_service import escalate_unknown

        lead = answer_data.get("unknown") or "Не могу предложить надёжное решение по этой неисправности."
        reply = escalate_unknown(result["case_id"], request.message, lead, user)
        message = (reply or {}).get("message") or lead

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

    # Что уже помогало на этом станке — отдельной строкой в переписке.
    # Это не зависит от того, воспользовался ли подсказкой сам ИИ:
    # человек должен увидеть прошлое решение дословно.
    try:
        from backend.services.knowledge_service import add_similar_note
        add_similar_note(result["case_id"], request.message)
    except Exception as error:
        print(f"[knowledge] похожий случай не добавлен: {error}")

    # Есть ли названная деталь на складе — отдельной строкой в переписке.
    try:
        from backend.services.part_usage_service import add_stock_note
        add_stock_note(result["case_id"], answer_data["recommendation"])
    except Exception as error:
        print(f"[parts] подсказка по складу не добавлена: {error}")


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

@router.post("/diagnose")
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

        from backend.services.conversation_service import escalate_unknown

        # Честно: «по этому станку нет руководства — зову специалиста»,
        # а не общий совет. Жалоба и причина остаются в переписке.
        lead = answer_data.get("unknown") or "Не могу предложить надёжное решение по этой неисправности."
        reply = escalate_unknown(result["case_id"], request.question, lead, user)
        message = (reply or {}).get("message") or lead

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

@router.post("/case/{case_id}/feedback")
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

@router.post("/case/{case_id}/draft-close")
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

@router.post("/case/{case_id}/approve-close")
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

@router.post("/diagnostic/next")
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
