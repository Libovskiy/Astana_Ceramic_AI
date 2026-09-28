"""
Сворачиваемые разделы: механизм один на всю систему.

Длинные списки (очередь работ, оборудование, коды ошибок, работы ТО,
цехи при выборе станка) сворачиваются, чтобы страница помещалась на
экран. Владелец попросил это 28.09.2026: «слишком много места
занимает».

Главное, что здесь стережётся, — ЕДИНСТВЕННОСТЬ механизма. Он уже был
на «Электрике» (в plc-errors.js), и я чуть не написал рядом второй,
со своими классами. Два похожих сворачивания на соседних страницах
ведут себя по-разному, и человек перестаёт им доверять: здесь
запомнилось, там нет, здесь стрелка, там нет.

Ещё одно правило: свёрнутое не равно спрятанное. У каждой свёрнутой
секции в заголовке остаётся число — сколько там строк.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "frontend" / "static"
TEMPLATES = ROOT / "frontend" / "templates"

layout = (STATIC / "acai_layout.js").read_text(encoding="utf-8")
plc = (STATIC / "plc-errors.js").read_text(encoding="utf-8")
equip = (STATIC / "equipment.js").read_text(encoding="utf-8")
myto = (STATIC / "my-maintenance.js").read_text(encoding="utf-8")
acai_css = (STATIC / "acai.css").read_text(encoding="utf-8")
page_css = (STATIC / "equipment-page.css").read_text(encoding="utf-8")

checks, failed = 0, []


def check(condition, message, extra=None):
    global checks
    checks += 1
    if not condition:
        failed.append(message + (f" — {extra}" if extra is not None else ""))


# ── Механизм один ───────────────────────────────────────────────────
defined_in = [name for name, text in (
    ("acai_layout.js", layout), ("plc-errors.js", plc),
    ("equipment.js", equip), ("my-maintenance.js", myto),
) if re.search(r"function toggleSection\b", text)]
check(defined_in == ["acai_layout.js"],
      "toggleSection объявлен ровно один раз и в общем файле", defined_in)

check("function restoreSections" in layout, "есть возврат выбора человека")
check("localStorage" in layout.split("function toggleSection")[1][:600],
      "выбор запоминается, а не сбрасывается при каждом заходе")

styled_in = [name for name, text in (("acai.css", acai_css),
                                     ("equipment-page.css", page_css))
             if ".collapsible.collapsed .collapse-body" in text]
check(styled_in == ["acai.css"],
      "стили сворачивания лежат в общем файле и не продублированы", styled_in)

# ── Разметка страниц ────────────────────────────────────────────────
for name in ("mechanics.html", "electrical.html"):
    html = (TEMPLATES / name).read_text(encoding="utf-8")
    check('class="dashboard-card collapsible collapsed" id="queueCard"' in html,
          f"{name}: очередь работ сворачивается")
    check('id="queueCount"' in html, f"{name}: и показывает число работ")
    check("collapse-head" in html and "collapse-body" in html,
          f"{name}: разметка та же, что у остальных")
    check("data-collapse=" not in html,
          f"{name}: нет следов второго механизма")

mech = (TEMPLATES / "mechanics.html").read_text(encoding="utf-8")
check('id="equipmentCard"' in mech and 'id="equipmentCount"' in mech,
      "у механика список оборудования тоже сворачивается и считается")

check("myToCard" in myto and "collapse-count" in myto,
      "«Мои работы по ТО» сворачиваются и показывают число")

# ── Свёрнутое не значит спрятанное ──────────────────────────────────
check(".collapse-count:empty" in acai_css,
      "пустой значок числа не рисуется вовсе")
check("watchSectionCounts" in equip,
      "числа считаются по тому, что реально отрисовано")
check("expandSection(\"equipmentCard\")" in equip,
      "поиск раскрывает свёрнутую секцию сам")

# ── Цехи при выборе станка ──────────────────────────────────────────
chat = (STATIC / "chat.js").read_text(encoding="utf-8")
check("chat-zone-closed" in chat, "цехи при выборе станка свёрнуты")
check("openZones" in chat, "и разворачиваются по нажатию")
check("const open = q ? true : openZones.has(zone)" in chat,
      "при поиске цехи раскрываются сами")

# ── Версии статики подняты ──────────────────────────────────────────
index = (TEMPLATES / "index.html").read_text(encoding="utf-8")
for asset, least in (("acai.css", 63), ("acai_layout.js", 63)):
    found = re.search(rf"{re.escape(asset)}\?v=(\d+)", index)
    check(found and int(found.group(1)) >= least,
          f"версия {asset} поднята после правки", found and found.group(1))

print(f"Сворачиваемые разделы: проверок {checks}, сбоев {len(failed)}")
for item in failed:
    print("  -", item)
sys.exit(1 if failed else 0)
