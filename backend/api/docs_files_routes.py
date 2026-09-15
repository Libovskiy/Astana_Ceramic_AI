"""
Документы по оборудованию — с проверкой сессии.

Папка docs была смонтирована как StaticFiles на /docs-files без всякой
авторизации: 172 руководства и схемы забирал любой, кто знает адрес.
Внутри локалки это терпимо, при выходе наружу — утечка.

Адреса намеренно оставлены прежними (/docs-files/<путь>), чтобы не
переписывать ссылки во фронтенде и не трогать file_path в базе.

Подключение в main.py:
    from backend.api.docs_files_routes import router as docs_files_router
    app.include_router(docs_files_router)

И ОБЯЗАТЕЛЬНО убрать старый app.mount("/docs-files", ...) — иначе в коде
останется незакрытая дверь, даже если сейчас её перекрывает роутер.
"""
import mimetypes
import unicodedata
from pathlib import Path

from fastapi import APIRouter, Cookie, Depends, HTTPException
from fastapi.responses import FileResponse

from backend.config import BASE_DIR
from backend.services.auth_service import get_user_by_session

router = APIRouter(tags=["docs-files"])

DOCS_DIR = (BASE_DIR / "docs").resolve()


def current_user(session_token: str | None = Cookie(default=None)):
    user = get_user_by_session(session_token)
    if user is None:
        raise HTTPException(status_code=401, detail="Не авторизован.")
    return user


@router.get("/docs-files/{file_path:path}")
def get_doc_file(file_path: str, user: dict = Depends(current_user)):
    if not file_path:
        raise HTTPException(status_code=404, detail="Файл не указан")

    # macOS хранит имена в NFD («ё» = «е» + умлаут), браузер шлёт NFC.
    # Без нормализации часть документов просто не находится.
    candidates = [
        DOCS_DIR / file_path,
        DOCS_DIR / unicodedata.normalize("NFC", file_path),
        DOCS_DIR / unicodedata.normalize("NFD", file_path),
    ]

    target = None
    for c in candidates:
        try:
            resolved = c.resolve()
        except Exception:
            continue
        # ../ в пути не должен выводить за пределы docs
        if not str(resolved).startswith(str(DOCS_DIR)):
            raise HTTPException(status_code=403, detail="Недопустимый путь")
        if resolved.is_file():
            target = resolved
            break

    if target is None:
        raise HTTPException(status_code=404, detail="Файл не найден")

    media_type, _ = mimetypes.guess_type(target.name)
    return FileResponse(
        target,
        media_type=media_type or "application/octet-stream",
        filename=target.name,
        headers={"Cache-Control": "private, max-age=3600"},
    )
