"""
Выбор станка при новом обращении: по цехам, а не одним столбцом.

Нашёл владелец 28.09.2026: на странице «Разбор поломки» станки шли
подряд одним списком. У рабочего их два-три, и это незаметно, а у
мастера и главного инженера — сорок девять: чтобы дойти до печи, надо
было прокрутить всю массоподготовку и формовку.

Правило цеха должно быть ОДНО на всю систему. Оно уже есть в
«Обращениях» и в «Диагностике»: сначала участок (location), потом этап
(stage). Если завести здесь своё, страницы начнут раскладывать одни и
те же станки по-разному — а человек решит, что станок пропал.

Проверяется по исходникам: как выглядит список, в браузере видно на
снимках, а вот расхождение правил видно только так.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
chat_js = (ROOT / "frontend" / "static" / "chat.js").read_text(encoding="utf-8")
chat_css = (ROOT / "frontend" / "static" / "chat.css").read_text(encoding="utf-8")
chat_html = (ROOT / "frontend" / "templates" / "chat.html").read_text(encoding="utf-8")
cases_html = (ROOT / "frontend" / "templates" / "cases.html").read_text(encoding="utf-8")
diag_html = (ROOT / "frontend" / "templates" / "diagnostics.html").read_text(encoding="utf-8")

checks = 0
failed = []


def check(condition, message, extra=None):
    global checks
    checks += 1
    if not condition:
        failed.append(message + (f" — {extra}" if extra is not None else ""))


# ── Список станков разложен по цехам ────────────────────────────────
check("chatZoneOf" in chat_js, "у списка станков есть правило цеха")
check("chat-zone-head" in chat_js and "chat-zone-head" in chat_css,
      "заголовок цеха есть и в разметке, и в стилях")
check("chatEquipmentFind" in chat_js, "есть поиск по названию")
check("equipment.length <= 6" in chat_js,
      "когда станков мало, список не делится на цехи")

# ── Правило цеха одно на всю систему ────────────────────────────────
def zone_rule(text):
    """Из какого поля берётся цех: ищем пару location → stage."""
    found = re.findall(r"(location[\s\S]{0,80}?stage)", text)
    return [re.sub(r"\s+", " ", f) for f in found]


for name, text in (("чат", chat_js), ("обращения", cases_html), ("диагностика", diag_html)):
    rule = zone_rule(text)
    check(bool(rule), f"в «{name}» цех берётся из location, затем stage", rule)

check("'Другое'" not in chat_js and '"Другое"' not in chat_js,
      "пустой цех называется честно, а не «Другое»")
check("Цех не указан" in chat_js, "и это видно человеку")

# ── Версии статики подняты, иначе браузер возьмёт старое ────────────
for asset in ("chat.js", "chat.css"):
    version = re.search(rf"{re.escape(asset)}\?v=(\d+)", chat_html)
    check(version is not None, f"{asset} подключён с версией")

check(re.search(r"chat\.js\?v=(\d+)", chat_html).group(1) >= "62",
      "версия chat.js поднята после правки")
check(re.search(r"chat\.css\?v=(\d+)", chat_html).group(1) >= "11",
      "версия chat.css поднята после правки")

print(f"Выбор станка при обращении: проверок {checks}, сбоев {len(failed)}")
for item in failed:
    print("  -", item)
sys.exit(1 if failed else 0)
