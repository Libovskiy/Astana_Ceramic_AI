#!/usr/bin/env python3
"""
Сравнение поиска: прежняя англоязычная модель против многоязычной.

Показывает по одному и тому же вопросу верхние результаты из двух
коллекций рядом. Смотреть надо не на числа расстояний — они у разных
моделей несравнимы, — а на то, попал ли в выдачу текст, относящийся
к вопросу.

    cd /Users/champ_01/Documents/FactoryAssistant
    source venv/bin/activate
    python3 compare_search.py
    python3 compare_search.py "не поднимается давление в прессе"
"""
import sys
import textwrap
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

CHROMA_DB_PATH = BASE_DIR / "knowledge_base" / "chroma_db"

OLD = ("factory_manuals", "all-MiniLM-L6-v2")
NEW = ("factory_manuals_ml", "paraphrase-multilingual-MiniLM-L12-v2")

# Реальные симптомы из системы — те, что уже вносили в обращения.
DEFAULT_QUESTIONS = [
    "перегрев",
    "посторонний шум или стук",
    "заклинило или застряло",
]

TOP = 3


def query(collection_name, model_name, question):
    import chromadb
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

    client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
    embedding = SentenceTransformerEmbeddingFunction(model_name=model_name)

    try:
        collection = client.get_collection(name=collection_name, embedding_function=embedding)
    except Exception as error:
        return None, f"коллекция недоступна: {error}"

    try:
        res = collection.query(query_texts=[question], n_results=TOP)
    except Exception as error:
        return None, f"ошибка запроса: {error}"

    rows = []
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    for doc, meta in zip(docs, metas):
        rows.append({
            "file": (meta or {}).get("file", "—"),
            "page": (meta or {}).get("page", "—"),
            "machine": (meta or {}).get("machine", "—"),
            "text": " ".join(str(doc).split())[:220],
        })
    return rows, None


def show(title, rows, error):
    print(f"\n  {title}")
    if error:
        print(f"    {error}")
        return
    if not rows:
        print("    ничего не найдено")
        return
    for i, r in enumerate(rows, 1):
        print(f"    {i}. [{r['machine']}] {r['file']}, стр. {r['page']}")
        for line in textwrap.wrap(r["text"], width=92):
            print(f"       {line}")


def main():
    questions = [" ".join(sys.argv[1:])] if len(sys.argv) > 1 else DEFAULT_QUESTIONS

    for question in questions:
        print("\n" + "=" * 96)
        print(f"ВОПРОС: {question}")
        print("=" * 96)

        rows, error = query(*OLD, question)
        show(f"БЫЛО — {OLD[1]}", rows, error)

        rows, error = query(*NEW, question)
        show(f"СТАЛО — {NEW[1]}", rows, error)

    print("\n" + "=" * 96)
    print("Смотрите на смысл: относится ли найденный текст к вопросу.")
    print("Числа расстояний у разных моделей несравнимы, поэтому их не показываю.")


if __name__ == "__main__":
    main()
