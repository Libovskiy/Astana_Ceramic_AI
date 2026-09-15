#!/usr/bin/env python3
"""
Комбинированный поиск: по смыслу и по точным словам одновременно.

Проблема, которую чиним. Многоязычная модель хорошо ищет по смыслу:
«перегрев» находит раздел про охлаждение, «посторонний шум» — раздел
про допустимый уровень шума. Но на точных формулировках она проваливает:
запрос «номинальное напряжение главных цепей» не находит кусок, где эта
фраза написана дословно, — для смыслового поиска буквальное совпадение
слабый сигнал.

А на заводе половина запросов именно буквальная: человек вводит то, что
написано на шильдике, в паспорте или на щите.

Решение — искать двумя способами и объединять. Смысловой поиск даёт
тематически близкое, словесный ищет куски, где встречаются те же слова.
Кусок, найденный обоими способами, поднимается наверх.

Словесный поиск делаем средствами самой базы (подстрока в тексте) —
без новых зависимостей и второго индекса.

    cd /Users/champ_01/Documents/FactoryAssistant
    python3 fix_hybrid_search.py

Идемпотентен, делает копию файла.
"""
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
VECTOR = BASE_DIR / "backend" / "services" / "vector_service.py"

OLD = '''def search_documents(machine: str, question: str, limit: int = 5):

    collection = get_collection()

    if collection is None:
        return _empty_result()

    limit = limit * OVERFETCH

    folders = resolve_docs_folders(machine)

    if folders:

        try:

            where = (
                {"machine": folders[0]}
                if len(folders) == 1
                else {"machine": {"$in": folders}}
            )

            results = collection.query(
                query_texts=[question],
                n_results=limit,
                where=where
            )

            if results.get("documents") and results[\"documents\"][0]:
                return results

        except Exception as error:
            print(f"[vector_service] Ошибка поиска по папкам {folders}: {error}")

    try:
        return collection.query(query_texts=[question], n_results=limit)

    except Exception as error:
        print(f"[vector_service] Ошибка поиска: {error}")
        return _empty_result()'''

NEW = '''# Слова короче этого не несут смысла для поиска по подстроке:
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
        return _empty_result()'''


def main():
    if not VECTOR.exists():
        print("✗ backend/services/vector_service.py не найден")
        sys.exit(1)

    text = VECTOR.read_text(encoding="utf-8")

    if "_keyword_hits" in text:
        print("✓ уже применено")
    else:
        if OLD not in text:
            print("✗ не нашёл функцию search_documents в ожидаемом виде.")
            print("  Возможно, файл уже правился — проверьте вручную.")
            sys.exit(1)

        shutil.copy2(VECTOR, VECTOR.with_suffix(".py.bak-hybrid"))
        VECTOR.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
        print("✓ поиск теперь комбинированный")
        print("  копия: backend/services/vector_service.py.bak-hybrid")

    import py_compile
    try:
        py_compile.compile(str(VECTOR), doraise=True)
        print("✓ модуль компилируется")
    except Exception as error:
        print(f"✗ синтаксическая ошибка: {error}")
        sys.exit(1)

    print("\nДальше: очистить __pycache__ и перезапустить сервер.")
    print('Проверка: python3 compare_search.py "номинальное напряжение главных цепей"')


if __name__ == "__main__":
    main()
