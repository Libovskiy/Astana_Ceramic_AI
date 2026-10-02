"""
3D-карта массаподготовки: показания с панели ложатся на узлы верно.

Привязаны четыре регистра — те, что назвал владелец 02.10.2026:
загрузка PL024-1/2 это бункеры, частоты питателей — песок и глина.
Проверяются две вещи, и обе обязательны:

  «показывает по правде» — узел красится по тем же порогам, что и
  «Главная»: загрузка ниже 50 % критична, ниже 80 % — внимание,
  нулевая частота это «стоит», а не поломка и не «нет данных»;

  парная проверка «не выдумывает» — узлы без регистра остаются серыми
  с надписью «регистр не назначен», а когда сбор стоит, с карты
  пропадают ВСЕ числа. Без этой пары первая проверка зелёная и на
  карте, которая красит всё зелёным всегда.

Браузер настоящий: сцену строит Three.js, и состояние узлов видно
только после отрисовки. Сервер не нужен — страница отдаётся файловым
сервером, а три ответа панели подменяются. Боевые данные не
затрагиваются вовсе.

Запуск (из корня проекта): python tests/test_massaprep_live.py
"""

import http.server
import json
import socketserver
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "frontend" / "templates" / "massaprep_map.html"

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("ПРОПУЩЕНО: playwright не установлен, браузерная проверка не шла")
    sys.exit(0)


def three_js():
    local = ROOT / "theme" / "three.min.js"
    if local.exists():
        return local.read_text(encoding="utf-8")
    try:
        import urllib.request
        src = urllib.request.urlopen(
            "https://cdn.jsdelivr.net/npm/three@0.128.0/build/three.min.js",
            timeout=20).read().decode("utf-8")
    except Exception:
        return None
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(src, encoding="utf-8")
    return src


LIBRARY = three_js()
if not LIBRARY:
    print("ПРОПУЩЕНО: нет theme/three.min.js и нет интернета — сцену не построить")
    sys.exit(0)


class Quiet(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(PAGE.parent), **kw)

    def log_message(self, *a):
        pass


httpd = socketserver.TCPServer(("127.0.0.1", 0), Quiet)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{httpd.server_address[1]}/{PAGE.name}"

passed, failed = [], []


def check(name, condition, detail=""):
    if condition:
        passed.append(name)
        print(f"  OK   {name}")
    else:
        failed.append(f"{name}: {detail}")
        print(f"  СБОЙ {name}  {str(detail)[:300]}")


NOW = "2026-10-02T13:40:00"

REGISTERS = {"success": True, "registers": [
    {"register": "pl024_1_загрузка_проц", "title": "Загрузка бункера 1 (PL024-1)",
     "short_title": "Бункер 1", "unit": "%", "state": "live"},
    {"register": "pl024_2_загрузка_проц", "title": "Загрузка бункера 2 (PL024-2)",
     "short_title": "Бункер 2", "unit": "%", "state": "live"},
    {"register": "питатель_1_гц", "title": "Частота питателя №1 (глина)",
     "short_title": "Питатель №1 — Глина", "unit": "Гц", "state": "live"},
    {"register": "питатель_2_гц", "title": "Частота питателя №2 (песок)",
     "short_title": "Питатель №2 — Песок", "unit": "Гц", "state": "live"},
    {"register": "конвейер_1_гц", "title": "Частота конвейера №1",
     "short_title": "Конв. 1", "unit": "Гц", "state": "live"},
    {"register": "конвейер_2_гц", "title": "Частота конвейера №2",
     "short_title": "Конв. 2", "unit": "Гц", "state": "live"},
    {"register": "конвейер_5_гц", "title": "Частота конвейера №5",
     "short_title": "Конв. 5", "unit": "Гц", "state": "live"},
    {"register": "авария_флаг", "title": "Сигнал панели (регистр 1658)",
     "short_title": "Сигнал панели", "unit": "", "state": "live"},
]}

LIVE = {
    "pl024_1_загрузка_проц": {"value": "82.4", "at": NOW},   # норма
    "pl024_2_загрузка_проц": {"value": "47.1", "at": NOW},   # критично
    "питатель_1_гц": {"value": "38.2", "at": NOW},           # работает
    "питатель_2_гц": {"value": "0", "at": NOW},              # стоит
    "конвейер_1_гц": {"value": "32.0", "at": NOW},   # идёт с питателем глины
    "конвейер_5_гц": {"value": "8.0", "at": NOW},    # идёт с питателем песка
    "конвейер_2_гц": {"value": "21.1", "at": NOW},   # место на линии неизвестно
    "авария_флаг": {"value": "0", "at": NOW},
}


SENSOR_NAMES = (ROOT / "frontend" / "static" / "sensor-names.js").read_text(encoding="utf-8")


def open_map(browser, health, live=LIVE, viewport=None):
    page = browser.new_page(viewport=viewport) if viewport else browser.new_page()
    # Справочник имён — настоящий файл системы: проверяем тот же путь,
    # которым страница ходит на сервере.
    page.route("**/static/sensor-names.js", lambda route: route.fulfill(
        status=200, content_type="application/javascript", body=SENSOR_NAMES))
    page.route("**/three*.js", lambda route: route.fulfill(
        status=200, content_type="application/javascript", body=LIBRARY))
    page.route("**/api/sensor-registers", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(REGISTERS)))
    page.route("**/api/sensors/health", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(health)))
    page.route("**/api/sensors/live", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(live)))
    page.goto(URL)
    page.wait_for_selector("body[data-live-ready='1']", timeout=20000)
    return page


def states(page):
    return page.evaluate(
        """() => Object.fromEntries((window.acaiMapStations || []).map(s =>
             [s.name, {state: s.state, status: s.statusText,
                       chip: s.label.textContent, bound: !!s.register}]))""")


try:
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:
            print(f"ПРОПУЩЕНО: Chromium не запускается ({str(exc)[:120]})")
            sys.exit(0)

        # ── 1. сбор идёт: показания ложатся на узлы ──────────────
        page = open_map(browser, {"ok": True, "state": "live", "last_data_at": NOW})
        got = states(page)

        check("узлов на схеме десять", len(got) == 10, sorted(got))
        check("привязаны ровно четыре",
              sum(1 for v in got.values() if v["bound"]) == 4,
              [k for k, v in got.items() if v["bound"]])

        check("бункер 82,4 % — норма", got["Бункер 1"]["state"] == "ok", got.get("Бункер 1"))
        check("бункер 47,1 % — критично", got["Бункер 2"]["state"] == "crit", got.get("Бункер 2"))
        check("питатель 38,2 Гц — работает",
              got["Питатель №1 — Глина"]["state"] == "ok", got.get("Питатель №1 — Глина"))
        check("нулевая частота — «стоит», а не поломка",
              got["Питатель №2 — Песок"]["state"] == "idle"
              and "стоит" in got["Питатель №2 — Песок"]["chip"].lower(),
              got.get("Питатель №2 — Песок"))

        check("число видно прямо на подписи",
              "82,4" in got["Бункер 1"]["chip"], got["Бункер 1"]["chip"])
        check("в статусе сказано, когда снято",
              "снято в" in got["Бункер 1"]["status"], got["Бункер 1"]["status"])

        # Парная: узлы без регистра не притворяются работающими.
        for name in ("Дробилка ДТЕ117", "PL 601", "Камневыделитель",
                     "СМК-102", "УСМ-40", "СМК 126"):
            check(f"{name}: регистра нет — и цифр нет",
                  got[name]["state"] == "nodata" and not got[name]["bound"]
                  and got[name]["chip"].strip() == name
                  and "не назначен" in got[name]["status"],
                  got[name])

        # ── частота там, где она относится к делу ────────────────
        belts = page.locator(".belt").evaluate_all(
            """els => els.map(e => { const r = e.getBoundingClientRect();
                 return {t: e.textContent.trim(), shown: r.width > 0,
                         l: r.left, r: r.right, top: r.top, bot: r.bottom}; })""")
        shown = [b["t"] for b in belts if b["shown"]]

        check("частоты стоят на самих лентах", len(shown) == 2, shown)
        check("на ленте глины — 32,0 Гц", any("32,0" in t for t in shown), shown)
        check("на ленте песка — 8,0 Гц", any("8,0" in t for t in shown), shown)
        check("и помечены как неподтверждённые",
              all("?" in t for t in shown), shown)

        chips = page.locator(".chip").evaluate_all(
            """els => els.map(e => { const r = e.getBoundingClientRect();
                 return {t: e.textContent.trim(), l: r.left, r: r.right,
                         top: r.top, bot: r.bottom}; })""")
        clash = [(b["t"], c["t"]) for b in belts if b["shown"] for c in chips
                 if b["l"] < c["r"] and c["l"] < b["r"]
                 and b["top"] < c["bot"] and c["top"] < b["bot"]]
        check("подписи лент не налезают на подписи станций", not clash, clash)

        strip = page.locator("#liveStrip").inner_text()
        # Парная: переехавшие ушли со строки, а те, чьё место неизвестно,
        # остались — молча пропасть с экрана они не должны.
        check("переехавшие цифры ушли из строки внизу",
              "Конв. 1" not in strip and "Конв. 5" not in strip, strip)
        check("остальные конвейеры внизу остались",
              "Конв. 2" in strip and "21,1" in strip, strip)
        check("и сказано, почему они не на схеме",
              "без места на схеме" in strip, strip)
        check("сигнал панели и время на месте",
              "Сигнал панели" in strip and "снято в" in strip, strip)
        page.close()

        # ── 2. парная: сбор стоит — на карте ни одного числа ─────
        page = open_map(browser, {"ok": False, "state": "collector",
                                  "since": NOW, "last_data_at": NOW})
        got = states(page)
        check("сбор стоит: все узлы «нет данных»",
              all(v["state"] == "nodata" for v in got.values()),
              {k: v["state"] for k, v in got.items() if v["state"] != "nodata"})
        # В имени узла цифра есть и своя («Бункер 1»), поэтому смотрим на
        # приписку с показанием: её быть не должно.
        check("сбор стоит: показаний на подписях нет",
              all(v["chip"].strip() == name for name, v in got.items()),
              {n: v["chip"] for n, v in got.items() if v["chip"].strip() != n})
        check("сбор стоит: на лентах тоже пусто",
              not any(page.locator(".belt").all_inner_texts()),
              page.locator(".belt").all_inner_texts())
        check("сбор стоит: сказано, с какого времени",
              "13:40" in page.locator("#liveStrip").inner_text(),
              page.locator("#liveStrip").inner_text())
        page.close()

        # ── 3. телефон: подписи читаются ────────────────────────
        # На узкой ширине узлы сходятся в одну точку. Подписи налезали
        # друг на друга, а крайние уезжали за край: «PL 601» читался
        # как «01».
        page = open_map(browser, {"ok": True, "state": "live", "last_data_at": NOW},
                        viewport={"width": 390, "height": 844})
        boxes = page.locator(".chip").evaluate_all(
            """els => els.map(e => { const r = e.getBoundingClientRect();
                 return {t: e.textContent.trim(), l: r.left, r: r.right,
                         top: r.top, bot: r.bottom}; })""")

        outside = [b["t"] for b in boxes if b["l"] < 0 or b["r"] > 390]
        check("на телефоне подписи не уезжают за край", not outside, outside)

        overlaps = []
        for i, one in enumerate(boxes):
            for other in boxes[i + 1:]:
                if (one["l"] < other["r"] and other["l"] < one["r"]
                        and one["top"] < other["bot"] and other["top"] < one["bot"]):
                    overlaps.append((one["t"], other["t"]))
        check("на телефоне подписи не налезают друг на друга", not overlaps, overlaps)

        # Парная: развели — но не растеряли, видны все десять.
        check("и все узлы подписаны", len(boxes) == 10, len(boxes))
        page.close()
        browser.close()
finally:
    httpd.shutdown()

print(f"\nПоказания на карте: проверок {len(passed) + len(failed)}, сбоев {len(failed)}")
for item in failed:
    print("  -", item[:400])
sys.exit(1 if failed else 0)
