#!/usr/bin/env python3
"""
Распознавание сканов и добавление их текста в базу знаний.

Из 424 документов 269 — сканы: внутри картинки страниц, текста нет.
Поиск их не видит, ИИ по ним молчит. Среди них паспорта шкафов,
протоколы, руководства — больше половины документации завода.

Оригиналы НЕ трогаем. Обычно при распознавании в PDF встраивают
текстовый слой, переписывая файл, — долго и рискованно. Нам текст нужен
только для поиска, поэтому распознаём страницы и кладём результат прямо
в базу знаний. Документы остаются как есть.

Что нужно поставить один раз:

    brew install tesseract tesseract-lang

Проверить, что русский появился:

    tesseract --list-langs        # в списке должен быть rus

Запуск:

    cd /Users/champ_01/Documents/FactoryAssistant
    source venv/bin/activate
    python3 ocr_index.py --check        # что будет распознано
    python3 ocr_index.py --limit 3      # попробовать на трёх
    python3 ocr_index.py                # всё остальное

Прерывать можно: прогресс пишется в knowledge_base/ocr_done.json,
повторный запуск продолжит с места остановки.
"""
import argparse
import json
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

DOCS_PATH = BASE_DIR / "docs"
PROGRESS_PATH = BASE_DIR / "knowledge_base" / "ocr_done.json"

# 200 точек на дюйм: ниже — распознавание сыпется на мелком шрифте
# чертежей, выше — растёт время без заметной пользы на паспортах.
DPI = 200

# Сканы бывают на сотни страниц (альбомы схем, протоколы испытаний).
# Ограничиваем: дальше идут приложения и штампы, а время растёт линейно.
MAX_PAGES = 40

BATCH_SIZE = 200


def has_text_layer(path: Path) -> bool:
    """Есть ли в PDF извлекаемый текст — тогда распознавать не нужно."""
    import fitz

    try:
        doc = fitz.open(path)
        try:
            for page in list(doc)[:5]:
                if len((page.get_text() or "").strip()) > 40:
                    return True
        finally:
            doc.close()
    except Exception:
        return True  # не прочитался — не наше дело, пропустим

    return False


def ocr_with_confidence(image_path: Path, lang: str, psm: str) -> tuple:
    """
    Распознаёт страницу и возвращает (текст, средняя уверенность).

    Уверенность берём у самой распознавалки: она выдаёт её по каждому
    слову в табличном режиме. Это надёжнее самодельных проверок —
    я пробовал угадывать кашу по виду слов, и «чкэтия01045И» такую
    проверку проходило как нормальное русское слово.
    """
    try:
        result = subprocess.run(
            [TESSERACT, str(image_path), "stdout", "-l", lang, "--psm", psm, "tsv"],
            capture_output=True, text=True, timeout=180,
        )
    except Exception:
        return "", 0.0

    words, scores = [], []

    for line in (result.stdout or "").splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 12:
            continue
        text, conf = parts[11].strip(), parts[10]
        if not text:
            continue
        try:
            value = float(conf)
        except ValueError:
            continue
        if value < 0:
            continue
        words.append(text)
        scores.append(value)

    if not words:
        return "", 0.0

    return " ".join(words), sum(scores) / len(scores)


# Ниже этого порога текст нечитаемый: повёрнутый скан, мятый лист,
# слишком низкое разрешение. Такое в базу класть нельзя — поиск будет
# выдавать бред и подрывать доверие ко всей выдаче.
MIN_CONFIDENCE = 55.0


def ocr_page(image_path: Path, lang: str) -> str:
    """
    Распознаёт страницу, при необходимости подбирая поворот.

    Часть сканов сделана вверх ногами или боком — без поворота
    распознавание выдаёт кашу. Сначала пробуем автоопределение, потом
    перебираем четыре поворота и берём вариант с лучшей уверенностью.
    """
    text, confidence = ocr_with_confidence(image_path, lang, "1")

    if confidence >= MIN_CONFIDENCE:
        return text

    best_text, best_confidence = text, confidence

    for angle in (90, 180, 270):
        rotated = rotate_image(image_path, angle)
        if rotated is None:
            continue
        try:
            candidate, candidate_confidence = ocr_with_confidence(rotated, lang, "3")
        finally:
            rotated.unlink(missing_ok=True)

        if candidate_confidence > best_confidence:
            best_text, best_confidence = candidate, candidate_confidence

        if best_confidence >= MIN_CONFIDENCE:
            break

    # Не дотянули — возвращаем пусто: лучше без документа, чем с кашей.
    return best_text if best_confidence >= MIN_CONFIDENCE else ""


def rotate_image(image_path: Path, angle: int):
    """Поворачивает страницу и возвращает путь к копии."""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        out = image_path.with_name(f"{image_path.stem}_r{angle}.png")
        with Image.open(image_path) as img:
            img.rotate(angle, expand=True).save(out)
        return out
    except Exception:
        return None


def ocr_pdf(path: Path, lang: str) -> tuple:
    """
    Распознаёт документ постранично.
    Возвращает (список страниц-текстов, сколько страниц обработано).
    """
    import fitz

    pages = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        try:
            doc = fitz.open(path)
        except Exception:
            return [], 0

        try:
            total = min(len(doc), MAX_PAGES)

            for number in range(total):
                image_file = tmp_dir / f"p{number}.png"

                try:
                    pixmap = doc[number].get_pixmap(dpi=DPI)
                    pixmap.save(image_file)
                except Exception:
                    continue

                text = " ".join(ocr_page(image_file, lang).split())
                image_file.unlink(missing_ok=True)

                # Короткий результат — шум распознавания пустой страницы.
                # Нечитаемое ocr_page уже отбросил по уверенности.
                if len(text) > 60:
                    pages.append((number + 1, text))
        finally:
            doc.close()

    return pages, total


def load_progress() -> dict:
    if PROGRESS_PATH.exists():
        try:
            return json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_progress(done: dict):
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_PATH.write_text(
        json.dumps(done, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# Путь к распознавалке ищем сами. Python внутри venv может не видеть
# Homebrew: окружение активировали до того, как brew прописался в PATH,
# и тогда tesseract работает в терминале, но не из скрипта.
TESSERACT = None


def find_tesseract() -> str:
    import shutil

    found = shutil.which("tesseract")
    if found:
        return found

    for candidate in (
        "/opt/homebrew/bin/tesseract",      # Apple Silicon
        "/usr/local/bin/tesseract",         # Intel
        "/opt/local/bin/tesseract",         # MacPorts
        "/usr/bin/tesseract",               # Linux
    ):
        if Path(candidate).exists():
            return candidate

    print("✗ tesseract не найден ни в PATH, ни в обычных местах установки.")
    print("  Поставьте: brew install tesseract tesseract-lang")
    print("  Если уже поставлен — выполните в этом же окне:")
    print('    eval "$(/opt/homebrew/bin/brew shellenv zsh)"')
    sys.exit(1)


def pick_language() -> str:
    global TESSERACT
    TESSERACT = find_tesseract()
    print(f"Распознавалка:       {TESSERACT}")

    try:
        result = subprocess.run(
            [TESSERACT, "--list-langs"], capture_output=True, text=True, timeout=30
        )
        # Часть версий печатает список в stderr, часть в stdout.
        langs = set((result.stdout + " " + result.stderr).split())
    except Exception as error:
        print(f"✗ не удалось запустить tesseract: {error}")
        sys.exit(1)

    if "rus" in langs and "eng" in langs:
        return "rus+eng"
    if "rus" in langs:
        return "rus"

    print("✗ Русский язык для tesseract не установлен.")
    print("  Поставьте: brew install tesseract-lang")
    print(f"  Сейчас доступно: {', '.join(sorted(langs)) or '—'}")
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="только показать список")
    ap.add_argument("--limit", type=int, help="обработать не больше N документов")
    ap.add_argument("--only", help="только документы, чей путь содержит подстроку")
    ap.add_argument("--redo", action="store_true",
                    help="перераспознать уже обработанные (после правки распознавания)")
    args = ap.parse_args()

    if not DOCS_PATH.exists():
        print("✗ docs/ не найдена — запускай из корня проекта")
        sys.exit(1)

    from backend.tools.text_chunker import split_text
    from backend.tools.document_filter import is_useful

    lang = pick_language()
    done = {} if args.redo else load_progress()

    if args.redo:
        print("Режим --redo: обработанные раньше документы будут распознаны заново.")

    pdfs = sorted(DOCS_PATH.rglob("*.pdf"))
    if args.only:
        pdfs = [p for p in pdfs if args.only.lower() in str(p).lower()]

    scans = []
    for path in pdfs:
        relative = str(path.relative_to(DOCS_PATH))
        if relative in done:
            continue
        if has_text_layer(path):
            continue
        scans.append(path)

    print(f"Язык распознавания:  {lang}")
    print(f"Уже обработано:      {len(done)}")
    print(f"Осталось сканов:     {len(scans)}")

    if args.limit:
        scans = scans[:args.limit]
        print(f"Возьмём сейчас:      {len(scans)}")

    # Оценка по опыту: страница распознаётся около 2–4 секунд.
    print(f"\nПримерное время:     {len(scans) * 15 // 60 + 1} мин "
          f"(зависит от числа страниц)\n")

    if args.check or not scans:
        for path in scans[:40]:
            print(f"  {path.relative_to(DOCS_PATH)}")
        if len(scans) > 40:
            print(f"  ... и ещё {len(scans) - 40}")
        if args.check:
            print("\nЭто предпросмотр. Запустите без --check, чтобы распознать.")
        return

    import chromadb
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
    from backend.config import CHROMA_DB_PATH, CHROMA_COLLECTION_NAME, EMBED_MODEL_NAME

    client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
    collection = client.get_or_create_collection(
        name=CHROMA_COLLECTION_NAME,
        embedding_function=SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL_NAME),
    )

    started = time.time()
    added_total = 0
    empty = []

    for index, path in enumerate(scans, start=1):
        relative = str(path.relative_to(DOCS_PATH))
        machine = unicodedata.normalize("NFC", path.parent.name).lower()

        print(f"[{index}/{len(scans)}] {path.name}", flush=True)

        pages, total_pages = ocr_pdf(path, lang)

        if not pages:
            empty.append(relative)
            done[relative] = {"chunks": 0, "note": "распознать не удалось"}
            save_progress(done)
            print("    пусто — вероятно, чертёж или плохое качество скана")
            continue

        prepared = []
        for page_number, text in pages:
            for chunk_index, chunk in enumerate(split_text(text)):
                if not is_useful(chunk):
                    continue
                prepared.append((
                    f"{relative}#ocr{page_number}#{chunk_index}",
                    chunk,
                    {
                        "machine": machine,
                        "file": path.name,
                        "path": relative,
                        "page": page_number,
                        # Помечаем: текст получен распознаванием, он может
                        # содержать ошибки. Видно и в выдаче, и при разборе.
                        "source": "ocr",
                    },
                ))

        if not prepared:
            empty.append(relative)
            done[relative] = {"chunks": 0, "note": "после отсева пусто"}
            save_progress(done)
            print("    после отсева ничего не осталось")
            continue

        # Идентификаторы кусков стабильные, поэтому upsert перезапишет
        # прежний результат распознавания, а не создаст дубли.
        for start in range(0, len(prepared), BATCH_SIZE):
            batch = prepared[start:start + BATCH_SIZE]
            collection.upsert(
                ids=[x[0] for x in batch],
                documents=[x[1] for x in batch],
                metadatas=[x[2] for x in batch],
            )

        added_total += len(prepared)
        done[relative] = {"chunks": len(prepared), "pages": len(pages)}
        save_progress(done)

        elapsed = int(time.time() - started)
        print(f"    +{len(prepared)} кусков с {len(pages)} стр. "
              f"(из {total_pages}) · прошло {elapsed // 60}м {elapsed % 60}с")

    print("\n" + "=" * 58)
    print(f"  Обработано документов: {len(scans) - len(empty)}")
    print(f"  Без результата:        {len(empty)}")
    print(f"  Добавлено кусков:      {added_total}")
    print(f"  Всего в базе знаний:   {collection.count()}")
    print("=" * 58)

    if empty:
        print("\nНе распозналось (обычно чертежи и схемы без текста):")
        for name in empty[:15]:
            print(f"  {name}")
        if len(empty) > 15:
            print(f"  ... и ещё {len(empty) - 15}")


if __name__ == "__main__":
    main()
