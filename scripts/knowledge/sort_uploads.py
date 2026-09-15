#!/usr/bin/env python3
"""
Разбор документов из docs/uploads с потерянными именами.

Файлы, загруженные через сайт до вчерашней правки, сохранялись без
нормализации имени: кириллица превратилась в прочерки, и папки стали
называться «_______________________1». Поиск принимал такую папку за
документацию станка и выдавал советы по чужому оборудованию — так
дезинтегратору достался паспорт питателя.

Скрипт читает первую страницу каждого PDF, показывает, что внутри, и
предлагает папку. Ничего не двигает без подтверждения.

    cd /Users/champ_01/Documents/FactoryAssistant
    python3 sort_uploads.py            # показать, что нашлось
    python3 sort_uploads.py --apply    # разложить и убрать дубли
"""
import argparse
import hashlib
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DOCS = BASE_DIR / "docs"
UPLOADS = DOCS / "uploads"


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def first_text(path: Path, limit: int = 300) -> str:
    """Первые осмысленные строки из PDF — по ним видно, что за документ."""
    try:
        import fitz
    except ImportError:
        return "(нет pymupdf)"
    try:
        doc = fitz.open(path)
        try:
            for page in doc:
                text = " ".join((page.get_text() or "").split())
                if len(text) > 40:
                    return text[:limit]
        finally:
            doc.close()
    except Exception as error:
        return f"(не прочиталось: {error})"
    return "(текста нет — вероятно скан)"


def existing_folders():
    """Папки станков в docs, кроме uploads."""
    out = []
    for path in sorted(DOCS.rglob("*")):
        if path.is_dir() and UPLOADS not in path.parents and path != UPLOADS:
            out.append(path)
    return out


def guess_folder(text: str, name: str, folders):
    """
    Подсказка по ключевым словам из текста и имени файла.
    Это именно подсказка — решение за человеком.
    """
    hay = (text + " " + name).lower()

    hints = [
        (("pl024", "pl-024", "питатель"), "питател"),
        (("pl601", "pl-601", "дезинтегратор", "дезинтигратор"), "дезинтегратор"),
        (("усм 40", "усм40", "усм-40"), "усм 40"),
        (("microber", "gerim", "inyectair", "promatic", "presthermic", "печи", "обжиг"), "печь"),
        (("optima", "оптима"), "optima"),
        (("смк 126", "смеситель"), "смесител"),
        (("магна", "magna", "575"), "магна"),
        (("dte", "дробилк"), "дробилк"),
    ]

    for keys, folder_key in hints:
        if any(k in hay for k in keys):
            for folder in folders:
                if folder_key in folder.name.lower():
                    return folder
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="разложить файлы")
    args = ap.parse_args()

    if not UPLOADS.exists():
        print("docs/uploads не найдена — раскладывать нечего.")
        return

    folders = existing_folders()
    files = sorted(p for p in UPLOADS.rglob("*") if p.is_file())

    if not files:
        print("В docs/uploads пусто.")
        return

    # дубликаты по содержимому: одинаковые PDF с суффиксом _2
    by_hash = {}
    for path in files:
        by_hash.setdefault(file_hash(path), []).append(path)

    print(f"Файлов в uploads: {len(files)}")
    print(f"Уникальных по содержимому: {len(by_hash)}\n")
    print("=" * 78)

    plan = []

    for digest, paths in by_hash.items():
        original = min(paths, key=lambda p: len(p.name))
        duplicates = [p for p in paths if p != original]

        if original.suffix.lower() != ".pdf":
            print(f"\n[пропуск: не PDF] {original.name}")
            continue

        text = first_text(original)
        target = guess_folder(text, original.name, folders)

        print(f"\nФАЙЛ:    {original.relative_to(DOCS)}")
        print(f"РАЗМЕР:  {original.stat().st_size // 1024} КБ")
        print(f"ВНУТРИ:  {text[:200]}")
        if duplicates:
            print(f"ДУБЛИ:   {len(duplicates)} шт — {', '.join(d.name for d in duplicates)}")
        print(f"ПРЕДЛОЖЕНИЕ: {target.relative_to(DOCS) if target else '— не определилось, положите вручную'}")

        if target:
            plan.append((original, target, duplicates))

    print("\n" + "=" * 78)
    print(f"Определилось автоматически: {len(plan)}")

    if not args.apply:
        print("\nЭто предпросмотр. Проверьте предложения выше.")
        print("Если согласны — запустите: python3 sort_uploads.py --apply")
        print("Что не определилось — перенесите руками в нужную папку.")
        return

    print("\nПереношу...")
    moved = 0
    for original, target, duplicates in plan:
        # Имя оставляем как есть: оно испорчено, но менять его я не буду —
        # угадывать исходное название документа не моё дело.
        dest = target / original.name
        if dest.exists():
            print(f"  уже есть, пропуск: {dest.relative_to(DOCS)}")
            continue
        shutil.move(str(original), str(dest))
        moved += 1
        print(f"  → {dest.relative_to(DOCS)}")
        for dup in duplicates:
            dup.unlink()
            print(f"    дубль удалён: {dup.name}")

    print(f"\n✓ перенесено: {moved}")
    print("\nДальше: python3 rebuild_multilingual.py — пересобрать поиск.")


if __name__ == "__main__":
    main()
