from backend.services.machine_service import detect_machine
from backend.services.vector_service import search_documents
from backend.services.filter_service import filter_results
from backend.services.symptom_service import detect_symptom
from backend.services.gpt_symptom_service import analyze as gpt_analyze
from backend.services.case_service import (
    create_case,
    get_active_case
)

from backend.services.equipment_state_service import (
    apply_case_event
)

from backend.services.equipment_service import (
    find_equipment_by_machine
)


def search(question: str, selected_machine=None, equipment_id=None):

    # =========================================
    # 1. ОПРЕДЕЛЯЕМ ОБОРУДОВАНИЕ
    # =========================================

    # Мусорные значения от клиента: если фронтенд не подставил
    # название, приходит строка "undefined" или "unknown", и она
    # уходит в базу как имя станка. Рабочий потом видит в списке
    # обращений «undefined» вместо «Дробилка DTE 117».
    GARBAGE = {"undefined", "null", "unknown", "неизвестно", "none", ""}

    if selected_machine and str(selected_machine).strip().lower() in GARBAGE:
        selected_machine = None

    if selected_machine:

        machine = {
            "machine": selected_machine
        }

    else:

        machine = detect_machine(question)

        # -------------------------------------
        # Keyword-детектор не справился —
        # пробуем GPT (если ключ настроен,
        # иначе gpt_analyze вернёт None и мы
        # просто останемся без результата).
        # -------------------------------------

        if machine is None:

            gpt_result = gpt_analyze(question)

            if gpt_result and gpt_result.get("machine"):

                machine = {
                    "machine": gpt_result["machine"],
                    "gpt_symptom_hint": gpt_result.get("symptom")
                }

        if machine is None:

            return {
                "success": False,
                "message": "Не удалось определить оборудование."
            }

    # =========================================
    # 1.1 ПРИВЯЗЫВАЕМ ОБОРУДОВАНИЕ
    # =========================================
    #
    # Если equipment_id уже передан из /diagnose —
    # ничего не угадываем.
    #
    # Если /chat определил только machine,
    # пробуем найти однозначное оборудование
    # через существующий equipment_service.
    #
    if equipment_id is None:
        equipment = find_equipment_by_machine(
            machine["machine"]
        )

        if equipment:
            equipment_id = equipment["id"]

    # =========================================
    # 2. ОПРЕДЕЛЯЕМ СИМПТОМ
    # =========================================

    symptom = detect_symptom(
        machine["machine"],
        question,
        equipment_id=equipment_id
    )

    # =========================================
    # 3. ФОРМИРУЕМ ПОИСКОВЫЙ ЗАПРОС
    # =========================================

    search_query = question

    if symptom:

        search_query = symptom["search"]

    # =========================================
    # 4. ИЩЕМ ИНФОРМАЦИЮ В ДОКУМЕНТАЦИИ
    # =========================================

    results = search_documents(
        machine=machine["machine"],
        question=search_query,
        limit=5
    )

    # =========================================
    # 5. ФИЛЬТРАЦИЯ
    # =========================================

    results = filter_results(results)

    # =========================================
    # 6. ПРОВЕРЯЕМ АКТИВНОЕ ОБРАЩЕНИЕ
    # =========================================

    # Ищем открытое обращение ИМЕННО ПО ЭТОМУ станку, а не последнее
    # открытое по всему заводу (см. case_service.get_active_case).
    case_id = get_active_case(
        equipment_id=equipment_id,
        machine=machine["machine"]
    )

    new_case = False

    if case_id is None:

        # Название станка берём из справочника оборудования.
        # cases.machine — текстовое поле, и что в него положишь,
        # то рабочий и увидит. Справочник — единственный источник,
        # где имя гарантированно правильное.
        machine_name = machine["machine"]

        if equipment_id:
            try:
                from backend.services.equipment_service import get_equipment
                found = get_equipment(equipment_id)
                if found and found.get("name"):
                    machine_name = found["name"]
            except Exception as error:
                print(f"[search] Не удалось взять имя станка: {error}")

        case_id = create_case(
            machine_name,
            symptom["name"] if symptom else "",
            question,
            equipment_id=equipment_id
        )

        new_case = True

    # =========================================
    # 7. ИЗМЕНЯЕМ СОСТОЯНИЕ ОБОРУДОВАНИЯ
    # =========================================
    #
    # ВАЖНО:
    # Снижение происходит только один раз,
    # когда создаётся новое обращение.
    #
    # Новое предупреждение:
    # Readiness -10
    #
    # Пока мы используем уровень "warning".
    # Позже AI сможет определять:
    # minor / warning / critical.
    # =========================================

    equipment_state = None

    if new_case:

        # Если equipment_id уже точно известен (рабочий выбрал
        # станок из списка в /diagnose) — используем его напрямую,
        # без угадывания по имени. Раньше здесь ВСЕГДА искали
        # станок заново по строке "machine" через
        # find_equipment_by_machine(), даже когда equipment_id уже
        # был на руках — а сопоставление по подстроке ненадёжно
        # (см. баг с кириллицей в LOWER() — equipment_service.py).

        equipment_state = apply_case_event(
            machine=machine["machine"],
            case_id=case_id,
            problem=(
                symptom["name"]
                if symptom
                else question
            ),
            severity="warning",
            equipment_id=equipment_id
        )

    # =========================================
    # 8. ВОЗВРАЩАЕМ РЕЗУЛЬТАТ
    # =========================================

    return {

        "success": True,

        "case_id": case_id,

        "machine": machine,

        "symptom": symptom,

        "results": results,

        "equipment_state": equipment_state

    }

# =========================================================
# CONTINUE DIAGNOSIS (реакция на "Помогло" / "Не помогло")
# =========================================================

from backend.config import MAX_AI_STEPS
from backend.services.case_service import (
    get_case,
    close_case_by_ai,
    escalate_case,
    set_step
)
from backend.services.downtime_service import try_auto_end_downtime_for_case
from backend.services.chat_service import get_history, save_message
from backend.services.response_service import build_answer


def continue_diagnosis(case_id: int, helped: bool):

    case = get_case(case_id)

    if case is None:
        return {
            "success": False,
            "message": "Обращение не найдено."
        }

    # -------------------------------------
    # "Помогло" — закрываем сразу, без людей.
    # -------------------------------------

    if helped:

        history = get_history(case_id)

        last_suggestion = None

        for role, message in reversed(history):
            if role == "assistant":
                last_suggestion = message
                break

        close_case_by_ai(case_id, resolution_comment=last_suggestion)

        # Автозавершение простоя — если ИИ сам решил проблему,
        # простой (если был начат при создании обращения) тоже
        # должен закончиться, а не висеть незавершённым вечно.
        try_auto_end_downtime_for_case(case_id, ended_by="Закрыто ИИ")

        return {
            "success": True,
            "resolved": True,
            "message": "Обращение закрыто."
        }

    # -------------------------------------
    # "Не помогло" — либо следующий шаг, либо эскалация.
    # -------------------------------------

    current_step = case["current_step"] or 0

    if current_step >= MAX_AI_STEPS:

        escalate_case(case_id)

        return {
            "success": True,
            "escalated": True,
            "message": (
                "ACAI исчерпал варианты. "
                "Требуется более опытный специалист."
            )
        }

    results = search_documents(
        machine=case["machine"],
        question=case["worker_question"],
        limit=5
    )

    results = filter_results(results)

    history = get_history(case_id)

    exclude_actions = [
        message
        for role, message in history
        if role == "assistant"
    ]

    answer_data = build_answer(
        case_id,
        case["machine"],
        results,
        question=case["worker_question"],
        exclude_actions=exclude_actions,
        equipment_id=case["equipment_id"]
    )

    if not answer_data["recommendation"]:

        escalate_case(case_id)

        return {
            "success": True,
            "escalated": True,
            "message": (
                "ACAI не нашёл больше вариантов. "
                "Требуется более опытный специалист."
            )
        }

    new_step = current_step + 1

    set_step(case_id, new_step)

    save_message(case_id, "assistant", answer_data["recommendation"])

    return {
        "success": True,
        "resolved": False,
        "escalated": False,
        "recommendation": answer_data["recommendation"],
        "step": new_step,
        "max_steps": MAX_AI_STEPS,
        "actions": answer_data["actions"],
        "explanation": answer_data.get("explanation")
    }
