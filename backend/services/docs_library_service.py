"""
Документация завода — то, что реально лежит на диске.

Зачем это отдельно от equipment_documents. В списке документов системы
18 строк: их заводили руками через карточку станка. На диске при этом
650 файлов, из них 452 PDF — заводскую документацию заливали папками,
минуя систему. Вкладка «Документация» знала о шести из них и была
пустее, чем знает ИИ: он ищет по этим же папкам.

Что делает этот модуль:

  • обходит DOCS_PATH и собирает файлы годных для документации типов;
  • сопоставляет папку со станком ТОЛЬКО там, где совпадение
    однозначно, — остальное честно идёт в «Без привязки к станку»,
    внутри по папкам цехов. Угадывать нельзя: «руководство не от
    этого станка» хуже, чем «руководство лежит вот здесь»;
  • одинаковые файлы в разных папках (их много: одну и ту же
    инструкцию по вентилятору положили в пять папок) показывает
    один раз, по sha256, с пометкой, где ещё лежит.

Файлы отдаются не отсюда, а через /docs-files с проверкой сессии
(backend/api/docs_files_routes.py). Это документация производителей,
наружу она уходить не должна.

Хеши кэшируются: считать sha256 по 697 МБ на каждый заход страницы
недопустимо. Ключ кэша — путь, размер и время правки; тронули файл —
пересчитается сам.
"""

import hashlib
import json
import sqlite3
import unicodedata
from pathlib import Path

from backend.config import DB_NAME, DOCS_PATH

# Что показываем. Прочее в папках есть (.tmp, .spl7, .db) — это мусор
# выгрузки, человеку он не документация.
DOC_SUFFIXES = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".jpg", ".jpeg",
                ".png", ".tif", ".tiff"}

SUFFIX_LABEL = {".pdf": "PDF", ".doc": "Word", ".docx": "Word",
                ".xls": "Excel", ".xlsx": "Excel", ".jpg": "Фото",
                ".jpeg": "Фото", ".png": "Фото", ".tif": "Скан", ".tiff": "Скан"}

# Что браузер не покажет сам. Проверено 25.09.2026: Chrome не
# открывает TIF ни на компьютере, ни на Android — скачивает файл;
# Safari на Маке и айфоне открывает. Для таких отдаём копию в PNG по
# /docs-preview, а оригинал оставляем скачиваемым.
NEEDS_PREVIEW = {".tif", ".tiff"}

UNLINKED = "Без привязки к станку"

_CACHE_PATH = DOCS_PATH.parent / "knowledge_base" / "docs_hashes.json"


def _fold(value: str) -> str:
    """
    Имя папки и имя станка к одному виду.

    Косая черта в имени станка («GERIM 200/2/14», «GB/1500») в файловой
    системе невозможна, и при выгрузке её заменили двоеточием. Это не
    догадка, а известная замена — приводим оба знака к одному.
    """
    text = unicodedata.normalize("NFC", (value or "").strip()).lower()
    for char in "/:\\":
        text = text.replace(char, " ")
    return " ".join(text.split())


def _equipment_index() -> dict:
    """
    Имя папки → станок, только однозначные совпадения.

    Если два станка сворачиваются в одно имя, такое имя выбрасываем:
    привязать документ к одному из двух наугад хуже, чем не привязать.
    """
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, name, location FROM equipment WHERE COALESCE(is_active, 1) = 1")]
    finally:
        conn.close()

    index, ambiguous = {}, set()
    for row in rows:
        key = _fold(row["name"])
        if not key:
            continue
        if key in index:
            ambiguous.add(key)
            continue
        index[key] = row
    for key in ambiguous:
        index.pop(key, None)
    return index


def _load_cache() -> dict:
    try:
        return json.loads(_CACHE_PATH.read_text())
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(cache))
    except Exception as error:
        print(f"[docs] кэш хешей не сохранён: {error}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scan_library() -> dict:
    """
    Вся документация с диска, сгруппированная по станкам.

    Возвращает группы: по станку — там, где папка совпала с его
    названием однозначно; остальное — «Без привязки к станку», внутри
    по папкам цехов. Одинаковые файлы схлопнуты по sha256.
    """
    root = DOCS_PATH.resolve()
    if not root.exists():
        return {"groups": [], "files_total": 0, "duplicates": 0, "unlinked": 0}

    index = _equipment_index()
    cache = _load_cache()
    fresh, changed = {}, False

    by_hash = {}

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in DOC_SUFFIXES:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue

        rel = path.relative_to(root)
        key = f"{rel}|{stat.st_size}|{int(stat.st_mtime)}"
        digest = cache.get(key)
        if not digest:
            try:
                digest = _sha256(path)
            except OSError:
                continue
            changed = True
        fresh[key] = digest

        # Станок ищем по самой глубокой папке, которая совпала: у
        # «МАССАПОДГОТОВКА/Дробилка DTE 117» станок — дробилка, а не цех.
        machine, matched_at = None, None
        for parent in list(rel.parents)[:-1]:
            found = index.get(_fold(parent.name))
            if found:
                machine, matched_at = found, parent
                break

        # Что лежит МЕЖДУ папкой станка и файлом. Руководство по
        # вальцам УСМ 40 разложено постранично: 60 сканов в «РЭ» и 50
        # в «Электрической схеме». Без этой подписи станок выглядел бы
        # списком из 114 безымянных страниц вместо двух документов.
        part = ""
        if matched_at is not None:
            inner = rel.parent.relative_to(matched_at)
            part = inner.as_posix() if inner.as_posix() != "." else ""

        entry = by_hash.setdefault(digest, {
            "sha256": digest,
            "title": path.name,
            "size_bytes": stat.st_size,
            "kind": SUFFIX_LABEL.get(path.suffix.lower(), path.suffix.lstrip(".").upper()),
            "url": f"/docs-files/{rel.as_posix()}",
            "preview_url": (f"/docs-preview/{rel.as_posix()}"
                            if path.suffix.lower() in NEEDS_PREVIEW else None),
            "machine_id": machine["id"] if machine else None,
            "machine_name": machine["name"] if machine else None,
            "zone": (machine or {}).get("location") or rel.parts[0],
            "part": part,
            "path": rel.as_posix(),
            "also_in": [],
        })
        if entry["path"] != rel.as_posix():
            entry["also_in"].append(rel.parent.as_posix() or ".")
            # Копия лежит в папке станка, а первая найденная — нет:
            # показываем ту, что привязана, она человеку полезнее.
            if entry["machine_id"] is None and machine:
                entry.update(machine_id=machine["id"], machine_name=machine["name"],
                             zone=machine["location"] or rel.parts[0], part=part,
                             url=f"/docs-files/{rel.as_posix()}", path=rel.as_posix(),
                             preview_url=(f"/docs-preview/{rel.as_posix()}"
                                          if path.suffix.lower() in NEEDS_PREVIEW else None))

    if changed or len(fresh) != len(cache):
        _save_cache(fresh)

    # ── Группировка ────────────────────────────────────────────────
    groups = {}
    for item in by_hash.values():
        if item["machine_name"]:
            key = ("machine", item["machine_name"])
            title, sub = item["machine_name"], item["zone"] or ""
        else:
            folder = item["path"].split("/")[0]
            key = ("folder", folder)
            title, sub = folder, UNLINKED
        group = groups.setdefault(key, {"title": title, "sub": sub,
                                        "linked": key[0] == "machine", "items": []})
        group["items"].append(item)

    ordered = sorted(
        groups.values(),
        # Сначала привязанные к станкам — их ищут чаще; внутри по алфавиту.
        key=lambda g: (not g["linked"], g["title"].lower()),
    )
    for group in ordered:
        group["items"].sort(key=lambda i: (i["part"].lower(), i["title"].lower()))
        # Сколько в группе документов, а не страниц: человек ищет
        # «руководство по вальцам», а не «скан 37».
        group["parts"] = sorted({i["part"] for i in group["items"] if i["part"]})

    return {
        "groups": ordered,
        "files_total": len(fresh),
        "unique": len(by_hash),
        "duplicates": len(fresh) - len(by_hash),
        "unlinked": sum(len(g["items"]) for g in ordered if not g["linked"]),
    }


def registry_orphans() -> list:
    """
    Записи в списке документов системы, у которых файла нет на месте.

    Не удаляем: строка — след того, что документ заводили, и по ней
    видно, что именно надо перезалить. У пяти записей от 13-14.09 в
    пути одни подчёркивания — кириллица в именах потерялась при
    загрузке, и папки docs/uploads/… остались пустыми.
    """
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(
            """
            SELECT d.id, d.title, d.file_path, d.added_at, d.added_by,
                   e.name AS equipment_name
            FROM equipment_documents d
            LEFT JOIN equipment e ON e.id = d.equipment_id
            WHERE COALESCE(d.is_active, 1) = 1
            ORDER BY e.name, d.title
            """)]
    finally:
        conn.close()

    root = DOCS_PATH.resolve()
    return [r for r in rows
            if not r["file_path"] or not (root / r["file_path"]).exists()]
