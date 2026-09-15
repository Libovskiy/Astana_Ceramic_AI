from backend.services.instruction_service import extract_actions
from backend.services.ai_service import suggest_next_action
from backend.services.knowledge_service import get_relevant_resolutions
from backend.services.procedures_service import find_matching_procedure


def build_answer(
    case_id,
    machine,
    results,
    question="",
    exclude_actions=None,
    equipment_id=None
):
    """
    Возвращает ОДНО следующее предлагаемое действие (не финальный ответ) —
    вызывающий код (main.py) сам решает, что делать с обратной связью
    рабочего ("Помогло" / "Не помогло").

    Если вернуть recommendation=None — значит предложить больше нечего,
    вызывающий код должен эскалировать обращение на специалиста.

    Порядок приоритета источников (по решению пользователя):
    1. Реальная инструкция завода (procedures_service) — если для
       этого станка есть написанная человеком процедура, подходящая
       под вопрос, показываем её шаги. Самый надёжный источник —
       написан тем, кто реально знает станок.
    2. Легаси-сценарии instruction_service (сейчас — только "плёнка").
    3. ИИ с контекстом документации + база подтверждённых решений.
    4. (Отдельная будущая задача, не здесь) — поиск в интернете по
       такому же оборудованию, если ничего из 1-3 не подошло.

    Дополнительно возвращает "explanation" — на основании чего дан
    совет и насколько уверенно. НЕ выдумываем проценты (97% и т.п.),
    только честный уровень: Высокая/Средняя/Низкая, и список того,
    что реально было найдено (документация, подтверждённые случаи).
    """

    exclude_actions = exclude_actions or []

    # -------------------------------------
    # 1. Реальная инструкция завода — высший приоритет, если нашлась.
    # -------------------------------------

    matching_procedure = find_matching_procedure(equipment_id, question)

    if matching_procedure:

        procedure_actions = [
            {"text": step["text"]}
            for step in matching_procedure["steps"]
            if step["text"] not in exclude_actions
        ]

        if procedure_actions:

            return {
                "case_id": case_id,
                "machine": machine.capitalize(),
                "recommendation": procedure_actions[0]["text"],
                "actions": procedure_actions,
                "explanation": {
                    "confidence": "Высокая",
                    "basis": [f"Инструкция завода: «{matching_procedure['title']}»"]
                }
            }

    # -------------------------------------
    # 2. Легаси-сценарии из instruction_service (сейчас — только "плёнка").
    #    Работают без OpenAI, приоритет им, раз они уже проверены вручную.
    # -------------------------------------

    actions = extract_actions(
        results,
        question=question,
        exclude_actions=exclude_actions,
        machine=machine
    )

    if actions:

        first = actions[0]

        return {
            "case_id": case_id,
            "machine": machine.capitalize(),
            "recommendation": first["text"],
            "actions": actions,
            "explanation": {
                "confidence": "Высокая",
                "basis": ["Проверенный сценарий из базы инструкций"]
            }
        }

    # -------------------------------------
    # 3. Готовых легаси-действий не осталось (или их не было) —
    #    пробуем ИИ, подкидывая контекст документации + базу знаний.
    # -------------------------------------

    context_chunks = results.get("documents", []) if results else []
    doc_context = "\n\n".join(context_chunks[:3])

    knowledge_hints = get_relevant_resolutions(machine, question)

    suggestion = suggest_next_action(
        machine=machine,
        question=question,
        doc_context=doc_context,
        tried_actions=exclude_actions,
        knowledge_hints=knowledge_hints
    )

    if suggestion:

        basis = []

        if knowledge_hints:
            basis.append(
                f"{len(knowledge_hints)} подтверждённых похожих случаев в базе знаний"
            )

        if context_chunks:
            basis.append(
                f"Найдено в документации станка ({min(len(context_chunks), 3)} фрагм.)"
            )

        if knowledge_hints:
            confidence = "Высокая"
        elif context_chunks:
            confidence = "Средняя"
        else:
            confidence = "Низкая"
            basis.append("Общие знания ИИ — подтверждённых случаев или документации не найдено")

        return {
            "case_id": case_id,
            "machine": machine.capitalize(),
            "recommendation": suggestion,
            "actions": [],
            "explanation": {
                "confidence": confidence,
                "basis": basis
            }
        }

    # -------------------------------------
    # 4. Ни инструкции, ни легаси-сценария, ни ИИ (ключ не настроен /
    #    решил, что предлагать больше нечего) — сигнализируем эскалацию.
    # -------------------------------------

    return {
        "case_id": case_id,
        "machine": machine.capitalize(),
        "recommendation": None,
        "actions": [],
        "explanation": None
    }
