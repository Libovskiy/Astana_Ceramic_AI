#!/usr/bin/env python3
"""
Убирает 404 на /favicon.ico.

Браузер запрашивает иконку сам, на каждой странице, и каждый раз получает
404 — в консоли мусор, во вкладке пустой лист вместо значка.

Отдаём SVG: он один на все размеры, не нужно плодить png под ретину.
Роут отвечает и на /favicon.ico, и на /favicon.svg — старые браузеры
просят первое, современные берут из <link>.

    cd /Users/champ_01/Documents/FactoryAssistant
    python3 fix_favicon.py

Идемпотентен.
"""
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
MAIN = BASE_DIR / "backend" / "api" / "main.py"
STATIC = BASE_DIR / "frontend" / "static"
TEMPLATES = BASE_DIR / "frontend" / "templates"

ROUTE = '''

# =========================================
# ИКОНКА САЙТА
# =========================================
# Браузер просит /favicon.ico на каждой странице. Без этого роута в
# консоли на каждой вкладке висит 404.

@app.get("/favicon.ico", include_in_schema=False)
@app.get("/favicon.svg", include_in_schema=False)
def favicon():
    from fastapi.responses import FileResponse
    from pathlib import Path as _P

    icon = _P("frontend/static/favicon.svg")

    if not icon.exists():
        from fastapi import Response
        return Response(status_code=204)

    return FileResponse(
        icon,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )
'''

LINK = '<link rel="icon" type="image/svg+xml" href="/favicon.svg">'


def main():
    if not MAIN.exists():
        print("✗ backend/api/main.py не найден — запускай из корня проекта")
        sys.exit(1)
    if not (STATIC / "favicon.svg").exists():
        print("✗ frontend/static/favicon.svg не найден — сначала скопируй его")
        sys.exit(1)

    # 1. роут
    text = MAIN.read_text(encoding="utf-8")
    if "def favicon(" in text:
        print("✓ роут иконки уже есть")
    else:
        anchor = 'templates = Jinja2Templates('
        if anchor not in text:
            print("✗ не нашёл, куда вставить роут — добавь вручную")
            sys.exit(1)
        idx = text.index(anchor)
        shutil.copy2(MAIN, MAIN.with_suffix(".py.bak-favicon"))
        MAIN.write_text(text[:idx] + ROUTE.strip() + "\n\n\n" + text[idx:], encoding="utf-8")
        print("✓ роут /favicon.ico добавлен")

    # 2. ссылка в шаблонах — чтобы браузер брал svg, а не гадал
    touched = 0
    for f in sorted(TEMPLATES.glob("*.html")):
        html = f.read_text(encoding="utf-8")
        if 'rel="icon"' in html:
            continue
        if "<head>" not in html:
            continue
        f.write_text(html.replace("<head>", "<head>\n" + LINK, 1), encoding="utf-8")
        touched += 1
    print(f"✓ ссылка на иконку добавлена в шаблонов: {touched}")

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
