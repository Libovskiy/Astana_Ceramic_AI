"""Incremental ingestion of one approved PDF into ACAI knowledge base."""
from pathlib import Path
import fitz
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

from backend.config import DOCS_PATH, CHROMA_DB_PATH, CHROMA_COLLECTION_NAME, EMBED_MODEL_NAME
from backend.services import regulation_service
from backend.tools.text_chunker import split_text
from backend.tools.document_filter import is_useful


def ingest_document(document_id: int):
    conn = regulation_service.get_connection()
    row = conn.execute("SELECT * FROM equipment_documents WHERE id = ?", (document_id,)).fetchone()
    conn.close()
    if not row:
        return
    if row["status"] != "approved" or Path(str(DOCS_PATH / row["file_path"])).suffix.lower() != ".pdf":
        return

    try:
        path = DOCS_PATH / row["file_path"]
        if not path.exists():
            raise FileNotFoundError(f"Файл не найден: {row['file_path']}")
        doc = fitz.open(path)
        chunks = []
        for page_no, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
            if not is_useful(text):
                continue
            for idx, chunk in enumerate(split_text(text)):
                if chunk.strip():
                    chunk_id = f"document:{document_id}:p{page_no}:c{idx}"
                    chunks.append((chunk_id, chunk, {
                        "document_id": str(document_id),
                        "equipment_id": str(row["equipment_id"] or ""),
                        "part_id": str(row["part_id"] or ""),
                        "stage_key": str(row["stage_key"] or ""),
                        "document": row["title"] or path.name,
                        "path": row["file_path"],
                        "page": page_no,
                    }))
        doc.close()
        if not chunks:
            raise ValueError("В PDF не найден читаемый текст. Если это скан, нужен OCR.")

        client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
        embedding = SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL_NAME)
        collection = client.get_or_create_collection(name=CHROMA_COLLECTION_NAME, embedding_function=embedding)
        for i in range(0, len(chunks), 200):
            batch = chunks[i:i+200]
            collection.upsert(ids=[x[0] for x in batch], documents=[x[1] for x in batch], metadatas=[x[2] for x in batch])
        regulation_service.mark_document_knowledge(document_id, "indexed")
    except Exception as exc:
        regulation_service.mark_document_knowledge(document_id, "error", str(exc)[:1000])
