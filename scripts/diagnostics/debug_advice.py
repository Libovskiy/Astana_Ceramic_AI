"""
Разбор по шагам: почему ИИ дал (или не дал) совет.

Показывает всю цепочку построения ответа — что нашлось в
документации, что осталось после фильтра, что вернул GPT. Нужен,
когда рабочий получает "ACAI не нашёл подходящего решения", а
почему — непонятно.

Запуск:
    python debug_advice.py "Упаковочная машина" "подшипник горячий, стук"
    python debug_advice.py "Дробилка DTE 117" "не запускается"
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))


import sys

from backend.config import MAX_AI_STEPS, OPENAI_API_KEY
from backend.services.vector_service import (
    search_documents,
    resolve_docs_folders,
    get_folders,
    is_available
)
from backend.services.filter_service import filter_results
from backend.services.symptom_service import detect_symptom
from backend.services.knowledge_service import get_relevant_resolutions
from backend.services.procedures_service import find_matching_procedure
from backend.services.instruction_service import extract_actions
from backend.services import ai_service


def line(title):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def main():

    if len(sys.argv) < 3:
        print('Запуск: python debug_advice.py "Название станка" "текст рабочего"')
        return

    machine = sys.argv[1]
    question = sys.argv[2]

    print(f"\nСтанок:  {machine}")
    print(f"Вопрос:  {question}")
    print(f"Ключ OpenAI: {'задан' if OPENAI_API_KEY else 'НЕ ЗАДАН'}")

    # -----------------------------------------
    line("1. СИМПТОМ")

    symptom = detect_symptom(machine, question)

    if symptom:
        print(f"  название: {symptom.get('name')}")
        print(f"  запрос по документации: {symptom.get('search')}")
        print(f"  определил: {symptom.get('detected_by')}")
        search_query = symptom.get("search") or question
    else:
        print("  не распознан — искать будем по исходному тексту")
        search_query = question

    # -----------------------------------------
    line("2. ДОКУМЕНТАЦИЯ")

    if not is_available():
        print("  БАЗА ЗНАНИЙ НЕДОСТУПНА — поиск отключён")
        results = {"documents": [[]], "metadatas": [[]]}
    else:
        print(f"  всего папок в базе: {len(get_folders())}")
        print(f"  подходящие станку:  {resolve_docs_folders(machine) or '— общий поиск'}")
        print(f"  поисковый запрос:   {search_query}")

        results = search_documents(machine=machine, question=search_query, limit=5)

    raw_docs = results.get("documents", [[]])[0] if results.get("documents") else []
    raw_meta = results.get("metadatas", [[]])[0] if results.get("metadatas") else []

    print(f"\n  найдено кусков: {len(raw_docs)}")

    for index, (doc, meta) in enumerate(zip(raw_docs, raw_meta), start=1):
        print(f"    {index}. {meta.get('file')} стр. {meta.get('page')} — {len(doc)} симв.")
        print(f"       {doc[:110]}...")

    # -----------------------------------------
    line("3. ФИЛЬТР (filter_service)")

    filtered = filter_results(results)
    kept = filtered.get("documents", [])

    print(f"  было {len(raw_docs)} -> осталось {len(kept)}")

    if raw_docs and not kept:
        print("\n  ВСЁ ОТСЕЯНО. Причины в filter_service.filter_results():")
        print("    - кусок короче 120 символов;")
        print("    - содержит слово из BAD_PHRASES (содержание, index,")
        print("      copyright, версия, руководство пользователя...).")
        print("  ИИ получит ПУСТУЮ документацию и будет отвечать вслепую.")

    for index, doc in enumerate(kept, start=1):
        print(f"    {index}. {len(doc)} симв. — {doc[:90]}...")

    # -----------------------------------------
    line("4. ИНСТРУКЦИЯ ЗАВОДА (высший приоритет)")

    procedure = find_matching_procedure(None, question)
    print(f"  найдено по тексту без станка: {procedure['title'] if procedure else 'нет'}")
    print("  (в боевом коде ищется по equipment_id этого станка)")

    # -----------------------------------------
    line("5. ЛЕГАСИ-СЦЕНАРИЙ (instruction_service)")

    actions = extract_actions(filtered, question=question, machine=machine)
    print(f"  подходящих действий: {len(actions)}")
    for action in actions:
        print(f"    - {action['text']}")

    # -----------------------------------------
    line("6. БАЗА ПОДТВЕРЖДЁННЫХ РЕШЕНИЙ")

    hints = get_relevant_resolutions(machine, question)
    print(f"  похожих случаев: {len(hints)}")
    for hint in hints:
        print(f"    - {hint[:100]}")

    # -----------------------------------------
    line("7. ЗАПРОС К GPT (suggest_next_action)")

    doc_context = "\n\n".join(kept[:3])

    print(f"  длина контекста документации: {len(doc_context)} символов")
    print(f"  подсказок из базы знаний: {len(hints)}")
    print(f"  уже пробовали: (пусто, это первый шаг)")

    if not OPENAI_API_KEY:
        print("\n  Ключ не задан — GPT не вызывается, сразу эскалация.")
        return

    suggestion = ai_service.suggest_next_action(
        machine=machine,
        question=question,
        doc_context=doc_context,
        tried_actions=[],
        knowledge_hints=hints
    )

    print()

    if suggestion:
        print(f"  ОТВЕТ GPT: {suggestion}")
    else:
        print("  GPT вернул None. Это значит ОДНО из двух:")
        print("    а) модель ответила ровно 'ЭСКАЛАЦИЯ' — сочла, что")
        print("       самостоятельные попытки бессмысленны;")
        print("    б) произошла ошибка запроса (её текст напечатан выше")
        print("       строкой [ai_service]).")
        print("\n  В обоих случаях рабочий увидит 'требуется специалист'")
        print("  уже на первом шаге.")

    # -----------------------------------------
    line("ИТОГ")

    if procedure or actions:
        print("  Ответ дала бы инструкция/сценарий — до GPT дело не дошло бы.")
    elif suggestion:
        print(f"  Совет есть. Уверенность: {'Высокая' if hints else 'Средняя' if kept else 'Низкая'}")
        if not kept:
            print("  ВНИМАНИЕ: документации в контексте не было — это общие")
            print("  знания модели о таком оборудовании, не ваш мануал.")
    else:
        print("  Совета нет -> эскалация на специалиста с первого шага.")
        print(f"  (MAX_AI_STEPS={MAX_AI_STEPS}, но до второго шага не доходит)")

    print()


if __name__ == "__main__":
    main()
