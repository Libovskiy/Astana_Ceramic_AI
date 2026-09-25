"""
Просмотр сканов, которые браузер не умеет показывать.

61 страница руководств лежит в TIF. Проверено в четырёх браузерах
25.09.2026:

    Chrome на компьютере  — не показывает, скачивает файл
    Chrome на Android     — не показывает
    Safari на Маке        — показывает
    Safari на айфоне      — показывает

То есть механик с телефона на Android вместо страницы руководства
получал скачанный файл, который нечем открыть. Поэтому отдаём копию в
PNG. Оригинал не трогаем: он остаётся на диске и скачивается по
прежнему адресу /docs-files.

Почему PNG в один бит и без уменьшения. Это чертежи и машинописный
текст: JPEG раздувает их вшестеро (16 КБ → 92 КБ) и мылит буквы, а
уменьшение до 1600 px делает файл крошечным, но съедает мелкие
подписи на схемах — а именно их человек и приезжает смотреть. Полный
размер в один бит весит 35–148 КБ на страницу.

Копии складываются рядом с базой знаний и считаются один раз: ключ —
путь, размер и время правки файла.
"""

import hashlib
import io
import unicodedata
from pathlib import Path

from fastapi import APIRouter, Cookie, Depends, HTTPException
from fastapi.responses import FileResponse

from backend.config import DOCS_PATH
from backend.services.auth_service import get_user_by_session

router = APIRouter(tags=["docs-preview"])

DOCS_DIR = DOCS_PATH.resolve()
PREVIEW_DIR = DOCS_PATH.parent / "knowledge_base" / "docs_preview"

# Что браузер не покажет сам. Word и Excel сюда не входят: их он тоже
# не рисует, но и превращать таблицу в картинку бессмысленно — такой
# файл открывают в своей программе.
NEEDS_PREVIEW = {".tif", ".tiff"}


def current_user(session_token: str | None = Cookie(default=None)):
    user = get_user_by_session(session_token)
    if user is None:
        raise HTTPException(status_code=401, detail="Не авторизован.")
    return user


def _resolve(file_path: str) -> Path:
    """Тот же поиск, что и у оригиналов: имена бывают в NFD и в NFC."""
    for candidate in (DOCS_DIR / file_path,
                      DOCS_DIR / unicodedata.normalize("NFC", file_path),
                      DOCS_DIR / unicodedata.normalize("NFD", file_path)):
        try:
            resolved = candidate.resolve()
        except Exception:
            continue
        if not resolved.is_relative_to(DOCS_DIR):
            raise HTTPException(status_code=403, detail="Недопустимый путь")
        if resolved.is_file():
            return resolved
    raise HTTPException(status_code=404, detail="Файл не найден")


def preview_path(source: Path) -> Path:
    stat = source.stat()
    key = f"{source.relative_to(DOCS_DIR)}|{stat.st_size}|{int(stat.st_mtime)}"
    return PREVIEW_DIR / (hashlib.sha256(key.encode()).hexdigest() + ".png")


def build_preview(source: Path) -> Path:
    """Сделать PNG, если его ещё нет. Оригинал только читается."""
    target = preview_path(source)
    if target.exists():
        return target

    from PIL import Image

    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        # Многостраничный TIF существует, но в наших сканах одна
        # страница на файл; берём первую и не молчим об остальном.
        image.seek(0)
        buffer = io.BytesIO()
        image.save(buffer, "PNG", optimize=True)

    # Пишем через временный файл: два одновременных запроса не должны
    # оставить наполовину записанную картинку.
    temporary = target.with_suffix(".part")
    temporary.write_bytes(buffer.getvalue())
    temporary.replace(target)
    return target


@router.get("/docs-preview/{file_path:path}")
def get_preview(file_path: str, user: dict = Depends(current_user)):
    source = _resolve(file_path)

    if source.suffix.lower() not in NEEDS_PREVIEW:
        raise HTTPException(status_code=400,
                            detail="Для этого файла просмотр не нужен.")

    try:
        target = build_preview(source)
    except Exception as error:
        print(f"[docs-preview] {source.name}: {error}")
        raise HTTPException(status_code=422, detail="Скан не удалось показать.")

    return FileResponse(target, media_type="image/png",
                        headers={"Cache-Control": "private, max-age=86400"})
