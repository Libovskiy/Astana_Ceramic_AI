"""
Роуты лаборатории. Подключаются к main.py двумя строками:

    from backend.api.lab_routes import router as lab_router
    app.include_router(lab_router)

Разместить: backend/api/lab_routes.py
"""

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from backend.services.auth_service import get_user_by_session
from backend.services.lab_service import (
    create_entry,
    delete_entry,
    get_entries_grouped,
    get_product_types,
    add_product_type,
    archive_product_type,
    get_plain_summary,
    save_consultation,
    get_consultations,
    build_journal_context,
    mark_complete,
    get_pending,
    update_entry,
    get_entries,
    get_entry,
    get_best_mixes,
    get_moisture_effect,
    find_similar,
    get_summary
)
from backend.services.ai_service import suggest_lab_mix, lab_consult
from backend.services.audit_service import log_action


router = APIRouter(tags=["lab"])

templates = Jinja2Templates(directory="frontend/templates")


# Кто вообще заходит в раздел.
LAB_ROLES = (
    "lab_technician", "technologist",
    "chief_engineer", "director", "admin", "analyst", "engineer"
)

# Кто ведёт журнал.
#
# Лаборант и технолог — по работе. Зам. директора и админ — потому
# что кто-то должен уметь поправить запись, когда лаборант в
# отпуске или ошибся, а протокол уже подшит.
#
# Аналитик — только просмотр: его работа читать цифры, а не менять.
#
# Оговорка, которую стоит держать в голове: чем больше людей правят
# лабораторные данные, тем меньше им доверия. Журнал действий пишет,
# кто что менял, но восстановить исходное значение он не даёт.
# Если через месяц окажется, что цифры "гуляют", первым делом
# сузьте этот список обратно до лаборанта и технолога.
LAB_WRITE_ROLES = (
    "lab_technician", "technologist",
    "chief_engineer", "director", "admin"
)

# Кому раздел открывается сразу на АНАЛИТИКЕ, а не на журнале.
# Директору и заму карточки замеров не нужны — им нужен ответ
# "какой состав даёт лучшую марку".
# Кто может УДАЛЯТЬ записи журнала.
#
# Лаборанта здесь намеренно нет: он вносит данные, а не решает, каким
# из них не место в истории. Ошибся — исправит, а удаление это уже
# вопрос ответственности за отчётность.
#
# Каждое удаление пишется в журнал действий: восстановить запись
# нельзя, и единственным следом остаётся строка "кто и что удалил".
LAB_DELETE_ROLES = ("technologist", "chief_engineer", "director", "admin")

ANALYTICS_FIRST_ROLES = (
    "director", "chief_engineer", "analyst", "engineer", "technologist"
)


class EntryRequest(BaseModel):
    data: dict


def lab_user(session_token: str | None = Cookie(default=None)):

    user = get_user_by_session(session_token)

    if user is None:
        raise HTTPException(status_code=401, detail="Не авторизован.")

    if user["role"] not in LAB_ROLES:
        raise HTTPException(status_code=403, detail="Раздел лаборатории вам не доступен.")

    return user


@router.get("/lab")
def lab_page(request: Request):
    return templates.TemplateResponse(request=request, name="lab.html")


@router.get("/api/lab/entries")
def entries(
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 60,
    user: dict = Depends(lab_user)
):

    return {
        "success": True,
        "entries": get_entries(limit=limit, date_from=date_from, date_to=date_to),
        "pending": get_pending(),
        "can_write": user["role"] in LAB_WRITE_ROLES,
        "analytics_first": user["role"] in ANALYTICS_FIRST_ROLES,
        "role": user["role"]
    }


@router.post("/api/lab/entries")
def create(request: EntryRequest, user: dict = Depends(lab_user)):

    if user["role"] not in LAB_WRITE_ROLES:
        raise HTTPException(status_code=403, detail="Запись в журнал — работа лаборанта и технолога.")

    try:
        entry_id = create_entry(request.data, created_by=user.get("full_name") or user["username"])
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    return {"success": True, "id": entry_id}


@router.put("/api/lab/entries/{entry_id}")
def update(entry_id: int, request: EntryRequest, user: dict = Depends(lab_user)):
    """
    Дописать то, что стало известно позже. Утром лаборант знает
    шихту, а вес готовых изделий и марку — только когда вагонетка
    выйдет из печи, через несколько суток.
    """

    if user["role"] not in LAB_WRITE_ROLES:
        raise HTTPException(status_code=403, detail="Правка журнала — работа лаборанта и технолога.")

    if not update_entry(entry_id, request.data):
        raise HTTPException(status_code=404, detail="Запись не найдена или нечего менять.")

    return {"success": True, "entry": get_entry(entry_id)}


@router.get("/api/lab/analysis")
def analysis(user: dict = Depends(lab_user)):
    """Что говорят накопленные данные."""

    return {
        "success": True,
        "summary": get_summary(),
        "best_mixes": get_best_mixes(),
        "moisture_effect": get_moisture_effect()
    }


@router.get("/api/lab/similar")
def similar(
    clay_percent: float,
    moisture: float | None = None,
    user: dict = Depends(lab_user)
):

    return {"success": True, **find_similar(clay_percent, moisture)}


@router.post("/api/lab/suggest")
def suggest(request: EntryRequest, user: dict = Depends(lab_user)):
    """
    Подсказка ИИ по журналу. Он не считает сам — читает уже
    посчитанную статистику и объясняет её словами, честно говоря,
    когда записей мало.
    """

    data = request.data

    clay = data.get("clay_percent")
    moisture = data.get("moisture_optima")

    similar_result = find_similar(clay, moisture) if clay else {"stats": None}

    conditions = (
        f"глина {clay}% / песок {data.get('sand_percent') or (100 - clay if clay else '?')}%, "
        f"влажность шихты {moisture or 'не указана'}%, "
        f"вид продукции {data.get('product_production') or 'не указан'}"
    )

    text = suggest_lab_mix(
        current_conditions=conditions,
        best_mixes=get_best_mixes(),
        moisture_effect=get_moisture_effect(),
        similar_stats=similar_result.get("stats")
    )

    if not text:
        return {
            "success": True,
            "suggestion": None,
            "message": (
                "Пока нечего сказать: в журнале мало записей с "
                "заполненной маркой прочности. Подсказка появится, "
                "когда накопится статистика."
            )
        }

    return {"success": True, "suggestion": text, "stats": similar_result.get("stats")}

class CompleteRequest(BaseModel):
    complete: bool = True


@router.post("/api/lab/entries/{entry_id}/complete")
def complete(entry_id: int, request: CompleteRequest, user: dict = Depends(lab_user)):
    """
    "Отчёт закончен" — или снятие отметки, если вспомнили, что
    чего-то не хватает.
    """

    if user["role"] not in LAB_WRITE_ROLES:
        raise HTTPException(status_code=403, detail="Отмечать отчёт — работа лаборанта и технолога.")

    who = user.get("full_name") or user["username"]

    if not mark_complete(entry_id, who, complete=request.complete):
        raise HTTPException(status_code=404, detail="Запись не найдена.")

    return {"success": True, "entry": get_entry(entry_id)}

# =========================================================
# РАЗГОВОР С ACAI
# =========================================================
# Бланк отвечает на "что было", а лаборанту нужно "что делать":
# глина пришла жёлтая, песок влажный — что менять. Формой это не
# задать, вариантов больше, чем полей.


class AskRequest(BaseModel):
    question: str


@router.post("/api/lab/consult")
def consult(request: AskRequest, user: dict = Depends(lab_user)):

    if user["role"] not in LAB_WRITE_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Спрашивать может лаборант, технолог или зам. директора. Остальным доступна история."
        )

    question = (request.question or "").strip()

    if len(question) < 5:
        raise HTTPException(status_code=400, detail="Опишите вопрос словами.")

    context = build_journal_context()

    answer = lab_consult(
        question=question,
        journal_stats=context,
        history=get_consultations(limit=3)
    )

    if not answer:
        return {
            "success": True,
            "answer": None,
            "message": "ACAI сейчас недоступен. Попробуйте позже."
        }

    save_consultation(
        question=question,
        answer=answer,
        context=context,
        author=user.get("full_name") or user["username"],
        author_role=user["role"]
    )

    return {"success": True, "answer": answer}


@router.get("/api/lab/consult")
def consult_history(user: dict = Depends(lab_user)):
    """
    История вопросов и ответов — видна ВСЕМ, у кого есть доступ в
    раздел, включая офис. Если лаборант уже спрашивал про жёлтую
    глину, полезнее прочитать ответ, чем спрашивать заново.
    """

    return {
        "success": True,
        "consultations": get_consultations(),
        "can_ask": user["role"] in LAB_WRITE_ROLES
    }


@router.get("/api/lab/plain")
def plain(user: dict = Depends(lab_user)):
    """Сводка простыми словами — для тех, кто не работает с шихтой."""

    return {"success": True, "lines": get_plain_summary()}

# =========================================================
# ВИДЫ ПРОДУКЦИИ
# =========================================================


class ProductRequest(BaseModel):
    name: str


@router.get("/api/lab/products")
def products(user: dict = Depends(lab_user)):

    return {
        "success": True,
        "products": get_product_types(),
        "can_edit": user["role"] in LAB_WRITE_ROLES
    }


@router.post("/api/lab/products")
def add_product(request: ProductRequest, user: dict = Depends(lab_user)):
    """Новый вид кирпича — номенклатура меняется, код ради этого не трогаем."""

    if user["role"] not in LAB_WRITE_ROLES:
        raise HTTPException(status_code=403, detail="Добавлять виды продукции вам нельзя.")

    try:
        product_id = add_product_type(request.name, user.get("full_name") or user["username"])
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    log_action(
        username=user["username"], role=user["role"],
        action="lab_product_added", target=f"product:{product_id}",
        details=request.name
    )

    return {"success": True, "products": get_product_types()}


@router.delete("/api/lab/products/{product_id}")
def remove_product(product_id: int, user: dict = Depends(lab_user)):
    """
    Убрать вид из списка. Именно убрать, а не удалить: к нему
    привязаны записи за прошлые месяцы, и они не должны остаться
    без названия продукции.
    """

    if user["role"] not in LAB_DELETE_ROLES:
        raise HTTPException(status_code=403, detail="Убирать виды продукции вам нельзя.")

    if not archive_product_type(product_id):
        raise HTTPException(status_code=404, detail="Вид не найден.")

    log_action(
        username=user["username"], role=user["role"],
        action="lab_product_archived", target=f"product:{product_id}"
    )

    return {"success": True, "products": get_product_types()}


# =========================================================
# ЖУРНАЛ ПО ВИДАМ
# =========================================================

@router.get("/api/lab/grouped")
def grouped(
    date_from: str | None = None,
    date_to: str | None = None,
    user: dict = Depends(lab_user)
):
    """
    Записи по видам кирпича. Смешивать полнотелый с блоком нельзя:
    у них разные вес, геометрия и марка, и средняя по всем видам
    сразу — число, которое ничего не значит.
    """

    return {
        "success": True,
        "groups": get_entries_grouped(date_from=date_from, date_to=date_to),
        "can_write": user["role"] in LAB_WRITE_ROLES,
        "can_delete": user["role"] in LAB_DELETE_ROLES
    }


@router.delete("/api/lab/entries/{entry_id}")
def remove_entry(entry_id: int, user: dict = Depends(lab_user)):

    if user["role"] not in LAB_DELETE_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Удалять записи журнала может технолог, зам. директора, директор или администратор."
        )

    snapshot = delete_entry(entry_id)

    if snapshot is None:
        raise HTTPException(status_code=404, detail="Запись не найдена.")

    # Что именно удалили — в журнал действий. Саму запись уже не
    # вернуть, останется только этот след.
    log_action(
        username=user["username"], role=user["role"],
        action="lab_entry_deleted", target=f"lab:{entry_id}",
        details=snapshot
    )

    return {"success": True}

