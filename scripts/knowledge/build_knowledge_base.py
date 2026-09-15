"""
Сборка базы знаний из PDF в docs/.

ГЛАВНАЯ ПРАВКА: разбиение на куски перенесено ВНУТРЬ цикла по
страницам. В прошлой версии строки

    chunks = split_text(text)
    for chunk in chunks: ...

стояли на уровне самого цикла "for page_number, page in ...",
то есть выполнялись ОДИН раз после его завершения — по тексту
последней непустой страницы. Текущая база на диске собрана более
ранней (корректной) версией скрипта, поэтому она в порядке; но
любой запуск сломанной версии сначала удалял бы коллекцию, а затем
записывал бы в неё по одной странице с документа. Не запускайте
старую версию.

Дополнительно:
- пути берутся из backend/config.py, а не из parents[2];
- добавление в Chroma идёт пачками (заметно быстрее);
- старая коллекция удаляется только ПОСЛЕ успешного разбора PDF,
  чтобы неудачный запуск не оставил вас без базы знаний;
- errors_index.json пишется во временный файл и подменяется в
  конце — прерванный запуск не обнулит индекс ошибок.

Запуск: python -m backend.tools.build_knowledge_base
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))


import re
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


def read_pdf(pdf, error_index):
    """
    Возвращает список (chunk_text, metadata) по ВСЕМ страницам
    документа и попутно наполняет индекс кодов ошибок.
    """

    prepared = []

    doc = fitz.open(pdf)

    try:

        for page_number, page in enumerate(doc, start=1):

            text = page.get_text()

            if not text.strip():
                continue

            text = " ".join(text.split())

            # -----------------------------
            # Коды ошибок на этой странице
            # -----------------------------

            for code in re.findall(r"\b[A-Z]\d{3,4}\b", text):

                if code not in error_index:

                    error_index[code] = {
                        "document": pdf.name,
                        "folder": pdf.parent.name,
                        "page": page_number
                    }

            # -----------------------------
            # Куски ЭТОЙ страницы
            # -----------------------------

            for chunk in split_text(text):

                if not is_useful(chunk):
                    continue

                prepared.append((
                    chunk,
                    {
                        "machine": pdf.parent.name.lower(),
                        "file": pdf.name,
                        "path": str(pdf.relative_to(DOCS_PATH)),
                        "page": page_number
                    }
                ))

    finally:
        doc.close()

    return prepared


def main():

    if not DOCS_PATH.exists():
        print(f"Папка с документацией не найдена: {DOCS_PATH}")
        return

    KNOWLEDGE_BASE_PATH.mkdir(parents=True, exist_ok=True)

    pdf_files = sorted(DOCS_PATH.rglob("*.pdf"))

    print(f"\nНайдено PDF: {len(pdf_files)}\n")

    if not pdf_files:
        print("Нечего индексировать — выхожу, существующая база не тронута.")
        return

    # -----------------------------
    # 1. Читаем ВСЕ документы в память ДО удаления старой коллекции
    # -----------------------------

    error_index = {}
    prepared = []
    failed = []

    for pdf in pdf_files:

        print(f"Обрабатываю: {pdf.name}")

        try:

            chunks = read_pdf(pdf, error_index)

            print(f"   кусков: {len(chunks)}")

            prepared.extend(chunks)

        except Exception as error:

            print(f"   ОШИБКА: {error}")

            failed.append((pdf.name, str(error)))

    if not prepared:
        print("\nНи одного пригодного куска не получено — база НЕ тронута.")
        return

    # -----------------------------
    # 2. Только теперь пересоздаём коллекцию
    # -----------------------------

    client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))

    embedding_function = SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )

    try:
        client.delete_collection(CHROMA_COLLECTION_NAME)
    except Exception:
        pass

    collection = client.create_collection(
        name=CHROMA_COLLECTION_NAME,
        embedding_function=embedding_function
    )

    # -----------------------------
    # 3. Пишем пачками
    # -----------------------------

    for start in range(0, len(prepared), BATCH_SIZE):

        batch = prepared[start:start + BATCH_SIZE]

        collection.add(
            ids=[str(start + offset) for offset in range(len(batch))],
            documents=[chunk for chunk, _ in batch],
            metadatas=[
                {**meta, "chunk": start + offset}
                for offset, (_, meta) in enumerate(batch)
            ]
        )

        print(f"Записано: {min(start + BATCH_SIZE, len(prepared))} / {len(prepared)}")

    # -----------------------------
    # 4. Индекс ошибок — через временный файл
    # -----------------------------

    temp_path = ERROR_INDEX_PATH.with_suffix(".json.tmp")

    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(error_index, f, ensure_ascii=False, indent=4)

    os.replace(temp_path, ERROR_INDEX_PATH)

    # -----------------------------

    print("\n===================================")
    print("БАЗА ЗНАНИЙ СОЗДАНА")
    print("===================================")
    print(f"Документов обработано: {len(pdf_files) - len(failed)} из {len(pdf_files)}")
    print(f"Добавлено кусков: {len(prepared)}")
    print(f"Найдено кодов ошибок: {len(error_index)}")

    if failed:
        print("\nНе удалось обработать:")
        for name, error in failed:
            print(f"  {name}: {error}")

    print("===================================")


if __name__ == "__main__":
    main()
