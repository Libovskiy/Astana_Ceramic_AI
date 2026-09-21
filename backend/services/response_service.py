from backend.services.instruction_service import extract_actions
from backend.services.ai_service import suggest_next_action
from backend.services.knowledge_service import get_relevant_resolutions
from backend.services.procedures_service import find_matching_procedure
from backend.services.plc_error_service import find_by_code, split_solution_steps
from backend.services.vector_service import own_machine_documents


def honest_unknown(machine_title, has_documentation):
    """
    Что сказать рабочему, когда опереться не на что.

    Лучше сразу «не знаю, зову мастера», чем общий совет, который звучит
    уверенно, а к этому станку отношения не имеет: одна такая фраза
    бережёт доверие сильнее десяти правдоподобных ответов.
    """
    name = f"«{machine_title}»" if machine_title else "этому станку"
    if not has_documentation:
        return (f"По станку {name} у меня нет руководства и подтверждённых решений, "
                f"поэтому гадать не буду.")
    return (f"В руководстве по станку {name} не нашёл ничего про эту неисправность, "
            f"поэтому гадать не буду.")


def machine_title(machine, equipment_id=None):
    if equipment_id:
        try:
            from backend.services.equipment_service import get_equipment
            equipment = get_equipment(equipment_id)
            if equipment and equipment.get("name"):
                return equipment["name"]
        except Exception:
            pass
    return (machine or "").strip()



def _journal_hints(equipment_id, machine, question):
    """
    Записи журнала ремонтов по участку этого станка.

    По 26 станкам из 49 своего руководства нет, и раньше ИИ по ним
    сразу звал специалиста. В сменном отчёте лежит 361 запись живого
    опыта — «Замена скребков УСМ-40», «Ремонт червячного вала
    Мессерси». Источник слабее подтверждённого решения, поэтому идёт
    отдельно и помечается честно.
    """
    try:
        from backend.services.equipment_service import get_equipment
        from backend.services.production_import_service import repairs_for_machine

        location = None
        if equipment_id:
            equipment = get_equipment(equipment_id) or {}
            location = equipment.get("location") or equipment.get("stage")

        if not location:
            return []

        found = repairs_for_machine(machine, location, question)
        return [
            f"{(row.get('date') or '')[:10]}, {row.get('section_title') or ''}: {row.get('text')}"
            for row in found
        ]
    except Exception as error:
        print(f"[journal] подсказки из отчёта не собраны: {error}")
        return []


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
    0. Код ошибки PLC (plc_error_service) — если в тексте жалобы есть
       код вида A45/E45/F0.03 и в базе для него уже вписано решение,
       отдаём его без обращения к ИИ вообще: это самый точный источник
       из всех (человек считал код прямо с панели) и самый дешёвый —
       не тратим токены на то, что и так известно однозначно.
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
    # 0. Код ошибки PLC — точнее источника не бывает, если решение
    #    для этого кода уже кто-то вписал в базу.
    # -------------------------------------

    plc_matches = [m for m in find_by_code(question) if (m.get("solution") or "").strip()]

    if plc_matches:

        match = plc_matches[0]

        # По одному шагу: следующий рабочий получит, нажав «Не помогло»
        # (conversation_service.generate_reply продолжит с шага 2).
        steps = split_solution_steps(match["solution"])

        return {
            "case_id": case_id,
            "machine": machine.capitalize(),
            "recommendation": steps[0],
            "actions": [{"text": step} for step in steps],
            "explanation": {
                "confidence": "Высокая",
                "basis": [f"Код ошибки PLC {match['code']}: {match['title']} (линия «{match['line']}»)"]
            }
        }

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

    title = machine_title(machine, equipment_id)

    # Только руководство ЭТОГО станка: без своей папки поиск отдаёт чужие
    context_chunks, _, has_documentation = own_machine_documents(title or machine, results)
    doc_context = "\n\n".join(context_chunks[:3])

    knowledge_hints = get_relevant_resolutions(machine, question)
    journal_hints = _journal_hints(equipment_id, machine, question)

    # Опереться не на что — честно говорим и зовём специалиста, а не
    # выдаём общие советы с видом знатока. Журнал ремонтов участка тоже
    # опора: слабая, но своя, с этого завода.
    if not context_chunks and not knowledge_hints and not journal_hints:
        return {
            "case_id": case_id,
            "machine": machine.capitalize(),
            "recommendation": None,
            "actions": [],
            "explanation": None,
            "unknown": honest_unknown(title, has_documentation),
        }

    suggestion = suggest_next_action(
        machine=machine,
        question=question,
        doc_context=doc_context,
        tried_actions=exclude_actions,
        knowledge_hints=knowledge_hints,
        journal_hints=journal_hints
    )

    if suggestion:

        from backend.services.conversation_service import _confidence, _case_word

        confidence, source = _confidence(knowledge_hints, context_chunks, suggestion,
                                         journal_hints=journal_hints)

        basis = [f"Совет {source}"]

        if journal_hints and not context_chunks:
            basis.append(f"журнал ремонтов участка ({len(journal_hints)})")

        if knowledge_hints:
            basis.append(_case_word(len(knowledge_hints)) + " на этом станке в базе знаний")

        if context_chunks:
            basis.append(
                f"Руководство по этому станку ({min(len(context_chunks), 3)} фрагм.)"
            )

        if confidence == "Низкая" and not journal_hints:
            basis.append("Подтверждённых случаев и документации по станку не нашлось")

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
