"""
Отсев мусорных кусков документации ПЕРЕД отправкой в ИИ.

Работает в момент поиска, поэтому правки действуют сразу — база
знаний не перестраивается.

Зачем понадобилось: MESSERSI.pdf наполовину состоит из таблиц
электросхем и перечней клемм. По запросу про перегрев подшипника
семантический поиск честно возвращал куски вида

    "Tot. sheet MH3 Ed 4 Original BERALMAR 151878 - 5247 + Date
     PNT CBT 148 6 14/04/2017 5 = 172659 Job n Motori..."
    "GF Blow Cooling welding EDE067800 EDE031900 EDE067500"

— потому что там есть слова cooling и motori. Для человека и для
ИИ это бесполезный шум: ни причины, ни действия в нём нет. Старый
фильтр их пропускал (в куске находилось слово "motor" из списка
полезных, и good >= bad срабатывал).

Теперь кусок отбраковывается ещё и по СТРУКТУРЕ: если это в
основном коды, артикулы и цифры, а не связный текст — он
отбрасывается независимо от того, какие слова в нём встретились.
"""

import re


BAD_PHRASES = [
    "чистая страница",
    "руководство пользователя",
    "table of contents",
    "оглавление",
    "содержание",
    "copyright",
    "лист регистрации изменений",
    "свидетельство о приемке",
    "гарантийный талон",

    # маркеры таблиц электросхем и спецификаций
    "tot. sheet",
    "job n",
    "plc inputs",
    "plc outputs",
    "page f e d c",
    "ed 1 original",
    "ed 2 original",
    "ed 3 original",
    "ed 4 original",
    "ed 5 original",
]


MIN_LENGTH = 120

# Доля "словесного" текста, ниже которой кусок считается таблицей.
MIN_WORD_RATIO = 0.55

# Максимальная доля кодов и артикулов (EDE067800, X2.J4, 151878).
MAX_CODE_RATIO = 0.30


def _looks_like_table(text: str) -> bool:
    """
    True, если кусок — таблица кодов, а не связный текст.

    Считаем два признака:
      - доля токенов, состоящих только из букв (обычные слова);
      - доля токенов-кодов: цифры, смеси букв с цифрами, обрывки
        обозначений вроде "/116.6:D" или "-X2.J4".
    """

    tokens = text.split()

    if len(tokens) < 12:
        # Слишком короткий, чтобы судить по статистике —
        # решение примет проверка длины.
        return False

    words = 0
    codes = 0

    for token in tokens:

        clean = token.strip(".,;:()[]{}/-–—+=«»\"'")

        if not clean:
            continue

        if clean.isalpha() and len(clean) > 2:
            words += 1
            continue

        has_digit = any(character.isdigit() for character in clean)

        if has_digit or len(clean) <= 2:
            codes += 1

    total = words + codes

    if total == 0:
        return True

    word_ratio = words / total
    code_ratio = codes / total

    return word_ratio < MIN_WORD_RATIO or code_ratio > MAX_CODE_RATIO


def is_readable(text: str) -> bool:
    """Одна проверка одного куска — вынесена, чтобы её можно было
    вызвать из других мест (например, при сборке базы знаний)."""

    if not text or len(text) < MIN_LENGTH:
        return False

    lower = text.lower()

    if any(phrase in lower for phrase in BAD_PHRASES):
        return False

    if _looks_like_table(text):
        return False

    return True


def filter_results(results, limit=5):
    """
    results — сырой ответ ChromaDB.
    limit   — сколько кусков оставить максимум (столько же уйдёт в ИИ).

    Возвращает {"documents": [...], "metadatas": [...]} — плоские
    списки, как ждёт response_service.
    """

    documents = results.get("documents") or [[]]
    metadatas = results.get("metadatas") or [[]]

    docs = documents[0] if documents else []
    meta = metadatas[0] if metadatas else []

    filtered_docs = []
    filtered_meta = []

    for doc, item in zip(docs, meta):

        if not is_readable(doc):
            continue

        filtered_docs.append(doc)
        filtered_meta.append(item)

        if len(filtered_docs) >= limit:
            break

    return {
        "documents": filtered_docs,
        "metadatas": filtered_meta
    }
