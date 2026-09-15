"""
Поиск по документации (ChromaDB).

СОПОСТАВЛЕНИЕ СТАНОК <-> ПАПКА ДОКУМЕНТАЦИИ СЧИТАЕТСЯ АВТОМАТИЧЕСКИ.

В метаданных Chroma поле "machine" — имя папки, в которой лежал PDF.
После переезда библиотеки папки называются почти как станки:
"смеситель лопастной смк 126", "1.дробилка dte 117",
"вентилятор нагнетания qb-44". Поэтому руками ничего вписывать не
нужно: список папок читается из самой базы, а станок сопоставляется
с ними по словам названия.

Порядок сопоставления:
  1. точное совпадение после нормализации;
  2. одна строка целиком входит в другую;
  3. совпадение по значимым словам (модель, номер, тип) —
     "Вальцы супертонкого помола OPTIMA 800" находит папку
     "7.вальцы  оптима 800 н";
  4. ручная карта из config.MACHINE_DOCS_MAP — только для случаев,
     где по словам не угадать (например "Упаковочная машина" и
     папка "messersi").

Если ничего не нашлось, поиск идёт по ВСЕЙ документации: лучше
показать кусок из соседнего руководства с указанием файла и
страницы, чем не показать ничего.

Коллекция открывается лениво: при недоступной базе поиск возвращает
пусто, а не роняет импортом весь сервер.
"""

import re
import unicodedata

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

from backend.config import (
    EMBED_MODEL_NAME,
    CHROMA_DB_PATH,
    CHROMA_COLLECTION_NAME,
    MACHINE_DOCS_MAP
)


_collection = None
_init_failed = False
_folders = None

# Слова, которые есть почти у всех и ничего не различают
STOP_WORDS = {
    "оборудование", "оборудовании", "система", "системы", "机",
    "шт", "рэ", "паспорт", "инструкция", "руководство", "цех",
    "линию", "линия", "для", "на", "и", "с", "по", "зона", "зоны",
    "прочие", "общие", "нового", "тип",
}


def _empty_result():
    return {"documents": [[]], "metadatas": [[]], "distances": [[]]}


def get_collection():

    global _collection, _init_failed

    if _collection is not None:
        return _collection

    if _init_failed:
        return None

    try:

        client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))

        embedding = SentenceTransformerEmbeddingFunction(
            model_name=EMBED_MODEL_NAME
        )

        _collection = client.get_collection(
            name=CHROMA_COLLECTION_NAME,
            embedding_function=embedding
        )

        return _collection

    except Exception as error:

        _init_failed = True

        print(
            f"[vector_service] База знаний недоступна ({CHROMA_DB_PATH}): {error}\n"
            f"[vector_service] Поиск по документации отключён — "
            f"система работает на инструкциях завода и ИИ."
        )

        return None


def is_available() -> bool:
    return get_collection() is not None


# =========================================================
# НОРМАЛИЗАЦИЯ И РАЗБОР НА СЛОВА
# =========================================================

def _normalize(value: str) -> str:

    # NFC обязателен: macOS хранит имена файлов и папок в форме NFD,
    # где "ё" — это "е" плюс отдельный знак умлаута. Такая строка
    # выглядит идентично записанной в коде, но не равна ей, и папка
    # "оборудование promatic для обжига углём" молча переставала
    # находиться.
    text = unicodedata.normalize("NFC", str(value or ""))

    text = text.lower().replace("ё", "е")

    # "1.дробилка" -> "1 дробилка", "gerim 200:2:14" -> "gerim 200 2 14"
    text = re.sub(r"[^0-9a-zа-я]+", " ", text)

    # "pl601" -> "pl 601", "qb44" -> "qb 44": в названиях станков
    # модель пишут через пробел или дефис, а в именах папок слитно.
    text = re.sub(r"(?<=[a-zа-я])(?=\d)", " ", text)
    text = re.sub(r"(?<=\d)(?=[a-zа-я])", " ", text)

    return " ".join(text.split())


def _tokens(value: str) -> set:

    words = _normalize(value).split()

    result = set()

    for word in words:

        if word in STOP_WORDS:
            continue

        # Одиночные цифры вроде порядкового номера папки ("1.", "13.")
        # различающей силы не имеют, а вот "800" или "126" — имеют.
        if word.isdigit() and len(word) < 2:
            continue

        if len(word) < 3 and not word.isdigit():
            continue

        result.add(word)

    return result


def get_folders():
    """Список папок документации, реально присутствующих в базе."""

    global _folders

    if _folders is not None:
        return _folders

    collection = get_collection()

    if collection is None:
        return []

    try:

        data = collection.get(include=["metadatas"])

        found = set()

        for meta in data.get("metadatas") or []:
            if meta and meta.get("machine"):
                found.add(meta["machine"])

        _folders = sorted(found)

    except Exception as error:

        print(f"[vector_service] Не удалось прочитать список папок: {error}")

        _folders = []

    return _folders


def reload_folders():
    """Сбросить кэш после пересборки базы знаний."""
    global _folders
    _folders = None


# =========================================================
# СТАНОК -> ПАПКИ
# =========================================================

def resolve_docs_folders(machine) -> list:

    if not machine:
        return []

    folders = get_folders()

    if not folders:
        return []

    target = _normalize(machine)
    target_tokens = _tokens(machine)

    exact = []
    contains = []
    scored = []

    for folder in folders:

        folder_norm = _normalize(folder)

        if not folder_norm:
            continue

        if folder_norm == target:
            exact.append(folder)
            continue

        if target and (target in folder_norm or folder_norm in target):
            contains.append(folder)
            continue

        common = target_tokens & _tokens(folder)

        if not common:
            continue

        # Одного общего слова мало: "вентилятор" встречается у семи
        # папок сразу. Принимаем совпадение, если:
        #   - совпали минимум два слова, одно из которых буквенное
        #     ("вальцы" + "оптима"), либо
        #   - совпал номер модели длиной от трёх знаков ("575", "117",
        #     "126") — он различает надёжно даже сам по себе.
        #
        # Голые двузначные числа отбрасываем: иначе "Вальцы УСМ 40"
        # цепляются к "вентилятор qb-40", а "Регистры сушилки (13 шт)"
        # к папке "13.дизель генератор" — совпало число, а не станок.
        has_letters = any(not word.isdigit() for word in common)

        has_model_number = any(
            word.isdigit() and len(word) >= 3
            for word in common
        )

        if (len(common) >= 2 and has_letters) or has_model_number:
            scored.append((len(common), folder))

    if exact:
        result = exact
    elif contains:
        result = contains
    else:
        scored.sort(reverse=True)
        result = [folder for _, folder in scored[:3]]

    # -----------------------------------------
    # Ручная карта — для случаев, где по словам не угадать
    # -----------------------------------------

    # Сверяем по нормализованному виду, а не по сырой строке —
    # см. комментарий про NFD в _normalize().
    by_normalized = {_normalize(folder): folder for folder in folders}

    for keyword, mapped in MACHINE_DOCS_MAP.items():

        if keyword not in target:
            continue

        for name in (mapped if isinstance(mapped, (list, tuple)) else [mapped]):

            folder = by_normalized.get(_normalize(name))

            if folder and folder not in result:
                result.append(folder)

    return result


# Из базы берём с запасом: filter_service выбрасывает таблицы
# электросхем и перечни клемм, а их в импортных мануалах половина.
# Без запаса после фильтра не оставалось ничего, и ИИ отвечал
# вслепую.
OVERFETCH = 4


# Слова короче этого не несут смысла для поиска по подстроке:
# «на», «до», «в» встречаются везде и только замусоривают выдачу.
MIN_TERM_LENGTH = 5

# Сколько слов запроса проверяем словесным поиском. Больше — дольше,
# а пользы мало: длинные запросы на заводе редкость.
MAX_TERMS = 4


def _significant_terms(question: str) -> list:
    """
    Слова запроса, по которым имеет смысл искать буквально.
    Отбрасываем короткие и служебные, самые длинные — вперёд:
    «напряжение» различает лучше, чем «цепей».
    """
    words = re.findall(r"[A-Za-zА-Яа-яЁё0-9-]{%d,}" % MIN_TERM_LENGTH, question)

    seen = []
    for word in words:
        normalized = _normalize(word)
        if not normalized or normalized in STOP_WORDS:
            continue
        if normalized not in seen:
            seen.append(normalized)

    seen.sort(key=len, reverse=True)

    # Отрезаем окончание: «дробилки» и «ДРОБИЛКА» — одно слово, а поиск
    # по подстроке об этом не знает. Основа «дробилк» найдёт оба падежа.
    stems = []
    for word in seen[:MAX_TERMS]:
        stems.append(word[:-2] if len(word) > 7 else word)

    return stems


def _keyword_hits(collection, question: str, where, limit: int) -> dict:
    """
    Куски, в которых встречаются слова запроса буквально.
    Возвращает {id: сколько слов совпало}.
    """
    hits = {}

    for term in _significant_terms(question):

        # Поиск по подстроке различает регистр, а в паспортах пишут
        # и «Напряжение», и «НАПРЯЖЕНИЕ», и строчными. Пробуем варианты.
        matched = set()

        for variant in (term, term.capitalize(), term.upper()):
            try:
                found = collection.get(
                    where=where,
                    where_document={"$contains": variant},
                    limit=limit,
                    include=[],
                )
            except Exception:
                continue

            matched.update(found.get("ids") or [])

        for chunk_id in matched:
            hits[chunk_id] = hits.get(chunk_id, 0) + 1

    return hits


def _merge(semantic: dict, keyword_ids: dict, collection, limit: int) -> dict:
    """
    Сводит две выдачи в одну. Куски, найденные и по смыслу, и по словам,
    идут первыми: совпадение с двух сторон — самый надёжный признак.
    """
    if not keyword_ids:
        return semantic

    ids = (semantic.get("ids") or [[]])[0]
    docs = (semantic.get("documents") or [[]])[0]
    metas = (semantic.get("metadatas") or [[]])[0]

    combined = []
    seen = set()

    # 1. Найденные обоими способами
    for i, chunk_id in enumerate(ids):
        if chunk_id in keyword_ids:
            combined.append((chunk_id, docs[i], metas[i], 2 + keyword_ids[chunk_id]))
            seen.add(chunk_id)

    # 2. Чисто словесные попадания — их в смысловой выдаче нет,
    #    а именно они спасают точные формулировки вроде названия узла.
    missing = [cid for cid in keyword_ids if cid not in seen]
    if missing:
        try:
            extra = collection.get(ids=missing[:limit], include=["documents", "metadatas"])
            for i, chunk_id in enumerate(extra.get("ids") or []):
                combined.append((
                    chunk_id,
                    (extra.get("documents") or [])[i],
                    (extra.get("metadatas") or [])[i],
                    1 + keyword_ids.get(chunk_id, 0),
                ))
                seen.add(chunk_id)
        except Exception:
            pass

    # 3. Остальное из смысловой выдачи, в прежнем порядке
    for i, chunk_id in enumerate(ids):
        if chunk_id not in seen:
            combined.append((chunk_id, docs[i], metas[i], 0))

    combined.sort(key=lambda row: -row[3])
    combined = combined[:limit]

    return {
        "ids": [[row[0] for row in combined]],
        "documents": [[row[1] for row in combined]],
        "metadatas": [[row[2] for row in combined]],
    }


def search_documents(machine: str, question: str, limit: int = 5):
    """
    Ищет по смыслу и по точным словам, объединяя результаты.

    Одного смыслового поиска мало: он хорошо понимает «перегрев», но
    теряет «номинальное напряжение главных цепей» — дословную фразу из
    паспорта. Одного словесного тоже мало: он не свяжет «стучит» и
    «посторонний шум». Вместе они закрывают оба случая.
    """
    collection = get_collection()

    if collection is None:
        return _empty_result()

    limit = limit * OVERFETCH

    folders = resolve_docs_folders(machine)

    where = None
    if folders:
        where = (
            {"machine": folders[0]}
            if len(folders) == 1
            else {"machine": {"$in": folders}}
        )

    if where is not None:
        try:
            semantic = collection.query(
                query_texts=[question], n_results=limit, where=where
            )

            if semantic.get("documents") and semantic["documents"][0]:
                keyword_ids = _keyword_hits(collection, question, where, limit)
                return _merge(semantic, keyword_ids, collection, limit)

        except Exception as error:
            print(f"[vector_service] Ошибка поиска по папкам {folders}: {error}")

    # По всей документации: либо станок не сопоставлен с папкой,
    # либо в его папке ничего не нашлось.
    try:
        semantic = collection.query(query_texts=[question], n_results=limit)
        keyword_ids = _keyword_hits(collection, question, None, limit)
        return _merge(semantic, keyword_ids, collection, limit)

    except Exception as error:
        print(f"[vector_service] Ошибка поиска: {error}")
        return _empty_result()
