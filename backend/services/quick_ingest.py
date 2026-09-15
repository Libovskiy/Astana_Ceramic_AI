"""
Индексация документа сразу после загрузки через карточку станка.

Было так: главный инженер прикрепляет паспорт в карточке, файл ложится
на диск, виден в списке, скачивается — а поиск про него не знает. ИИ
отвечает «документации не найдено» по станку, паспорт которого лежит
рядом. Индексация запускалась только при подтверждении документа через
раздел структуры, а этим путём никто не пользуется.

Разметку пишем ту же, что у остальной базы: поиск фильтрует по полю
machine, и без него документ попадёт в индекс, но останется невидимым —
что ещё хуже, чем не попасть вовсе.
"""
import re
import unicodedata
from pathlib import Path

from backend.config import (
    CHROMA_DB_PATH,
    CHROMA_COLLECTION_NAME,
    DOCS_PATH,
    EMBED_MODEL_NAME,
)

BATCH_SIZE = 200

# Оглавления и колонтитулы: строки из точек, голые номера страниц.
# Они похожи сразу на всё и лезут в выдачу вместо содержательных мест.
_JUNK = [re.compile(r"\.{6,}"), re.compile(r"^[\s\d.,:;|-]+$")]


def _looks_like_toc(chunk: str) -> bool:
    if any(pattern.search(chunk) for pattern in _JUNK):
        return True
    letters = sum(ch.isalpha() for ch in chunk)
    return letters < len(chunk) * 0.4


def index_uploaded_pdf(file_path: Path, machine_folder: str) -> dict:
    """
    Разбирает PDF и добавляет его в базу знаний.

    file_path      — полный путь к файлу на диске
    machine_folder — имя папки станка, оно же значение metadata.machine

    Возвращает {"chunks": N} или {"error": "..."} — вызывающий код
    решает, показывать ли это пользователю. Исключения наружу не
    выпускаем: загрузка документа не должна падать из-за индексации.
    """
    try:
        import fitz
        import chromadb
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

        from backend.tools.text_chunker import split_text
        from backend.tools.document_filter import is_useful
    except ImportError as error:
        return {"error": f"нет зависимостей: {error}"}

    path = Path(file_path)

    if not path.exists():
        return {"error": "файл не найден"}

    if path.suffix.lower() != ".pdf":
        return {"error": "не PDF — в базу знаний не попадёт"}

    try:
        relative = str(path.relative_to(DOCS_PATH))
    except ValueError:
        relative = path.name

    machine = unicodedata.normalize("NFC", str(machine_folder or "")).lower()

    prepared = []
    pages_with_text = 0

    try:
        doc = fitz.open(path)
        try:
            for page_number, page in enumerate(doc, start=1):
                text = page.get_text() or ""
                if not text.strip():
                    continue

                pages_with_text += 1
                text = " ".join(text.split())

                for index, chunk in enumerate(split_text(text)):
                    if not is_useful(chunk) or _looks_like_toc(chunk):
                        continue
                    prepared.append((
                        # Идентификатор стабилен: повторная загрузка того же
                        # файла перезапишет куски, а не удвоит их.
                        f"{relative}#{page_number}#{index}",
                        chunk,
                        {
                            "machine": machine,
                            "file": path.name,
                            "path": relative,
                            "page": page_number,
                        },
                    ))
        finally:
            doc.close()
    except Exception as error:
        return {"error": f"не прочитался: {error}"}

    if pages_with_text == 0:
        return {"error": "скан без текстового слоя — нужен OCR"}

    if not prepared:
        return {"error": "после отсева не осталось содержательного текста"}

    try:
        client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
        embedding = SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL_NAME)
        collection = client.get_or_create_collection(
            name=CHROMA_COLLECTION_NAME, embedding_function=embedding
        )

        for i in range(0, len(prepared), BATCH_SIZE):
            batch = prepared[i:i + BATCH_SIZE]
            collection.upsert(
                ids=[x[0] for x in batch],
                documents=[x[1] for x in batch],
                metadatas=[x[2] for x in batch],
            )
    except Exception as error:
        return {"error": f"база знаний недоступна: {error}"}

    return {"chunks": len(prepared)}
