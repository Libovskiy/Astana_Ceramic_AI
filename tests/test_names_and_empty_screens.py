"""
Экраны не должны врать названиями и не должны оставаться пустыми.

Собрано по обходу сайта по ролям 02.10.2026. Проверяются те места,
где человек видел не то, что есть на самом деле:

  должность показывалась системным словом («production_chief»), один
  и тот же человек звался «Гл. электрик» и «Гл. энергетик», участок —
  «Массоподготовка» и «Массаподготовка»;

  у рабочего на «Производстве» вечно висела заглушка «Считаю выпуск…»,
  потому что отчёт за смену он больше не ведёт и срабатывал тихий
  выход из обработчика;

  свёрнутая «Очередь работ» была без счётчика и выглядела так же, как
  непосчитанная.

Парные проверки — рядом: мало убрать «Гл. электрик», надо чтобы
осталось «Гл. энергетик», и мало позвать обработчик с null, надо чтобы
он при этом что-то написал.

Боевые данные не трогаются: читаются только исходники.

Запуск (из корня проекта): python tests/test_names_and_empty_screens.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.api.main import ROLE_LABELS as SERVER_ROLES
from backend.services.production_report_import import SECTION_TITLES

TPL = ROOT / "frontend" / "templates"
STATIC = ROOT / "frontend" / "static"
SERVICES = ROOT / "backend" / "services"

SETTINGS = (TPL / "settings.html").read_text(encoding="utf-8")
PRODUCTION = (TPL / "production.html").read_text(encoding="utf-8")
TECHNOLOG = (TPL / "technolog.html").read_text(encoding="utf-8")
SHIFT_JS = (STATIC / "shift-report.js").read_text(encoding="utf-8")
EQUIP_JS = (STATIC / "equipment.js").read_text(encoding="utf-8")
IMPORT_PY = (SERVICES / "production_import_service.py").read_text(encoding="utf-8")

passed, failed = [], []


def check(name, condition, detail=""):
    if condition:
        passed.append(name)
        print(f"  OK   {name}")
    else:
        failed.append(f"{name}: {detail}")
        print(f"  СБОЙ {name}  {str(detail)[:300]}")


# ─────────────────────────────────────────────────────────
# Должности: ни одного системного слова на экране
# ─────────────────────────────────────────────────────────

block = re.search(r"const ROLE_LABELS=\{(.*?)\};", SETTINGS, re.S)
page_roles = dict(re.findall(r"(\w+):'([^']+)'", block.group(1))) if block else {}

check("список должностей на странице найден", len(page_roles) > 5, len(page_roles))

missing = sorted(set(SERVER_ROLES) - set(page_roles))
check(
    "каждая роль с сервера подписана по-русски",
    not missing,
    f"в «Настройках» нет: {missing} — в списке людей встанет системное слово",
)

differ = {role: (SERVER_ROLES[role], page_roles[role])
          for role in SERVER_ROLES if role in page_roles
          and SERVER_ROLES[role] != page_roles[role]}
check(
    "подписи совпадают с серверными",
    not differ,
    f"расходятся: {differ}",
)

# Парная: «Гл. электрик» убран, но должность не исчезла.
check(
    "«Гл. электрик» больше не встречается",
    "Гл. электрик" not in SETTINGS,
    "один человек назывался двумя разными должностями",
)
check(
    "а «Гл. энергетик» на месте",
    page_roles.get("chief_electrician") == "Гл. энергетик",
    page_roles.get("chief_electrician"),
)


# ─────────────────────────────────────────────────────────
# Участок: одно написание
# ─────────────────────────────────────────────────────────

check(
    "подпись участка — «Массаподготовка»",
    SECTION_TITLES["massa"] == "Массаподготовка",
    SECTION_TITLES["massa"],
)

wrong = []
for path in list(SERVICES.glob("*.py")) + list(TPL.glob("*.html")):
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if "Массоподготовка" in line and "массоподготов" not in line.lower().replace("Массоподготовка".lower(), ""):
            # строки с распознаванием текста из файла оставляем: там
            # ищут корень слова, как его пишет начальник производства
            if line.strip().startswith("#") or line.strip().startswith("//"):
                continue
            wrong.append(f"{path.name}: {line.strip()[:70]}")
check(
    "«Массоподготовки» в подписях не осталось",
    not wrong,
    wrong,
)

check(
    "подпись участка берётся по ключу, а не из старой строки",
    "GROUP BY section, section_title" not in IMPORT_PY
    and IMPORT_PY.count('SECTION_TITLES.get(') >= 2,
    "строки, загруженные до переименования, покажут старое слово",
)


# ─────────────────────────────────────────────────────────
# Пустые экраны: заглушка не остаётся навсегда
# ─────────────────────────────────────────────────────────

check(
    "страница узнаёт, что отчёта на экране нет",
    "srNotify(null)" in SHIFT_JS,
    "без этого вывод рабочего остаётся на «Считаю выпуск…»",
)

check(
    "обработчик не выходит молча",
    "if (!report) return;" not in PRODUCTION,
)

# Парная: он не просто не выходит — он пишет человеку, что делать.
check(
    "и пишет, что отчёт не открыт",
    "Отчёт за смену не открыт" in PRODUCTION
    and "Отчёт ведёт начальник смены" in PRODUCTION,
)

check(
    "счётчик раздела показывает ноль числом",
    'counter.textContent = String(' in EQUIP_JS
    and 'counter.textContent = shown ? String(shown) : ""' not in EQUIP_JS,
    "свёрнутый раздел без числа не отличить от непосчитанного",
)


# ─────────────────────────────────────────────────────────
# «Технолог»: три разные беды — три разных текста
# ─────────────────────────────────────────────────────────

for what, mark in (
    ("сбор остановлен", "Сбор остановлен"),
    ("панель молчит", "не приходит ни одного показания"),
    ("нечего сверять: нет привязки", "ни один параметр к ним не привязан"),
):
    check(f"«Технолог» различает: {what}", mark in TECHNOLOG, mark)

check(
    "старый общий текст убран",
    "панель WebHMI не отдаёт данные — режим сверять не с чем" not in TECHNOLOG,
    "две разные беды снова показываются одной строкой",
)

print(f"\nНазвания и пустые экраны: проверок {len(passed) + len(failed)}, сбоев {len(failed)}")
for item in failed:
    print("  -", item[:400])
sys.exit(1 if failed else 0)
