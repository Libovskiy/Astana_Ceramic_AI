"""
Каждая страница с общим меню должна его построить.

acai_layout.js только объявляет initLayout(); вызывает его сама страница.
Забыл вызов — боковое меню пустое, колокольчика и часов нет, а ошибок в
консоли ноль, поэтому обход страниц этого не видит. Так на «Использовании»
и «Наблюдении» пропадали все остальные вкладки (нашёл владелец, 17.09.2026).

Запуск из корня проекта: python tests/test_layout_init.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "frontend" / "templates"
STATIC = ROOT / "frontend" / "static"

missing = []
for page in sorted(TEMPLATES.glob("*.html")):
    html = page.read_text(encoding="utf-8")
    if "acai_layout.js" not in html:
        continue
    if "initLayout(" in html:
        continue
    # вызов может жить в скрипте самой страницы
    scripts = re.findall(r'src="/static/([\w\-.]+\.js)', html)
    if any("initLayout(" in (STATIC / s).read_text(encoding="utf-8")
           for s in scripts if s != "acai_layout.js" and (STATIC / s).exists()):
        continue
    missing.append(page.name)

for name in missing:
    print(f"  СБОЙ {name}: подключает acai_layout.js, но не вызывает initLayout() — меню будет пустым")
print("Меню строится на всех страницах." if not missing else f"Страниц без меню: {len(missing)}")
sys.exit(1 if missing else 0)
