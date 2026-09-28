"""
Единицы показаний: берутся из справочника, а не угадываются по имени.

Нашёл владелец 28.09.2026: «почему везде используются проценты». На
«Аналитике» к любому показанию дописывался процент — частота конвейера
выглядела как «50,0 %», а моточасы как «8 073 268,0 %». Причина: каждая
страница угадывала единицу по имени регистра, и там, где «проц» в имени
не было, всё равно ставился процент.

Единицу заполняет главный инженер в справочнике регистров. Она и должна
быть источником: имена заводили люди и по-разному.

Проверяется по исходникам — как выглядит подпись, видно на снимках, а
вот расхождение правил между страницами видно только так.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "frontend" / "static"
TEMPLATES = ROOT / "frontend" / "templates"

helper = (STATIC / "sensor-names.js").read_text(encoding="utf-8")
pages = {name: (TEMPLATES / name).read_text(encoding="utf-8")
         for name in ("index.html", "analytics.html", "reports.html")}

checks, failed = 0, []


def check(condition, message, extra=None):
    global checks
    checks += 1
    if not condition:
        failed.append(message + (f" — {extra}" if extra is not None else ""))


# ── Правило одно и живёт в общем файле ──────────────────────────────
check("value(key, raw)" in helper, "общее правило показаний есть")
check("this.unit(key)" in helper, "единица берётся из справочника")
check('key === "авария_флаг"' in helper, "сигнал панели — «есть/нет», а не число")
check('=== "ч"' in helper and 'toLocaleString("ru-RU")' in helper,
      "моточасы — целые часы, без процентов и дробей")
check('minimumFractionDigits: 1' in helper, "дробная часть по-русски, через запятую")

# ── Страницы зовут общее правило, а не дописывают процент сами ──────
for name, text in pages.items():
    check("ACAISensors.value(" in text, f"{name}: зовёт общее правило")

analytics = pages["analytics.html"]
check("v.toFixed(1)+'%'" not in analytics,
      "«Аналитика» больше не дописывает процент ко всему подряд")
check("k.includes('проц') ? '%'" not in pages["reports.html"],
      "«Отчёты» не угадывают единицу по имени регистра")

# ── Цвет — только для загрузки ──────────────────────────────────────
check("shown.kind!=='percent'?'var(--text)'" in analytics,
      "частоту и часы не красят как «низкую загрузку»")

# ── Версия статики поднята ──────────────────────────────────────────
found = re.search(r"sensor-names\.js\?v=(\d+)", analytics)
check(found and int(found.group(1)) >= 3, "версия sensor-names.js поднята",
      found and found.group(1))

# ── Лишнее объяснение про фамилии убрано ────────────────────────────
xls = (STATIC / "xls-report.js").read_text(encoding="utf-8")
check("писали по-разному" not in xls,
      "сведение разных написаний фамилии больше не объясняется на экране")

print(f"Единицы показаний: проверок {checks}, сбоев {len(failed)}")
for item in failed:
    print("  -", item)
sys.exit(1 if failed else 0)
