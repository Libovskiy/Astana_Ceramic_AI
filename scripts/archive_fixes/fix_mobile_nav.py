#!/usr/bin/env python3
"""
Подключает мобильную навигацию ко всем страницам v2.

Скрипт мобильного меню уже был в проекте, но подключён к четырём старым
страницам и рассчитан на разметку первой версии — искал .page-header,
которого в v2 нет. Поэтому на телефоне меню не открывалось нигде, кроме
механики и электрики.

Новый файл mobile_nav_v2.js работает с текущей разметкой и добавляет
нижнюю панель быстрых переходов. Ставим его на каждую страницу, где
подключён acai_layout.js — то есть на все страницы v2.

    cd /Users/champ_01/Documents/FactoryAssistant
    python3 fix_mobile_nav.py

Идемпотентен.
"""
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
TEMPLATES = BASE_DIR / "frontend" / "templates"
SCRIPT = BASE_DIR / "frontend" / "static" / "mobile_nav_v2.js"

TAG = '<script src="/static/mobile_nav_v2.js?v=1"></script>'


def main():
    if not TEMPLATES.exists():
        print("✗ frontend/templates не найдена — запускай из корня проекта")
        sys.exit(1)
    if not SCRIPT.exists():
        print("✗ frontend/static/mobile_nav_v2.js не найден — сначала скопируй его")
        sys.exit(1)

    touched, already, skipped = [], [], []

    for path in sorted(TEMPLATES.glob("*.html")):
        html = path.read_text(encoding="utf-8")

        if "mobile_nav_v2.js" in html:
            already.append(path.name)
            continue

        # Только страницы v2: у них подключён acai_layout.js
        match = re.search(r'<script src="/static/acai_layout\.js[^"]*"></script>', html)
        if not match:
            skipped.append(path.name)
            continue

        # Ставим сразу после layout: навигация строится из готового сайдбара.
        html = html[:match.end()] + "\n" + TAG + html[match.end():]
        path.write_text(html, encoding="utf-8")
        touched.append(path.name)

    print(f"✓ подключено: {len(touched)}")
    for name in touched:
        print(f"    {name}")
    if already:
        print(f"✓ уже было: {len(already)}")
    if skipped:
        print(f"  пропущено (не v2): {len(skipped)}")

    print("\nДальше: обновить страницу на телефоне.")


if __name__ == "__main__":
    main()
