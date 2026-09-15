#!/usr/bin/env python3
"""
Возвращает доступ к странице учёта выпуска.

В main.py было ДВА роута /production. Первый отдавал устаревший
production_dashboard.html и перекрывал второй — а второй ведёт на
production.html, где «Учёт выпуска», «Месячный план», «Производство за
смену» и «История по сменам». Эта страница работала, но дойти до неё
было нельзя.

Дашборд удаляем: «Простои сегодня» перенесены на главную, «Последние
обращения» — это /cases, дерево оборудования — /equipment.

После правки:
    /            — главная: цепочка переделов, обращения, календарь, простои
    /production  — учёт выпуска: план, смены, история

    cd /Users/champ_01/Documents/FactoryAssistant
    python3 fix_production_page.py

Шаблон не удаляется, а переименовывается в .disabled — вернуть можно
одной командой. Идемпотентен.
"""
import re
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
MAIN = BASE_DIR / "backend" / "api" / "main.py"
LAYOUT = BASE_DIR / "frontend" / "static" / "acai_layout.js"
TEMPLATE = BASE_DIR / "frontend" / "templates" / "production_dashboard.html"


def patch_menu() -> None:
    """
    «Производство» остаётся на /production (учёт выпуска), но добавляем
    пункт «Главная» — на неё в меню не было ссылки вообще, попасть можно
    было только через логотип.
    """
    if not LAYOUT.exists():
        print("✗ acai_layout.js не найден")
        return
    text = LAYOUT.read_text(encoding="utf-8")

    if "label: 'Главная'" in text:
        print("✓ пункт «Главная» уже есть")
        return

    m = re.search(r"[ \t]*\{[^\n]*label:\s*'Производство',[^\n]*\}[,]?\n", text)
    if not m:
        print("! пункт «Производство» не найден — добавь «Главная» вручную")
        return

    roles = re.search(r"roles:\s*(\[[^\]]*\])", m.group(0))
    roles_str = roles.group(1) if roles else "[]"
    home = ("  { icon: '\U0001F3E0', label: 'Главная',       href: '/',   "
            f"roles: {roles_str} }},\n")

    shutil.copy2(LAYOUT, LAYOUT.with_suffix(".js.bak-production"))
    LAYOUT.write_text(text[:m.start()] + home + text[m.start():], encoding="utf-8")
    print("✓ добавлен пункт «Главная» → /")


def patch_routes() -> None:
    if not MAIN.exists():
        print("✗ main.py не найден")
        sys.exit(1)
    text = MAIN.read_text(encoding="utf-8")
    original = text

    # Удаляем ТОЛЬКО роут дашборда. Второй роут /production ведёт на
    # production.html (учёт выпуска) — его как раз и надо освободить.
    pattern = re.compile(
        r"@app\.get\(\"/production\"\)\s*\n"
        # в сигнатуре есть вложенные скобки — Depends(require_roles(...)),
        # поэтому берём всё до "):" в конце строки, а не до первой скобки
        r"def production_dashboard\(.*\):[ \t]*\n"
        r"\s+return templates\.TemplateResponse\([^)]*production_dashboard\.html[^)]*\)\s*\n",
        re.MULTILINE,
    )
    found = len(pattern.findall(text))
    if found:
        text = pattern.sub("", text)
        print("✓ роут дашборда убран — /production ведёт на учёт выпуска")
    else:
        print("✓ роут дашборда уже убран")

    left = text.count('@app.get("/production")')
    print(f"  роутов /production осталось: {left} (должен быть 1)")

    if text != original:
        shutil.copy2(MAIN, MAIN.with_suffix(".py.bak-production"))
        MAIN.write_text(text, encoding="utf-8")
        print("  копия: backend/api/main.py.bak-production")

    import py_compile
    try:
        py_compile.compile(str(MAIN), doraise=True)
        print("✓ main.py компилируется")
    except Exception as e:
        print(f"✗ синтаксическая ошибка: {e}")
        sys.exit(1)


def disable_template() -> None:
    if not TEMPLATE.exists():
        print("✓ шаблон уже отключён")
        return
    TEMPLATE.rename(TEMPLATE.with_suffix(".html.disabled"))
    print("✓ production_dashboard.html → .disabled (вернуть: mv обратно)")


def main():
    patch_menu()
    patch_routes()
    disable_template()
    print("\nДальше: поднять ?v= у acai_layout.js, очистить __pycache__, перезапустить.")


if __name__ == "__main__":
    main()
