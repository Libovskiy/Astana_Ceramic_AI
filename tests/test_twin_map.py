"""
Цифровой двойник завода: та же дверь, что у сводки, и ни одной
выдуманной цифры.

Двойник — не новый раздел, а развёрнутый вид карточки
«Производственная цепочка» на «Главной». Значит проверяются две вещи,
и обе обязательны:

  «не пускает лишних» — у кого нет «Главной», у того нет и двойника;

  парная проверка «пускает своих» — те же роли, что видят цепочку,
  открывают и двойника. Без неё первая проверка зелёная и на
  странице, закрытой вообще для всех.

Отдельно — честность показаний. Живых регистров у завода четыре:
загрузка двух бункеров и частоты двух питателей. Остальные участки
обязаны оставаться серыми с подписью «нет данных»: нарисовать на
печи или на упаковке правдоподобное число хуже, чем не рисовать
ничего.

Боевые данные не трогаются: живые запросы идут в песочнице на копии
базы, остальное читается из исходников.

Запуск (из корня проекта): python tests/test_twin_map.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from sandbox import Sandbox, check, finish  # ДО импорта backend

from backend.api.main import PAGE_ROLES

TWIN = "/twin"
TEMPLATE = (ROOT / "frontend" / "templates" / "twin_map.html").read_text(encoding="utf-8")
INDEX = (ROOT / "frontend" / "templates" / "index.html").read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────
# Права: один список со сводкой
# ─────────────────────────────────────────────────────────

check(
    "двойник и «Главная» ходят по одному списку ролей",
    PAGE_ROLES.get(TWIN) is PAGE_ROLES.get("/"),
    f"двойник={PAGE_ROLES.get(TWIN)}, главная={PAGE_ROLES.get('/')}",
)

sb = Sandbox()

for role in ("director", "chief_engineer", "production_chief"):
    person = sb.user(role)
    check(f"{role}: видит цепочку на «Главной»", person.get("/").status_code == 200)
    check(f"{role}: открывает двойника", person.get(TWIN).status_code == 200)

for role in ("worker", "mechanic", "lab_technician"):
    person = sb.user(role)
    check(f"{role}: «Главная» закрыта", person.get("/").status_code == 403)
    check(f"{role}: двойник закрыт", person.get(TWIN).status_code == 403)

from fastapi.testclient import TestClient

anon = TestClient(sb.app, follow_redirects=False).get(TWIN)
check(
    "без входа двойник не отдаётся",
    anon.status_code in (302, 307) and "/login" in anon.headers.get("location", ""),
    f"{anon.status_code} {anon.headers.get('location')}",
)

page = sb.user("director").get(TWIN).text
check("двойник: есть холст сцены", 'id="c"' in page)
check("двойник: есть список участков", 'id="rows"' in page and 'id="pins"' in page)
check("двойник: есть путь материала", 'id="steps"' in page)


# ─────────────────────────────────────────────────────────
# Цифры только настоящие
# ─────────────────────────────────────────────────────────

check(
    "страница открывается без чисел, а не с заготовками",
    "var LIVE={bunker1:null,bunker2:null,feeder1:null,feeder2:null" in TEMPLATE,
    "в исходнике артефакта стояли 88.6 / 82.0 / 32.0 / 8.0 — их показали бы как живые",
)

bound = set(re.findall(r"REG=\{[^}]*\}", TEMPLATE))
check(
    "привязаны те же четыре регистра, что на «Главной»",
    "'pl024_1_загрузка_проц'" in TEMPLATE and "'pl024_2_загрузка_проц'" in TEMPLATE
    and "'питатель_1_гц'" in TEMPLATE and "'питатель_2_гц'" in TEMPLATE,
    bound,
)

# Парная: участки без регистров так и помечены, а не закрашены зелёным.
states = set(re.findall(r"state:'(\w+)'", TEMPLATE))
check(
    "участки без показаний заведены как «нет данных»",
    states == {"nodata"},
    f"встречаются состояния: {sorted(states)}",
)
check(
    "и так подписаны",
    TEMPLATE.count("нет данных") >= 20,
    TEMPLATE.count("нет данных"),
)

check(
    "сбор стоит — чисел не показываем вовсе",
    "collection.ok" in TEMPLATE and "blank(" in TEMPLATE,
)

check(
    "имена берутся из справочника регистров",
    "ACAISensors" in TEMPLATE,
)

check(
    "условные места названы условными",
    TEMPLATE.count("условно") >= 2,
    TEMPLATE.count("условно"),
)


# ─────────────────────────────────────────────────────────
# Как встроен в сводку
# ─────────────────────────────────────────────────────────

check(
    "кнопка стоит в шапке «Производственной цепочки»",
    re.search(r'prod-map-header.*?id="twinExpand"', INDEX, re.S) is not None,
)

check(
    "сцена грузится только по нажатию",
    'id="twinFrame"' in INDEX
    and not re.search(r'id="twinFrame"[^>]*\ssrc=', INDEX)
    and "frame.src='/twin" in INDEX,
)

check(
    "закрытая сцена не держит видеокарту",
    "getElementById('twinFrame').removeAttribute('src')" in INDEX,
)

check(
    "свернуть можно мышью и с клавиатуры",
    "closeTwin()" in INDEX and "acai-twin-close" in INDEX,
)

# Двойник и карта линии не спорят, а ведут друг к другу.
check(
    "из двойника можно уйти в карту линии",
    "acai-twin-open-massa" in INDEX and "acai-twin-open-massa" in TEMPLATE,
)

check(
    "развёрнутый вид — оверлей, а не requestFullscreen",
    ".requestFullscreen(" not in INDEX
    and re.search(r"height:\s*100vh", TEMPLATE) is None,
)

check(
    "шрифты свои, а не из интернета",
    "fonts.googleapis.com" not in TEMPLATE and "/static/fonts.css" in TEMPLATE,
)

check(
    "тема берётся из выбора человека",
    "localStorage.getItem('acai_theme')" in TEMPLATE,
)

finish("Цифровой двойник завода")
