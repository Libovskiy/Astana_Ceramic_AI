"""
Статус документа в базе знаний: читает его ИИ или нет.

Загруженный файл виден в карточке станка, открывается, скачивается — и
человек уверен, что система теперь про него знает. Но если это скан без
текстового слоя, в базу знаний он не попадёт: распознавать картинки
индексатор не умеет. Молчание ИИ по такому станку выглядит как поломка,
хотя документ «вроде загружен».

Отдаём по каждому документу честное состояние, чтобы главный инженер
сразу видел, что скан надо распознать, а не гадал.

Подключение в main.py:
    from backend.api.doc_status_routes import router as doc_status_router
    app.include_router(doc_status_router)
"""
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Cookie, Depends, HTTPException

from backend.config import (
    CHROMA_COLLECTION_NAME,
    CHROMA_DB_PATH,
    DB_NAME,
    DOCS_PATH,
    EMBED_MODEL_NAME,
)
from backend.services.auth_service import get_user_by_session

router = APIRouter(tags=["documents-status"])


def current_user(session_token: str | None = Cookie(default=None)):
    user = get_user_by_session(session_token)
    if user is None:
        raise HTTPException(status_code=401, detail="Не авторизован.")
    return user


def _chunk_counts(file_names: list) -> dict:
    """Сколько кусков каждого файла лежит в базе знаний."""
    counts = {name: 0 for name in file_names}
    if not file_names:
        return counts

    try:
        import chromadb
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

        client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
        collection = client.get_collection(
            name=CHROMA_COLLECTION_NAME,
            embedding_function=SentenceTransformerEmbeddingFunction(
                model_name=EMBED_MODEL_NAME
            ),
        )
    except Exception:
        # База знаний недоступна — честнее ничего не утверждать,
        # чем показать «не проиндексирован» по всем документам.
        return {name: None for name in file_names}

    for name in file_names:
        try:
            found = collection.get(where={"file": name}, include=[])
            counts[name] = len(found.get("ids") or [])
        except Exception:
            counts[name] = None

    return counts


def _has_text_layer(path: Path) -> bool:
    """Есть ли в PDF извлекаемый текст — по первым страницам."""
    try:
        import fitz
    except ImportError:
        return True  # не можем проверить — не пугаем зря

    try:
        doc = fitz.open(path)
        try:
            for page in list(doc)[:5]:
                if len((page.get_text() or "").strip()) > 40:
                    return True
        finally:
            doc.close()
    except Exception:
        return True

    return False


@router.get("/api/equipment/{equipment_id}/documents/status")
def documents_status(equipment_id: int, user: dict = Depends(current_user)):
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT id, title, file_path FROM equipment_documents
               WHERE equipment_id = ? AND COALESCE(is_active, 1) = 1""",
            (equipment_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        conn.close()

    file_names = []
    for row in rows:
        file_path = row["file_path"] or ""
        file_names.append(Path(file_path).name)

    counts = _chunk_counts(file_names)

    result = []

    for row, name in zip(rows, file_names):
        chunks = counts.get(name)
        full_path = DOCS_PATH / (row["file_path"] or "")

        if chunks is None:
            state, hint = "unknown", "База знаний недоступна"
        elif chunks > 0:
            state, hint = "indexed", f"В базе знаний · {chunks} фрагм."
        elif not full_path.exists():
            state, hint = "missing", "Файл не найден на диске"
        elif full_path.suffix.lower() != ".pdf":
            state, hint = "not_pdf", "Не PDF — ИИ не читает"
        elif not _has_text_layer(full_path):
            state, hint = "scan", "Скан — ИИ не читает, нужно распознавание"
        else:
            state, hint = "pending", "Ещё не проиндексирован"

        result.append({
            "id": row["id"],
            "file": name,
            "chunks": chunks,
            "state": state,
            "hint": hint,
        })

    return {"success": True, "documents": result}
