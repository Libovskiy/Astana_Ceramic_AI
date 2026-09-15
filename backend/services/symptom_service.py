"""
Определение симптома по тексту рабочего.

КАК ЭТО РАБОТАЕТ

Основной путь — ИИ. Он читает жалобу и называет неисправность.
Ничего вписывать руками не нужно: ни ключевых слов, ни списка
категорий.

Единственное, что мы ему даём, — названия, которые УЖЕ встречались
на заводе (берутся из истории обращений, case_service.
get_known_symptoms). Если поломка такая же, ИИ обязан назвать её
теми же словами. Это нужно не для распознавания, а для счёта:
разделы "Повторяющиеся неисправности" и "Топ неисправностей"
группируют обращения по паре (станок, симптом), и если каждый раз
писать новую формулировку, две одинаковые поломки никогда не
совпадут.

Справочник растёт сам: первое обращение задаёт название, все
последующие похожие к нему прилипают.

Резервный путь — ключевые слова из backend/core/symptoms/*.json.
Включается, только когда ИИ недоступен: нет интернета на заводе
или не задан OPENAI_API_KEY. Дописывать эти файлы не нужно, они
просто страховка на такой случай.
"""

import json

from backend.config import SYMPTOMS_DIR, resolve_machine_key
from backend.services.gpt_symptom_service import classify_symptom
from backend.services.case_service import get_known_symptoms


COMMON_FILE = "common.json"

_cache = {}


def _normalize(text: str) -> str:
    """'ё' и 'е' — разные символы для Python, но одно и то же слово
    для человека ('плёнка' / 'пленка')."""
    return text.lower().replace("ё", "е")


def _load(filename: str):

    if filename in _cache:
        return _cache[filename]

    path = SYMPTOMS_DIR / filename

    if not path.exists():
        _cache[filename] = []
        return []

    try:

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        symptoms = data.get("symptoms", [])

    except (OSError, json.JSONDecodeError) as error:

        print(f"[symptom_service] Не удалось прочитать {path}: {error}")

        symptoms = []

    _cache[filename] = symptoms

    return symptoms


def reload_symptoms():
    """Сбросить кэш резервных справочников."""
    _cache.clear()


def _fallback_symptoms(machine):
    """Резервные справочники: общий + файл станка, если он есть."""

    symptoms = list(_load(COMMON_FILE))

    machine_files = []

    if machine:

        raw = str(machine).strip().lower()

        if raw:
            machine_files.append(f"{raw}.json")

        key = resolve_machine_key(machine)

        if key and f"{key}.json" not in machine_files:
            machine_files.append(f"{key}.json")

    machine_symptoms = []

    for filename in machine_files:
        machine_symptoms.extend(_load(filename))

    return symptoms, machine_symptoms


# =========================================================
# 1. ИИ — основной путь
# =========================================================

def _detect_by_ai(machine, question, equipment_id):

    try:
        known = get_known_symptoms(equipment_id=equipment_id)
    except Exception as error:
        # История недоступна — не повод отказываться от ИИ,
        # просто он назовёт симптом без оглядки на прошлые.
        print(f"[symptom_service] Не удалось прочитать историю симптомов: {error}")
        known = []

    # На старте истории нет вообще. Чтобы самые первые обращения
    # не расползлись по формулировкам, подсказываем ИИ типовые
    # названия из резервного справочника — дальше он опирается уже
    # на реальную историю завода.
    if not known:
        common, machine_specific = _fallback_symptoms(machine)
        known = [
            item["name"]
            for item in (machine_specific + common)
            if item.get("name")
        ]

    result = classify_symptom(
        machine=machine,
        question=question,
        known_names=known
    )

    if not result:
        return None

    return {
        "id": None,
        "name": result["name"],
        "search": result["search"],
        "detected_by": "ai"
    }


# =========================================================
# 2. Ключевые слова — резерв
# =========================================================

def _detect_by_keywords(machine, question):

    common, machine_specific = _fallback_symptoms(machine)

    text = _normalize(question)

    machine_ids = {
        item.get("id")
        for item in machine_specific
        if item.get("id")
    }

    catalog = {}

    for item in common + machine_specific:
        if item.get("id"):
            catalog[item["id"]] = item

    best = None
    best_key = (0, 0, -1)

    for symptom_id, symptom in catalog.items():

        score = 0
        length = 0

        for keyword in symptom.get("keywords", []):

            if _normalize(keyword) in text:
                score += 1
                length += len(keyword)

        if score == 0:
            continue

        # Больше совпадений -> более конкретное совпадение
        # (длиннее) -> справочник станка важнее общего.
        key = (score, length, 1 if symptom_id in machine_ids else 0)

        if key > best_key:
            best = symptom
            best_key = key

    if best is None:
        return None

    result = dict(best)
    result["detected_by"] = "keywords"

    return result


# =========================================================
# ТОЧКА ВХОДА
# =========================================================

def detect_symptom(machine: str, question: str, equipment_id=None):

    if not question or not question.strip():
        return None

    symptom = _detect_by_ai(machine, question, equipment_id)

    if symptom:
        return symptom

    return _detect_by_keywords(machine, question)
