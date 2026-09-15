#!/usr/bin/env python3
"""
Закрывает /docs-files: убирает открытый StaticFiles и подключает роутер
с проверкой сессии.

    cd /Users/champ_01/Documents/FactoryAssistant
    python3 fix_docs_files.py

Идемпотентен. Делает копию main.py рядом.
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))

import re
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
MAIN = BASE_DIR / "backend" / "api" / "main.py"
ROUTER = BASE_DIR / "backend" / "api" / "docs_files_routes.py"

MOUNT_RE = re.compile(
    r"""app\.mount\(\s*\n?\s*["']/docs-files["']\s*,\s*\n?\s*"""
    r"""StaticFiles\(directory\s*=\s*["']docs["']\)\s*,?\s*\n?"""
    r"""(?:\s*name\s*=\s*["']docs-files["']\s*,?\s*\n?)?\s*\)""",
    re.MULTILINE,
)

INCLUDE = (
    "from backend.api.docs_files_routes import router as docs_files_router\n"
    "app.include_router(docs_files_router)"
)


def main():
    if not MAIN.exists():
        print("✗ backend/api/main.py не найден — запускай из корня проекта")
        sys.exit(1)
    if not ROUTER.exists():
        print("✗ backend/api/docs_files_routes.py не найден — сначала скопируй его")
        sys.exit(1)

    text = MAIN.read_text(encoding="utf-8")
    original = text
    changed = []

    # 1. убираем открытый mount
    if MOUNT_RE.search(text):
        text = MOUNT_RE.sub(
            "# /docs-files теперь отдаётся через docs_files_routes с проверкой сессии.\n"
            "# Открытый StaticFiles убран: он раздавал все руководства без авторизации.",
            text,
            count=1,
        )
        changed.append("открытый mount убран")
    elif "docs_files_routes" in text:
        print("✓ mount уже убран")
    else:
        print("! mount /docs-files не найден — проверь main.py руками")

    # 2. подключаем роутер
    if "docs_files_router" in text:
        if not changed:
            print("✓ роутер уже подключён")
    else:
        anchor = None
        for cand in (
            "app.include_router(equipment_health_router)",
            "app.include_router(maintenance_summary_router)",
            "app.include_router(checklist_router)",
            "app.include_router(audit_router)",
        ):
            if cand in text:
                anchor = cand
                break
        if anchor is None:
            print("✗ не нашёл, куда вставить include_router — добавь руками:")
            print("   " + INCLUDE.replace("\n", "\n   "))
            sys.exit(1)
        text = text.replace(anchor, anchor + "\n\n" + INCLUDE, 1)
        changed.append("роутер подключён")

    if text != original:
        shutil.copy2(MAIN, MAIN.with_suffix(".py.bak-docsfiles"))
        MAIN.write_text(text, encoding="utf-8")
        for c in changed:
            print(f"✓ {c}")
        print("  копия: backend/api/main.py.bak-docsfiles")

    # проверка
    left = re.search(r"""app\.mount\([^)]*docs-files""", text, re.S)
    print("✓ открытых mount на /docs-files не осталось" if not left else "✗ mount всё ещё в файле")
    print("\nДальше: очистить __pycache__ и перезапустить сервер.")


if __name__ == "__main__":
    main()
