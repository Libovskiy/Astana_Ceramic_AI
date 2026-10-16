"""
Круг вагонеток идёт и не рвётся.

На заводе это бесконечная петля: формовка грузит сырец → трансбордер 1
ставит вагонетку на сушилку → трансбордер 2 сзади перетаскивает её из
сушилки в печь → трансбордер 1 забирает из печи на упаковку → после
разгрузки трансбордер 3 возвращает пустую вагонетку под формовку.
Остановка здесь — это простой, а простой стоит денег, поэтому круг на
схеме должен идти сам и не застревать.

Проверяется настоящим браузером, по тому, что видно на экране:

  «круг идёт» — за десять секунд вагонетки сдвинулись, тележки
  трансбордеров ходят по ямам, никто не застрял навсегда;

  парная проверка «не едут сквозь друг друга» — на одном трансбордере
  в один момент не больше одной вагонетки: если тележка занята,
  следующая ждёт. Без этой пары первая проверка зелёная и у схемы, где
  вагонетки просто пролетают одна через другую.

Боевые данные не трогаются: страница отдаётся файловым сервером,
ответы сервера подменяются пустыми.

Запуск (из корня проекта): python tests/test_plant_cycle.py
"""

import http.server
import socketserver
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TPL = ROOT / "frontend" / "templates"

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("ПРОПУЩЕНО: playwright не установлен, браузерная проверка не шла")
    sys.exit(0)

THREE = ROOT / "frontend" / "static" / "vendor" / "three-0.128.0.min.js"
ORBIT = ROOT / "frontend" / "static" / "vendor" / "three-0.128.0-OrbitControls.js"
if not THREE.exists():
    print("ПРОПУЩЕНО: нет местной копии Three.js")
    sys.exit(0)


class Quiet(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def log_message(self, *a):
        pass


httpd = socketserver.TCPServer(("127.0.0.1", 0), Quiet)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{httpd.server_address[1]}/frontend/templates/plant_3d.html"

passed, failed = [], []


def check(name, condition, detail=""):
    if condition:
        passed.append(name)
        print(f"  OK   {name}")
    else:
        failed.append(f"{name}: {detail}")
        print(f"  СБОЙ {name}  {str(detail)[:300]}")


try:
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:
            print(f"ПРОПУЩЕНО: Chromium не запускается ({str(exc)[:120]})")
            sys.exit(0)

        page = browser.new_page(viewport={"width": 1280, "height": 900})
        # Страница — часть сайта: ей нужны стили, меню и ответы сервера.
        # Отдаём файлы как есть, ответы подменяем пустыми: проверяем
        # сцену, а не данные.
        page.route("**/static/**", lambda route: route.continue_(
            url=route.request.url.replace("/static/", "/frontend/static/")))
        page.route("**/api/**", lambda route: route.fulfill(
            status=200, content_type="application/json", body='{"success":true,"groups":[],"templates":{}}'))
        page.goto(URL)
        page.wait_for_function("() => window.acaiPlantCycle", timeout=30000)
        page.wait_for_timeout(2000)

        first = page.evaluate("() => window.acaiPlantCycle.wagons()")
        tb_first = page.evaluate("() => window.acaiPlantCycle.transfers()")
        cycle = page.evaluate("() => window.acaiPlantCycle.cycle")

        check("вагонетки на схеме есть", len(first) >= 5, len(first))
        check("круг длиннее минуты", cycle > 60, cycle)
        check("трансбордеров три", sorted(tb_first) == ["back", "front", "ret"], tb_first)

        # ── круг идёт ────────────────────────────────────────────
        page.wait_for_timeout(10000)
        second = page.evaluate("() => window.acaiPlantCycle.wagons()")
        tb_second = page.evaluate("() => window.acaiPlantCycle.transfers()")

        moved = sum(1 for a, b in zip(first, second)
                    if abs(a["x"] - b["x"]) > .2 or abs(a["z"] - b["z"]) > .2)
        check("за десять секунд вагонетки сдвинулись", moved >= len(first) - 2,
              f"сдвинулось {moved} из {len(first)}")

        # Стоять можно только по делу: под загрузкой, под разгрузкой
        # или в очереди к занятому трансбордеру.
        stuck = [a for a, b in zip(first, second)
                 if a == b and not a["wait"] and not a["stand"]]
        check("никто не стоит без причины", not stuck, stuck[:2])

        check("тележки трансбордеров ходят",
              any(abs(tb_first[k] - tb_second[k]) > .2 for k in tb_first),
              {"было": tb_first, "стало": tb_second})

        # ── парная: на одной тележке не двое ─────────────────────
        clash = []
        for _ in range(12):
            now = page.evaluate("() => window.acaiPlantCycle.wagons()")
            busy = {}
            for w in now:
                if not w["tb"]:
                    continue
                busy[w["tb"]] = busy.get(w["tb"], 0) + 1
            for tb, n in busy.items():
                if n > 1:
                    clash.append((tb, n))
            page.wait_for_timeout(900)
        check("на трансбордере в один момент одна вагонетка", not clash, clash[:3])

        # ── и груз меняется по дороге ────────────────────────────
        loads = set()
        for _ in range(10):
            loads.update(w["load"] for w in page.evaluate("() => window.acaiPlantCycle.wagons()"))
            page.wait_for_timeout(1200)
        check("на вагонетках и сырец, и обожжённый, и пусто",
              {"raw", "fired", "empty"} <= loads, sorted(loads))

        page.close()
        browser.close()
finally:
    httpd.shutdown()

print(f"\nКруг вагонеток: проверок {len(passed) + len(failed)}, сбоев {len(failed)}")
for item in failed:
    print("  -", item[:400])
sys.exit(1 if failed else 0)
