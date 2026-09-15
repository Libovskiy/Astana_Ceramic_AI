#!/usr/bin/env python3
"""
Закрывает три находки аудита в main.py:

1. Обход пути при загрузке документов. Имя файла бралось из запроса
   (или из file.filename) и подставлялось прямо в путь — «../../» уводил
   запись за пределы docs. Та же ошибка, что была в старом коде фото
   обхода.
2. Нет потолка на размер и типа файла: гигабайтный файл забивал диск.
3. Нет ограничения попыток входа — пароль подбирался перебором.

    cd /Users/champ_01/Documents/FactoryAssistant
    python3 fix_security.py

Идемпотентен, делает копию main.py рядом.
"""
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
MAIN = BASE_DIR / "backend" / "api" / "main.py"

# ── 1. общие помощники ────────────────────────────────────
HELPERS = '''

# =========================================
# БЕЗОПАСНОСТЬ ЗАГРУЗОК И ВХОДА
# =========================================

import re as _re
import time as _time
import unicodedata as _ud
from collections import defaultdict as _dd
from threading import Lock as _Lock

MAX_DOC_BYTES = 50 * 1024 * 1024          # потолок на документ
ALLOWED_DOC_EXT = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".txt", ".jpg", ".jpeg", ".png"}


def safe_filename(name: str, default: str = "document.pdf") -> str:
    """
    Оставляет только имя файла, без каких-либо путей.

    Клиент присылает произвольную строку, и «../../backend/api/main.py»
    в ней — рабочий способ перезаписать код. Поэтому режем всё до
    последнего разделителя, выбрасываем управляющие символы и проверяем
    расширение по белому списку.
    """
    raw = str(name or "").strip()
    raw = raw.replace("\\\\", "/").split("/")[-1]      # и windows-, и unix-пути
    raw = _ud.normalize("NFC", raw)
    raw = _re.sub(r"[\\x00-\\x1f]", "", raw)
    raw = raw.lstrip(".") or default                  # «.», «..», «.htaccess»

    ext = ("." + raw.rsplit(".", 1)[-1].lower()) if "." in raw else ""
    if ext not in ALLOWED_DOC_EXT:
        raise HTTPException(
            status_code=415,
            detail=f"Такой тип файла загружать нельзя. Разрешены: {', '.join(sorted(ALLOWED_DOC_EXT))}",
        )
    return raw[:150]


# Ограничение попыток входа. Отдельный счётчик, а не общий
# rate_limit_service: у подбора пароля своя цена ошибки, и окно тут
# длиннее, чем минута.
LOGIN_MAX_ATTEMPTS = 10
LOGIN_WINDOW_SECONDS = 300
_login_attempts = _dd(list)
_login_lock = _Lock()


def login_allowed(key: str) -> bool:
    now = _time.time()
    with _login_lock:
        marks = _login_attempts[key]
        marks[:] = [t for t in marks if t > now - LOGIN_WINDOW_SECONDS]
        return len(marks) < LOGIN_MAX_ATTEMPTS


def login_failed(key: str) -> None:
    with _login_lock:
        _login_attempts[key].append(_time.time())


def login_succeeded(key: str) -> None:
    with _login_lock:
        _login_attempts.pop(key, None)
'''

# ── 2. вход с ограничением попыток ────────────────────────
OLD_LOGIN = '''@app.post("/auth/login")
def login(data: LoginRequest, response: Response):

    user = authenticate(data.username, data.password)

    if user is None:'''

NEW_LOGIN = '''@app.post("/auth/login")
def login(data: LoginRequest, response: Response, request: Request):

    # Ключ по адресу: перебор идёт с одной машины по списку логинов,
    # поэтому считать только по имени пользователя бесполезно.
    client_ip = request.client.host if request.client else "unknown"

    if not login_allowed(client_ip):
        log_action(username=data.username, role=None, action="login_blocked")
        return {
            "success": False,
            "message": "Слишком много попыток входа. Подождите 5 минут.",
        }

    user = authenticate(data.username, data.password)

    if user is None:

        login_failed(client_ip)'''

OLD_TOKEN = '''    token = create_session(user["id"])

    response.set_cookie('''
NEW_TOKEN = '''    login_succeeded(client_ip)

    token = create_session(user["id"])

    response.set_cookie('''

# ── 3. загрузка документа (multipart) ─────────────────────
OLD_UPLOAD = '''    safe_name = equipment["name"].replace("/", "-")
    folder = _Path("docs") / safe_name
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / file.filename
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)'''

NEW_UPLOAD = '''    safe_name = equipment["name"].replace("/", "-")
    folder = _Path("docs") / safe_name
    folder.mkdir(parents=True, exist_ok=True)

    # имя от клиента — только имя, без путей, и с проверкой расширения
    clean_name = safe_filename(file.filename)
    dest = folder / clean_name

    written = 0
    with dest.open("wb") as f:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > MAX_DOC_BYTES:
                f.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Файл больше 50 МБ")
            f.write(chunk)'''

OLD_UPLOAD_RET = '''    return {"success": True, "name": str(file.filename), "url": f"/docs-files/{safe_name}/{file.filename}"}'''
NEW_UPLOAD_RET = '''    return {"success": True, "name": clean_name, "url": f"/docs-files/{safe_name}/{clean_name}"}'''

# ── 4. загрузка документа (base64) ────────────────────────
OLD_B64 = '''    filename = request.get("filename", "document.pdf")
    data = request.get("data", "")
    try:
        file_bytes = _b64.b64decode(data)
        (folder / filename).write_bytes(file_bytes)'''

NEW_B64 = '''    filename = safe_filename(request.get("filename"))
    data = request.get("data", "")
    try:
        file_bytes = _b64.b64decode(data)
        if len(file_bytes) > MAX_DOC_BYTES:
            raise HTTPException(status_code=413, detail="Файл больше 50 МБ")
        (folder / filename).write_bytes(file_bytes)'''


def main():
    if not MAIN.exists():
        print("✗ backend/api/main.py не найден — запускай из корня проекта")
        sys.exit(1)

    text = MAIN.read_text(encoding="utf-8")
    original = text
    done, skipped = [], []

    # помощники — сразу после определения require_roles_rate_limited,
    # чтобы HTTPException и Request уже были импортированы
    if "def safe_filename(" in text:
        skipped.append("помощники уже добавлены")
    else:
        anchor = "def require_roles_rate_limited("
        if anchor not in text:
            print("✗ не нашёл, куда вставить помощники")
            sys.exit(1)
        idx = text.index(anchor)
        text = text[:idx] + HELPERS.strip() + "\n\n\n" + text[idx:]
        done.append("помощники добавлены")

    # marker — строка, которой в исходнике нет, а в изменённом коде есть.
    # Проверять «old отсутствует» нельзя: NEW_TOKEN целиком содержит
    # OLD_TOKEN, и при повторном запуске правка накладывалась дважды.
    for label, old, new, marker in (
        ("ограничение попыток входа", OLD_LOGIN, NEW_LOGIN, "login_allowed(client_ip)"),
        ("сброс счётчика при удачном входе", OLD_TOKEN, NEW_TOKEN, "login_succeeded(client_ip)"),
        ("загрузка документа: путь и размер", OLD_UPLOAD, NEW_UPLOAD, "clean_name = safe_filename(file.filename)"),
        ("загрузка документа: ответ", OLD_UPLOAD_RET, NEW_UPLOAD_RET, '"name": clean_name'),
        ("загрузка base64: путь и размер", OLD_B64, NEW_B64, 'filename = safe_filename(request.get("filename"))'),
    ):
        if marker in text:
            skipped.append(f"{label} — уже применено")
        elif old not in text:
            skipped.append(f"{label} — ФРАГМЕНТ НЕ НАЙДЕН, проверь вручную")
        else:
            text = text.replace(old, new, 1)
            done.append(label)

    if text != original:
        shutil.copy2(MAIN, MAIN.with_suffix(".py.bak-security"))
        MAIN.write_text(text, encoding="utf-8")

    for d in done:
        print(f"✓ {d}")
    for s in skipped:
        print(f"  {s}")

    if done:
        print("  копия: backend/api/main.py.bak-security")

    import py_compile
    try:
        py_compile.compile(str(MAIN), doraise=True)
        print("✓ main.py компилируется")
    except Exception as e:
        print(f"✗ синтаксическая ошибка: {e}")
        sys.exit(1)

    print("\nДальше: очистить __pycache__ и перезапустить сервер.")


if __name__ == "__main__":
    main()
