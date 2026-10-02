"""
3D-карта массаподготовки: та же дверь, что у блока с цифрами.

Карта — не новый раздел, а развёрнутый вид блока показаний на
«Главной». Значит проверяются две вещи, и обе обязательны:

  «не пускает лишних» — у кого нет «Главной», у того нет и карты;

  парная проверка «пускает своих» — те же роли, что видят блок с
  цифрами, открывают и карту. Без неё первая проверка зелёная и на
  странице, закрытой вообще для всех.

Отдельно — кнопка «Развернуть». Она живёт в шапке карточки, а
показания пишутся в тело: иначе первый же «нет данных» (сбор стоит,
расширение не на связи) стирал бы вход в карту вместе с цифрами. На
прежнем коде, где показания затирали всю карточку, эта проверка
падает.

Боевые данные не трогаются: живые запросы идут в песочнице на копии
базы, остальное читается из исходников.

Запуск (из корня проекта): python tests/test_massaprep_map.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from sandbox import Sandbox, check, finish  # ДО импорта backend

from backend.api.main import PAGE_ROLES

MAP = "/massaprep/3d"

INDEX = (ROOT / "frontend" / "templates" / "index.html").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "frontend" / "templates" / "massaprep_map.html").read_text(encoding="utf-8")
ICONS = (ROOT / "frontend" / "static" / "icons.js").read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────
# Права: один список с «Главной»
# ─────────────────────────────────────────────────────────

check(
    "карта и «Главная» ходят по одному списку ролей",
    PAGE_ROLES.get(MAP) is PAGE_ROLES.get("/"),
    f"карта={PAGE_ROLES.get(MAP)}, главная={PAGE_ROLES.get('/')}",
)

sb = Sandbox()

# Кому «Главная» открыта, тому открыта и карта.
for role in ("director", "production_chief", "analyst"):
    person = sb.user(role)
    home = person.get("/")
    card = person.get(MAP)
    check(
        f"{role}: видит блок с цифрами",
        home.status_code == 200,
        f"«Главная» ответила {home.status_code}",
    )
    check(
        f"{role}: открывает карту",
        card.status_code == 200,
        f"карта ответила {card.status_code}",
    )

# Кому «Главная» закрыта, тому закрыта и карта: иначе прямой адрес
# стал бы обходной дверью мимо прав.
for role in ("worker", "mechanic", "electrician", "lab_technician"):
    person = sb.user(role)
    home = person.get("/")
    card = person.get(MAP)
    check(
        f"{role}: блок с цифрами закрыт",
        home.status_code == 403,
        f"«Главная» ответила {home.status_code}",
    )
    check(
        f"{role}: карта закрыта",
        card.status_code == 403,
        f"карта ответила {card.status_code}",
    )

from fastapi.testclient import TestClient

anon = TestClient(sb.app, follow_redirects=False).get(MAP)
check(
    "без входа карта не отдаётся",
    anon.status_code in (302, 307) and "/login" in anon.headers.get("location", ""),
    f"{anon.status_code} {anon.headers.get('location')}",
)

page = sb.user("director").get(MAP).text
check("карта: есть холст сцены", 'id="c"' in page)
check("карта: Three.js подключён", "three.min.js" in page)
check("карта: есть переключатель вида", 'id="btnTop"' in page and 'id="btn3d"' in page)
check("карта: есть карточка статуса узла", 'id="detailPanel"' in page)


# ─────────────────────────────────────────────────────────
# Свёрнутый вид: цифры прежние, кнопка не исчезает
# ─────────────────────────────────────────────────────────

check(
    "на «Главной» есть кнопка «Развернуть»",
    'id="massaExpand"' in INDEX and "openMassaMap()" in INDEX,
)

check(
    "кнопка стоит в шапке карточки, а не среди показаний",
    re.search(r'class="ss-head".*?id="massaExpand"', INDEX, re.S) is not None,
)

check(
    "показания пишутся в тело карточки",
    INDEX.count("getElementById('sensorStripBody').innerHTML") == 2,
    f"нашлось {INDEX.count(chr(39) + 'sensorStripBody' + chr(39))}",
)

# Парная: на прежнем коде показания затирали всю карточку целиком —
# вместе с кнопкой. Такого присваивания остаться не должно.
check(
    "показания не затирают карточку целиком",
    "getElementById('sensorStrip').innerHTML" not in INDEX,
    "«нет данных» снова стёр бы кнопку «Развернуть»",
)

check(
    "источник показаний не тронут",
    "/api/sensors/live" in INDEX and "ACAISensors.health()" in INDEX,
)

check(
    "сцена грузится только по нажатию",
    'id="massaFrame"' in INDEX
    and not re.search(r'id="massaFrame"[^>]*\ssrc=', INDEX)
    and "frame.src='/massaprep/3d" in INDEX,
    "iframe с адресом прямо в разметке тянул бы Three.js всем подряд",
)

check(
    "свернуть можно и мышью, и с клавиатуры",
    "closeMassaMap()" in INDEX and "'Escape'" in INDEX and "acai-massaprep-close" in INDEX,
)

check(
    "закрытая карта не держит видеокарту",
    "removeAttribute('src')" in INDEX,
)


# ─────────────────────────────────────────────────────────
# На схеме — заглушки, а не выдуманные показания
# ─────────────────────────────────────────────────────────

states = set(re.findall(r"state:'(\w+)'", TEMPLATE))
check(
    "все узлы помечены «нет данных»",
    states == {"nodata"},
    f"встречаются состояния: {sorted(states)}",
)

check(
    "у узлов написано, почему пусто",
    TEMPLATE.count("регистр не назначен") >= 10,
    f"нашлось {TEMPLATE.count('регистр не назначен')}",
)

check(
    "библиотека грузится не блокирующим тегом",
    "<script src=" not in TEMPLATE and "el.src = CDN" in TEMPLATE,
    "блокирующий <script src> оставлял бы пустой экран, пока CDN молчит",
)

check(
    "обрыв и молчание CDN обработаны",
    "el.onerror" in TEMPLATE and "setTimeout" in TEMPLATE and "WAIT_MS" in TEMPLATE,
)

check(
    "есть что показать вместо схемы",
    'id="loadFail"' in TEMPLATE and 'id="failRetry"' in TEMPLATE,
)

check(
    "выход клавишей не зависит от сцены",
    TEMPLATE.index("acai-massaprep-close") > TEMPLATE.index("function startMap()"),
    "обработчик Esc внутри startMap — из нерабочей карты не выйти",
)

check(
    "развёрнутый вид — оверлей, а не requestFullscreen",
    ".requestFullscreen(" not in INDEX
    and re.search(r"height:\s*100vh", INDEX) is None
    and re.search(r"height:\s*100vh", TEMPLATE) is None,
    "в мобильном Safari fullscreen у iframe и 100vh ненадёжны",
)

check(
    "тема берётся из выбора человека, а не из системы",
    "localStorage.getItem('acai_theme')" in TEMPLATE
    and "prefers-color-scheme" not in TEMPLATE,
)


# ─────────────────────────────────────────────────────────
# Значок куба: добавлен и роздан
# ─────────────────────────────────────────────────────────

check("значок куба есть в наборе", re.search(r"^\s*cube:", ICONS, re.M) is not None)

versions = set()
for tpl in (ROOT / "frontend" / "templates").glob("*.html"):
    versions.update(re.findall(r"icons\.js\?v=(\d+)", tpl.read_text(encoding="utf-8")))

check(
    "версия icons.js у всех страниц одна",
    len(versions) == 1,
    f"встречаются версии {sorted(versions)} — у части страниц значок куба не появится",
)

finish("3D-карта массаподготовки")
