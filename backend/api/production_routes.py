"""
Производство: план, учёт выпуска, расчёт состава смеси.

Вынесено из main.py без изменений поведения.
"""

from fastapi import APIRouter
from backend.services.ai_service import suggest_mix_proportion
from backend.services.audit_service import log_action
from backend.services.mix_service import (
    create_mix_entry,
    find_similar_batches,
    get_mix_entries,
    update_outcome,
)
from backend.services.production_log_service import (
    BRICK_TYPES,
    check_plan_anomaly,
    get_monthly_plans,
    get_shift_chart_data,
    get_shift_history,
    get_today_production,
    log_shift_production,
    set_monthly_plan,
)
from fastapi import Depends
from pydantic import BaseModel

from backend.api.common import (
    DASHBOARD_ALLOWED_ROLES,
    get_current_user,
    require_roles,
)

router = APIRouter()

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


# =========================================
# MIX LOG (технолог — расчёт глина/песок)
# =========================================

MIX_WRITE_ROLES = ("technologist", "lab_technician")
MIX_READ_ROLES = (
    "technologist", "lab_technician", "director", "chief_engineer",
    "analyst"
)


@router.post("/api/mix")
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


@router.get("/api/mix")
def get_mix_entries_route(
    user: dict = Depends(require_roles(*MIX_READ_ROLES))
):

    return {
        "success": True,
        "entries": get_mix_entries()
    }


@router.post("/api/mix/suggest")
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


@router.post("/api/mix/{entry_id}/outcome")
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


@router.post("/api/mix/similar")
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


@router.get("/api/production/meta")
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



@router.get("/api/production/plan")
def get_production_plan_route(
    user: dict = Depends(require_roles(*DASHBOARD_ALLOWED_ROLES))
):

    return {
        "success": True,
        "plans": get_monthly_plans(),
        "brick_types": list(BRICK_TYPES.keys())
    }


@router.post("/api/production/plan")
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


@router.post("/api/production/log")
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


@router.get("/api/production/today")
def get_production_today_route(
    user: dict = Depends(require_roles(*DASHBOARD_ALLOWED_ROLES))
):

    return {
        "success": True,
        **get_today_production()
    }


@router.get("/api/production/history")
def get_production_history_route(
    date_from: str | None = None,
    date_to: str | None = None,
    user: dict = Depends(require_roles(*DASHBOARD_ALLOWED_ROLES))
):

    return {
        "success": True,
        **get_shift_history(date_from=date_from, date_to=date_to)
    }


@router.get("/api/production/shift-chart")
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
# СМЕННЫЙ ОТЧЁТ ИЗ ЭКСЕЛЯ
# =========================================
# Начальник производства ведёт отчёт в Экселе (файл в Битриксе, доступа
# у сайта нет — загружают руками). Связь односторонняя: Эксель главный,
# сайт читает. Обратной записи нет и не будет: портить чужую отчётность
# нельзя.

# Кто загружает отчёт. Это данные всего завода за год, поэтому список
# узкий — те же, кто отвечает за производство в целом.
# Кто загружает файл отчёта. Владелец, 22.09.2026: начальник
# производства (его файл), начальники смен (они его заполняют),
# главный инженер и аналитик. Директор и admin — как всегда.
REPORT_IMPORT_ROLES = ("admin", "director", "chief_engineer",
                       "production_chief", "shift_supervisor", "analyst")

MAX_REPORT_BYTES = 25 * 1024 * 1024


def _report_date(value) -> str:
    """«2026-09-17» → «17.09.2026». Для сообщений о загрузке файла."""
    text = str(value or "")
    if len(text) < 10:
        return "—"
    return f"{text[8:10]}.{text[5:7]}.{text[0:4]}"


@router.post("/api/production/report-import")
def import_production_report(
    request: dict,
    user: dict = Depends(require_roles(*REPORT_IMPORT_ROLES))
):
    """
    Загрузка файла отчёта: читаем, показываем что прочиталось и что нет.

    Файл принимается целиком в base64 — так же, как документы станков:
    отдельная форма multipart ради одного файла в год не нужна.
    """
    import base64
    import tempfile
    from datetime import datetime
    from pathlib import Path

    from fastapi import HTTPException

    from backend.services.production_report_import import read_workbook
    from backend.services.production_import_service import save_workbook

    filename = (request.get("filename") or "").strip() or "отчёт.xlsx"

    if not filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Нужен файл Excel (.xlsx).")

    try:
        binary = base64.b64decode(request.get("data") or "", validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Файл не прочитался — попробуйте загрузить заново.")

    if not binary:
        raise HTTPException(status_code=400, detail="Пустой файл.")

    if len(binary) > MAX_REPORT_BYTES:
        raise HTTPException(status_code=413, detail="Файл больше 25 МБ.")

    try:
        year = int(request.get("year") or datetime.now().year)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Не понял год отчёта.")

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "report.xlsx"
        path.write_bytes(binary)

        try:
            data = read_workbook(str(path), year)
        except Exception as error:
            # Читать чужой файл — дело ненадёжное: его могли
            # пересохранить, защитить паролем, сломать. Говорим прямо,
            # что не смогли, и ничего не записываем.
            raise HTTPException(
                status_code=400,
                detail=f"Не смог прочитать файл: {error}. Данные на сайте не менялись."
            )

    # Загрузка заменяет год целиком — значит, старой версией файла
    # можно молча затереть свежие данные. Если в файле МЕНЬШЕ, чем уже
    # сохранено, показываем «было / станет» и ждём подтверждения.
    # Больше — грузим молча, это обычное пополнение.
    from backend.services.production_import_service import compare_with_saved

    diff = compare_with_saved(data)

    if diff.get("shrinks") and not request.get("confirm"):
        names = {"months": "месяцев", "shifts": "смен",
                 "downtime": "простоев", "notes": "записей журнала"}
        lost = ", ".join(
            f"{names[key]}: было {diff['current'][key]}, станет {diff['incoming'][key]}"
            for key in diff.get("smaller") or []
        )

        # Главное — даты, а не количество строк. Если в файле нет дней,
        # которые на сайте уже есть, говорим об этом первой строкой.
        head = (
            f"В этом файле последняя смена — {_report_date(diff['incoming'].get('last_shift_date'))}, "
            f"а на сайте уже есть смены до {_report_date(diff['current'].get('last_shift_date'))}. "
            "Похоже, это более старая версия отчёта: свежие дни пропадут."
            if diff.get("older") else
            f"В этом файле меньше данных, чем уже загружено ({lost})."
        )

        return {
            "success": False,
            "needs_confirm": True,
            "diff": diff,
            "message": (
                f"{head} "
                f"Сейчас на сайте файл «{diff.get('filename') or '—'}» "
                f"от {str(diff.get('uploaded_at') or '')[:16]}."
                + (f" В нём тоже меньше: {lost}." if lost and diff.get("older") else "")
            ),
        }

    result = save_workbook(data, filename, user.get("full_name") or user.get("username"))

    log_action(
        username=user["username"], role=user["role"],
        action="production_report_imported", target=f"year:{year}",
        details=(f"{filename}: смен {result['run']['shifts']}, простоев {result['run']['downtime']}, "
                 f"записей журнала {result['run']['notes']}, не разобрано {result['run']['problems']}")
    )

    return {"success": True, **result}


@router.get("/api/production/report-import")
def production_report_state(
    year: int | None = None,
    user: dict = Depends(get_current_user)
):
    """Что сейчас прочитано из Экселя и что не разобралось."""
    from backend.services.production_import_service import summary, history

    return {"success": True, **summary(year), "history": history(5)}


@router.get("/api/production/report-analytics")
def production_report_analytics(
    year: int | None = None,
    user: dict = Depends(get_current_user)
):
    """
    Сводка по сменному отчёту: месяцы, участки, причины, день/ночь.

    Открыта всем, кто видит «Производство»: это работа цеха, и прятать
    её от самого цеха незачем. Считается из того, что прочиталось;
    неразобранное идёт отдельным числом, а не растворяется в итогах.
    """
    from backend.services.production_import_service import analytics, last_day_summary

    return {"success": True, **analytics(year), "last_day": last_day_summary()}


@router.get("/api/production/report-output")
def production_report_output(
    year: int | None = None,
    period: str = "all",
    sheet: str | None = None,
    user: dict = Depends(get_current_user)
):
    """
    Сколько сделали кирпичей, сколько брака и сколько годных.

    Период считается от последней смены в файле, а не от сегодня:
    отчёт заполняют с задержкой, и «за сегодня» по календарю почти
    всегда вернуло бы ноль там, где завод работал.

    В штуки переводим только то, для чего владелец назвал коэффициент
    (блок 10,7НФ — 0,0208 м³). Опытные форматы в кубометрах идут
    отдельной строкой: выдуманный коэффициент исказил бы весь выпуск.
    """
    from backend.services.production_import_service import production_totals

    return {"success": True, **production_totals(year, period, sheet)}


@router.get("/api/production/report-brigades")
def production_report_brigades(
    year: int | None = None,
    span: str = "month",
    user: dict = Depends(get_current_user)
):
    """
    Сколько сделала каждая бригада за свои смены: месяц, полгода, год.

    Сравнение по общей сумме было бы нечестным — у одной бригады смен
    больше. Главная цифра здесь «штук за смену», и рядом видно, из
    скольких смен она сложилась.
    """
    from backend.services.production_import_service import brigade_output

    return {"success": True, **brigade_output(year, span)}
