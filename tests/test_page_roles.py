"""
Права на страницы должны совпадать в двух местах.

Список ролей для каждой страницы живёт дважды: на сервере
(PAGE_ROLES в backend/api/main.py) и в меню (NAV_ITEMS в
frontend/static/acai_layout.js). Так сделано намеренно — меню рисует
браузер, а пускает на страницу сервер, — но если списки разъедутся,
человек увидит ссылку, ведущую в отказ, либо наоборот: пункт исчезнет
из меню, а страница останется доступной по прямому адресу.

Этот тест сверяет два списка и падает при первом расхождении.
Боевые данные не трогаются: читаются только исходники.

Запуск (из корня проекта): python tests/test_page_roles.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MAIN_PY = ROOT / "backend" / "api" / "main.py"
LAYOUT_JS = ROOT / "frontend" / "static" / "acai_layout.js"

passed, failed = [], []


def check(name, condition, detail=""):
    if condition:
        passed.append(name)
    else:
        failed.append((name, detail))


# ─────────────────────────────────────────────────────────
# Читаем права с сервера
# ─────────────────────────────────────────────────────────

def parse_page_roles() -> dict:
    src = MAIN_PY.read_text(encoding="utf-8")

    block = re.search(
        r"PAGE_ROLES[^=]*=\s*\{(.*?)\n\}",
        src,
        re.S,
    )

    if not block:
        raise AssertionError("PAGE_ROLES не найден в backend/api/main.py")

    roles = {}

    for match in re.finditer(r'"(/[^"]*)":\s*("\*"|\([^)]*\))', block.group(1)):
        path, value = match.group(1), match.group(2)
        roles[path] = "*" if value == '"*"' else set(re.findall(r'"(\w+)"', value))

    return roles


# ─────────────────────────────────────────────────────────
# Читаем права из меню
# ─────────────────────────────────────────────────────────

def parse_nav_items() -> dict:
    src = LAYOUT_JS.read_text(encoding="utf-8")

    block = re.search(r"const NAV_ITEMS = \[(.*?)\n\];", src, re.S)

    if not block:
        raise AssertionError("NAV_ITEMS не найден в frontend/static/acai_layout.js")

    roles = {}

    for match in re.finditer(
        r"href:\s*'([^']+)'\s*,\s*roles:\s*('\*'|\[[^\]]*\])",
        block.group(1),
    ):
        href, value = match.group(1), match.group(2)
        roles[href] = "*" if value == "'*'" else set(re.findall(r"'(\w+)'", value))

    return roles


page_roles = parse_page_roles()
nav_roles = parse_nav_items()

check("PAGE_ROLES разобран", len(page_roles) > 10, f"нашлось {len(page_roles)}")
check("NAV_ITEMS разобран", len(nav_roles) > 10, f"нашлось {len(nav_roles)}")


# ─────────────────────────────────────────────────────────
# Каждая страница из меню должна быть закрыта на сервере
# ─────────────────────────────────────────────────────────

for href in sorted(nav_roles):
    check(
        f"{href} есть в PAGE_ROLES",
        href in page_roles,
        "страница есть в меню, но сервер её не проверяет — "
        "откроется по прямому адресу любому вошедшему",
    )


# ─────────────────────────────────────────────────────────
# Списки ролей должны совпадать
# ─────────────────────────────────────────────────────────

for href in sorted(nav_roles):

    if href not in page_roles:
        continue

    menu = nav_roles[href]
    server = page_roles[href]

    if menu == "*" or server == "*":
        check(
            f"{href}: открыт для всех в обоих местах",
            menu == server,
            f"меню={menu}, сервер={server}",
        )
        continue

    # admin в меню перечисляют явно, а на сервере он проходит всегда
    # (см. require_roles и сам middleware) — поэтому не сравниваем.
    menu_cmp = menu - {"admin"}
    server_cmp = server - {"admin"}

    only_menu = sorted(menu_cmp - server_cmp)
    only_server = sorted(server_cmp - menu_cmp)

    detail = []

    if only_menu:
        detail.append(
            f"видят ссылку, но сервер не пустит: {', '.join(only_menu)}"
        )

    if only_server:
        detail.append(
            f"сервер пускает, но ссылки в меню нет: {', '.join(only_server)}"
        )

    check(f"{href}: роли совпадают", not detail, "; ".join(detail))


# ─────────────────────────────────────────────────────────
# Итог
# ─────────────────────────────────────────────────────────

print(f"\nПроверок пройдено: {len(passed)}")

if failed:
    print(f"ПРОВАЛЕНО: {len(failed)}\n")
    for name, detail in failed:
        print(f"  ✕ {name}")
        if detail:
            print(f"      {detail}")
    print(
        "\nПравь оба места: PAGE_ROLES в backend/api/main.py и "
        "NAV_ITEMS в frontend/static/acai_layout.js"
    )
    sys.exit(1)

print("Права на страницы в меню и на сервере совпадают.")
