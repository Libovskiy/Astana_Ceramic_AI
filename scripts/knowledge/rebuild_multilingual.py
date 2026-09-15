#!/usr/bin/env python3
"""
Пересборка базы знаний многоязычной моделью — в ОТДЕЛЬНУЮ коллекцию.

Зачем. Сейчас поиск по документации работает на all-MiniLM-L6-v2. Модель
обучена на английском, а 172 документа — русские паспорта и руководства.
Она ищет по смыслу, но смысла русского текста почти не улавливает:
«залипание влажным сырьём» и «налипание массы на вал» для неё далёкие
фразы. Отсюда нерелевантная выдача и честное «не нашёл решения».

Рабочая коллекция НЕ трогается. Новая собирается рядом, под своим именем,
чтобы можно было сравнить выдачу и переключиться (или откатиться) одной
строкой в .env.

    cd /Users/champ_01/Documents/FactoryAssistant
    source venv/bin/activate
    python3 rebuild_multilingual.py              # собрать
    python3 rebuild_multilingual.py --dry-run    # только посчитать

Модель качается один раз, около 500 МБ. Сборка 4000+ кусков на маке —
несколько минут.
"""
import argparse
import json
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

DOCS_PATH = BASE_DIR / "docs"
CHROMA_DB_PATH = BASE_DIR / "knowledge_base" / "chroma_db"
ERROR_INDEX_PATH = BASE_DIR / "knowledge_base" / "errors_index.json"

# Многоязычная модель того же размера вектора, что и прежняя.
# paraphrase-multilingual-MiniLM-L12-v2 понимает русский и не требует
# служебных префиксов в запросе, в отличие от моделей семейства e5.
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
NEW_COLLECTION = "factory_manuals_ml"
BATCH_SIZE = 200

# Оглавления и колонтитулы: строки из точек, «СТР. 17», голые номера.
# В прежней сборке они попали в индекс и лезут в выдачу вместо
# содержательных страниц — они похожи сразу на всё.
JUNK_PATTERNS = [
    re.compile(r"\.{6,}"),
    re.compile(r"^[\s\d.,:;|-]+$"),
]


def looks_like_toc(chunk: str) -> bool:
    if any(p.search(chunk) for p in JUNK_PATTERNS):
        return True
    letters = sum(c.isalpha() for c in chunk)
    return letters < len(chunk) * 0.4


def read_pdf(pdf, split_text, is_useful, error_index):
    """Куски по всем страницам + попутно коды ошибок."""
    import fitz

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
                error_index.setdefault(code, {
                    "document": pdf.name,
                    "folder": pdf.parent.name,
                    "page": page_number,
                })

            relative = str(pdf.relative_to(DOCS_PATH))

            for index, chunk in enumerate(split_text(text)):
                if not is_useful(chunk) or looks_like_toc(chunk):
                    continue
                prepared.append((
                    f"{relative}#{page_number}#{index}",
                    chunk,
                    {
                        # Разметку сохраняем прежнюю: vector_service
                        # фильтрует поиск по полю machine.
                        "machine": pdf.parent.name.lower(),
                        "file": pdf.name,
                        "path": relative,
                        "page": page_number,
                    },
                ))
    finally:
        doc.close()

    return prepared, pages_with_text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="посчитать, но не записывать")
    ap.add_argument("--only", help="только документы, чей путь содержит подстроку")
    args = ap.parse_args()

    if not DOCS_PATH.exists():
        print(f"✗ {DOCS_PATH} не найдена — запускай из корня проекта")
        sys.exit(1)

    from backend.tools.text_chunker import split_text
    from backend.tools.document_filter import is_useful

    import chromadb
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

    pdf_files = sorted(DOCS_PATH.rglob("*.pdf"))
    if args.only:
        pdf_files = [p for p in pdf_files if args.only.lower() in str(p).lower()]

    print(f"Документов найдено: {len(pdf_files)}")
    print(f"Модель:             {MODEL_NAME}")
    print(f"Новая коллекция:    {NEW_COLLECTION}")
    print(f"Рабочая коллекция:  не трогается\n")

    error_index = {}
    if ERROR_INDEX_PATH.exists():
        try:
            error_index = json.loads(ERROR_INDEX_PATH.read_text(encoding="utf-8"))
        except Exception:
            error_index = {}

    prepared, scans, failed = [], [], []

    for pdf in pdf_files:
        try:
            chunks, pages = read_pdf(pdf, split_text, is_useful, error_index)
            if pages == 0:
                scans.append(pdf.name)
                print(f"  скан без текста: {pdf.name}")
                continue
            if not chunks:
                print(f"  пусто после фильтра: {pdf.name}")
                continue
            print(f"  +{len(chunks):>4} кусков: {pdf.name}")
            prepared.extend(chunks)
        except Exception as error:
            failed.append((pdf.name, str(error)))
            print(f"  ОШИБКА: {pdf.name}: {error}")

    print("\n" + "=" * 58)
    print(f"  Сканов без текста: {len(scans)}")
    print(f"  Не прочиталось:    {len(failed)}")
    print(f"  Готово к записи:   {len(prepared)} кусков")
    print(f"  Кодов ошибок:      {len(error_index)}")
    print("=" * 58)

    if args.dry_run:
        print("\n--dry-run: ничего не записано.")
        return

    if not prepared:
        print("\nНечего записывать.")
        return

    print(f"\nЗагружаю модель (первый раз качается ~500 МБ)...")
    client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
    embedding = SentenceTransformerEmbeddingFunction(model_name=MODEL_NAME)

    # Пересобираем начисто: векторы прежней модели несовместимы с новой.
    try:
        client.delete_collection(NEW_COLLECTION)
        print(f"Прежняя {NEW_COLLECTION} удалена.")
    except Exception:
        pass

    collection = client.get_or_create_collection(
        name=NEW_COLLECTION, embedding_function=embedding
    )

    for i in range(0, len(prepared), BATCH_SIZE):
        batch = prepared[i:i + BATCH_SIZE]
        collection.upsert(
            ids=[x[0] for x in batch],
            documents=[x[1] for x in batch],
            metadatas=[x[2] for x in batch],
        )
        print(f"  записано {min(i + BATCH_SIZE, len(prepared))} из {len(prepared)}")

    ERROR_INDEX_PATH.write_text(
        json.dumps(error_index, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\n✓ {NEW_COLLECTION}: {collection.count()} кусков")
    print("Рабочая коллекция factory_manuals не тронута.")
    print("\nДальше: python3 compare_search.py — сравнить выдачу.")


if __name__ == "__main__":
    main()
