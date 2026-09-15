"""
Легаси-сценарии диагностики (до появления раздела "Инструкции").

Правка: сценарий "плёнка" теперь срабатывает ТОЛЬКО для упаковочной
машины (Messersi). Раньше проверялось одно слово "пленка" в тексте,
без всякой привязки к станку — и оператор экструдера, написавший
"плёнка на входе", получал шаги со ссылкой на MESSERSI.pdf стр. 142,
причём с пометкой уверенности "Высокая" (этот источник в
response_service имеет приоритет ВЫШЕ ИИ).

Это временный блок: как только те же три шага будут заведены через
раздел "Инструкции" (procedures_service) для упаковочной машины,
весь этот файл можно удалить, а вызов убрать из response_service.
"""

from backend.config import resolve_machine_key


# Станки, для которых легаси-сценарий вообще допустим.
LEGACY_SCENARIO_MACHINES = ("messersi",)


def extract_actions(results, question="", exclude_actions=None, machine=None):

    if exclude_actions is None:
        exclude_actions = []

    # Привязка к станку — без неё сценарий выдавался кому угодно.
    if resolve_machine_key(machine) not in LEGACY_SCENARIO_MACHINES:
        return []

    # "ё" и "е" — разные символы для Python, но одно и то же слово
    # для человека ("плёнка" / "пленка"). См. тот же фикс
    # в machine_service.py / symptom_service.py.
    question_lower = question.lower().replace("ё", "е")

    if "пленка" in question_lower:

        actions = [
            {
                "text": "Проверить натяжение пленки",
                "file": "MESSERSI.pdf",
                "page": 142
            },
            {
                "text": "Проверить датчик наличия пленки",
                "file": "MESSERSI.pdf",
                "page": 142
            },
            {
                "text": "Проверить направляющие ролики",
                "file": "MESSERSI.pdf",
                "page": 145
            }
        ]

    else:
        actions = []

    # Убираем уже выполненные действия
    filtered = []

    for action in actions:

        already_done = False

        for completed in exclude_actions:

            if action["text"].lower() == completed.lower():
                already_done = True
                break

        if not already_done:
            filtered.append(action)

    return filtered
