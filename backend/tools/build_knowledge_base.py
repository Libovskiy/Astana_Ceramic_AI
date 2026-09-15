"""
Сборка базы знаний из PDF в docs/.

ГЛАВНОЕ ОТЛИЧИЕ ОТ ПРЕЖНЕЙ ВЕРСИИ: по умолчанию скрипт ДОБАВЛЯЕТ
документы к существующей базе, а не пересоздаёт её.

Прежняя версия первым делом делала delete_collection(), и любой
запуск был односторонней операцией: если новые PDF оказывались
сканами, вы меняли рабочую базу на пустую и узнавали об этом
постфактум. Именно так 850 кусков превратились в 73.

Теперь:
  python -m backend.tools.build_knowledge_base
      добавит только те документы, которых в базе ещё нет.
      Уже проиндексированные пропускаются — запускать можно
      сколько угодно раз, дубликатов не будет.

  python -m backend.tools.build_knowledge_base --rebuild
      полная пересборка с нуля. Спросит подтверждение и покажет,
      сколько кусков вы теряете.

  python -m backend.tools.build_knowledge_base --only "МЕССЕРСИ"
      только документы, в пути которых есть эта подстрока.

  python -m backend.tools.build_knowledge_base --dry-run
      ничего не пишет, только показывает, что будет добавлено.

Второе отличие: разбиение на куски идёт ВНУТРИ цикла по страницам.
В сломанной версии эти строки стояли уровнем выше и обрабатывали
только последнюю страницу документа.
"""

import re
import sys
import json
import os

import fitz

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

from backend.tools.text_chunker import split_text
from backend.tools.document_filter import is_useful

from backend.config import (
    DOCS_PATH,
    KNOWLEDGE_BASE_PATH,
    CHROMA_DB_PATH,
    CHROMA_COLLECTION_NAME,
    ERROR_INDEX_PATH
)


BATCH_SIZE = 200


def get_client_and_embedding():

    client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))

    embedding_function = SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )

    return client, embedding_function


def indexed_paths(collection):
    """Какие документы уже в базе — по метаданному 'path'."""

    paths = set()

    try:
        data = collection.get(include=["metadatas"])
    except Exception as error:
        print(f"Не удалось прочитать состав базы: {error}")
        return paths

    for meta in data.get("metadatas") or []:
        if meta and meta.get("path"):
            paths.add(meta["path"])

    return paths


def read_pdf(pdf, error_index):
    """Куски по ВСЕМ страницам документа + коды ошибок."""

    prepared = []
    pages_with_text = 0

    doc = fitz.open(pdf)

    try:

        for page_number, page in enumerate(doc, start=1):

            text = page.get_text()

            if not text.strip():
                continue

            pages_with_text += 1

            text = " ".join(text.split())

            for code in re.findall(r"\b[A-Z]\d{3,4}\b", text):

                if code not in error_index:
                    error_index[code] = {
                        "document": pdf.name,
                        "folder": pdf.parent.name,
                        "page": page_number
                    }

            relative = str(pdf.relative_to(DOCS_PATH))

            for index, chunk in enumerate(split_text(text)):

                if not is_useful(chunk):
                    continue

                prepared.append((
                    # Идентификатор стабилен: повторная индексация
                    # того же куска перезапишет его, а не создаст дубль.
                    f"{relative}#{page_number}#{index}",
                    chunk,
                    {
                        "machine": pdf.parent.name.lower(),
                        "file": pdf.name,
                        "path": relative,
                        "page": page_number
                    }
                ))

    finally:
        doc.close()

    return prepared, pages_with_text


def load_error_index():

    if not ERROR_INDEX_PATH.exists():
        return {}

    try:
        with open(ERROR_INDEX_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_error_index(error_index):

    temp_path = ERROR_INDEX_PATH.with_suffix(".json.tmp")

    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(error_index, f, ensure_ascii=False, indent=4)

    os.replace(temp_path, ERROR_INDEX_PATH)


def main():

    rebuild = "--rebuild" in sys.argv
    dry_run = "--dry-run" in sys.argv

    only = None

    if "--only" in sys.argv:
        position = sys.argv.index("--only")
        if position + 1 < len(sys.argv):
            only = sys.argv[position + 1].lower()

    if not DOCS_PATH.exists():
        print(f"Папка с документацией не найдена: {DOCS_PATH}")
        return

    KNOWLEDGE_BASE_PATH.mkdir(parents=True, exist_ok=True)

    client, embedding_function = get_client_and_embedding()

    # -----------------------------
    # Текущее состояние базы
    # -----------------------------

    try:
        collection = client.get_collection(
            name=CHROMA_COLLECTION_NAME,
            embedding_function=embedding_function
        )
        existing_count = collection.count()
    except Exception:
        collection = None
        existing_count = 0

    print(f"\nПапка документации: {DOCS_PATH}")
    print(f"База знаний:        {CHROMA_DB_PATH}")
    print(f"Сейчас в базе:      {existing_count} кусков\n")

    # -----------------------------
    # Режим полной пересборки
    # -----------------------------

    if rebuild and existing_count and not dry_run:

        print(f"ВНИМАНИЕ: --rebuild удалит все {existing_count} кусков и соберёт заново.")
        print("Документы, которых сейчас нет в docs/, в базу уже не вернутся.")

        answer = input("Введите ПЕРЕСОБРАТЬ для подтверждения: ").strip()

        if answer != "ПЕРЕСОБРАТЬ":
            print("Отменено. База не тронута.")
            return

        client.delete_collection(CHROMA_COLLECTION_NAME)
        collection = None
        existing_count = 0

    already = set() if rebuild else (indexed_paths(collection) if collection else set())

    if already:
        print(f"Уже проиндексировано документов: {len(already)}\n")

    # -----------------------------
    # Что обрабатывать
    # -----------------------------

    pdf_files = sorted(DOCS_PATH.rglob("*.pdf"))

    if only:
        pdf_files = [p for p in pdf_files if only in str(p).lower()]
        print(f"Фильтр --only '{only}': подходит документов {len(pdf_files)}\n")

    if not pdf_files:
        print("Нечего индексировать. База не тронута.")
        return

    error_index = load_error_index()

    prepared = []
    scans = []
    skipped = []
    failed = []

    for pdf in pdf_files:

        relative = str(pdf.relative_to(DOCS_PATH))

        if relative in already:
            skipped.append(relative)
            continue

        try:

            chunks, pages_with_text = read_pdf(pdf, error_index)

            if pages_with_text == 0:
                scans.append(relative)
                print(f"  СКАН (нет текста): {pdf.name}")
                continue

            if not chunks:
                print(f"  пусто после фильтра: {pdf.name}")
                continue

            print(f"  +{len(chunks):>4} кусков: {pdf.name}")

            prepared.extend(chunks)

        except Exception as error:
            failed.append((pdf.name, str(error)))
            print(f"  ОШИБКА: {pdf.name}: {error}")

    # -----------------------------
    # Итог до записи
    # -----------------------------

    print("\n" + "=" * 60)
    print(f"  Пропущено (уже в базе): {len(skipped)}")
    print(f"  Сканов без текста:      {len(scans)}")
    print(f"  Не прочиталось:         {len(failed)}")
    print(f"  Готово к добавлению:    {len(prepared)} кусков")
    print("=" * 60)

    if dry_run:
        print("\n--dry-run: ничего не записано.")
        return

    if not prepared:
        print(f"\nДобавлять нечего. В базе остаётся {existing_count} кусков.")
        return

    # -----------------------------
    # Запись
    # -----------------------------

    if collection is None:
        collection = client.get_or_create_collection(
            name=CHROMA_COLLECTION_NAME,
            embedding_function=embedding_function
        )

    for start in range(0, len(prepared), BATCH_SIZE):

        batch = prepared[start:start + BATCH_SIZE]

        collection.upsert(
            ids=[item[0] for item in batch],
            documents=[item[1] for item in batch],
            metadatas=[item[2] for item in batch]
        )

        print(f"Записано: {min(start + BATCH_SIZE, len(prepared))} / {len(prepared)}")

    save_error_index(error_index)

    print("\n" + "=" * 60)
    print(f"  Было:  {existing_count} кусков")
    print(f"  Стало: {collection.count()} кусков")
    print(f"  Кодов ошибок в индексе: {len(error_index)}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()