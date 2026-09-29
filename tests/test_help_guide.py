"""
Руководство показывает каждому только его разделы.

Смысл раздела в том, что оператор не листает руководство директора.
Значит проверять надо две вещи, и обе обязательны:

  «не показывает лишнего» — у рабочего нет разделов руководства и
  журнала действий;

  парная проверка «показывает нужное» — те же разделы есть у тех, кому
  они адресованы. Без неё первый тест зелёный и на пустом ответе: отбор,
  который не отдаёт ничего, «лишнего» тоже не показывает.

Отдельно проверяется, что отбор делает сервер, а не разметка: в шаблоне
не должно быть блоков, спрятанных стилем, — их видно в исходном коде
страницы, и запрет становится видимостью запрета.

Боевые данные не трогаются: читаются только исходники и чистые функции.

Запуск (из корня проекта): python tests/test_help_guide.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.services.help_service import ALL_ROLES, GUIDE, sections_for

passed, failed = [], []


def check(name, condition, detail=""):
    if condition:
        passed.append(name)
    else:
        failed.append((name, detail))


def ids(role):
    return {section["id"] for section in sections_for(role)}


# ─────────────────────────────────────────────────────────
# Справочник исправен
# ─────────────────────────────────────────────────────────

check("разделы есть", len(GUIDE) >= 10, f"всего {len(GUIDE)}")

check(
    "id разделов не повторяются",
    len({section["id"] for section in GUIDE}) == len(GUIDE),
)

for section in GUIDE:
    roles = section["roles"]
    check(
        f"{section['id']}: роли известны",
        roles == "*" or (roles and all(role in ALL_ROLES for role in roles)),
        f"{roles}",
    )
    check(
        f"{section['id']}: есть текст",
        bool(section.get("steps") or section.get("notes")),
    )

# ─────────────────────────────────────────────────────────
# Не показывает лишнего
# ─────────────────────────────────────────────────────────

HEADS_ONLY = "help-admin"        # журнал действий и настройки
SERVICE_ONLY = "help-service"    # отметка работ по ТО
ACCEPT_ONLY = "help-accept"      # приём работ по ТО
LAB_ONLY = "help-lab"            # лаборатория

check("рабочий не видит журнал и настройки", HEADS_ONLY not in ids("worker"))
check("рабочий не видит отметку ТО", SERVICE_ONLY not in ids("worker"))
check("рабочий не видит приём работ", ACCEPT_ONLY not in ids("worker"))
check("лаборант не видит отметку ТО", SERVICE_ONLY not in ids("lab_technician"))
check("механик не принимает работы сам", ACCEPT_ONLY not in ids("mechanic"))
check("механик не видит лабораторию", LAB_ONLY not in ids("mechanic"))

# ─────────────────────────────────────────────────────────
# Парная проверка: показывает нужное
# ─────────────────────────────────────────────────────────
# Эти проверки падают на отборе, который отдаёт слишком мало, — и
# именно поэтому проверки выше что-то значат.

check("директор видит журнал и настройки", HEADS_ONLY in ids("director"))
check("механик видит отметку ТО", SERVICE_ONLY in ids("mechanic"))
check("гл. механик принимает работы", ACCEPT_ONLY in ids("chief_mechanic"))
check("лаборант видит лабораторию", LAB_ONLY in ids("lab_technician"))

# Общие разделы — у всех, включая рабочего: вход, экран, поломка.
COMMON = {section["id"] for section in GUIDE if section["roles"] == "*"}
check("общих разделов несколько", len(COMMON) >= 5, f"{len(COMMON)}")

for role in ALL_ROLES:
    got = ids(role)
    check(f"{role}: общие разделы на месте", COMMON <= got,
          f"не хватает: {', '.join(sorted(COMMON - got))}")
    check(f"{role}: что-то показано", len(got) >= len(COMMON), f"{len(got)}")

check("admin видит всё", len(ids("admin")) == len(GUIDE))

# Роль без прав (пустая строка, сломанная сессия) не должна получать
# ничего сверх общего.
check("без роли — только общее", ids("") == COMMON,
      f"лишнее: {', '.join(sorted(ids('') - COMMON))}")

# ─────────────────────────────────────────────────────────
# Отбор на сервере, а не в разметке
# ─────────────────────────────────────────────────────────

TEMPLATE = (ROOT / "frontend" / "templates" / "help.html").read_text()

check(
    "шаблон перебирает то, что дал сервер",
    "for section in sections" in TEMPLATE,
)

check(
    "в шаблоне нет разделов, спрятанных стилем",
    "display:none" not in TEMPLATE.replace(" ", ""),
    "спрятанный блок видно в исходном коде страницы",
)

for section in GUIDE:
    if section["roles"] == "*":
        continue
    first = (section.get("steps") or section.get("notes"))[0][:24]
    check(
        f"{section['id']}: текст не вшит в шаблон",
        first not in TEMPLATE,
    )

# Страница должна быть заявлена открытой всем: закрывать её по роли
# незачем, содержимое уже отобрано.
MAIN_PY = (ROOT / "backend" / "api" / "main.py").read_text()
check('"/help" открыт всем на сервере', '"/help": "*"' in MAIN_PY)

LAYOUT_JS = (ROOT / "frontend" / "static" / "acai_layout.js").read_text()
check("ссылка на руководство есть в меню", "'/help'" in LAYOUT_JS)

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
    sys.exit(1)

print("Руководство показывает каждому только его разделы.")
