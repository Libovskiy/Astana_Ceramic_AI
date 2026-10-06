"""
Трёхмерные схемы без интернета: вместо пустого экрана — объяснение.

Схем две: карта линии массаподготовки и цифровой двойник завода. Обе
рисует Three.js, она подгружается из интернета, а на заводском
компьютере его может не быть вовсе. Проверяется настоящим браузером,
с оборванной загрузкой библиотеки:

  «не висит пустым» — страница нарисована, видно, что случилось, и
  есть «Повторить»; выйти клавишей можно даже из нерабочей схемы;

  парная проверка «не ругается зря» — когда библиотека доступна
  (подсовываем её локально), сообщения об обрыве нет, а сцена
  строится. Без этой пары первая проверка зелёная и на странице,
  которая ругается всегда.

Браузер нужен настоящий: ошибка загрузки скрипта в исходниках не
видна. Если playwright или Chromium не установлены (сервер), проверка
честно печатает, что пропущена, и не притворяется пройденной.

Запуск (из корня проекта): python tests/test_maps_offline.py
"""

import http.server
import socketserver
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TPL = ROOT / "frontend" / "templates"

# имя, файл, что на экране при обрыве, какое сообщение шлёт Esc, что
# должно появиться со связью
PAGES = [
    ("карта линии", "massaprep_map.html", "acai-massaprep-close", ".chip", 10),
    ("цифровой двойник", "twin_map.html", "acai-twin-close", ".pin", 11),
]

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
SENSOR_NAMES = (ROOT / "frontend" / "static" / "sensor-names.js").read_text(encoding="utf-8")


class Quiet(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(TPL), **kw)

    def log_message(self, *a):
        pass


httpd = socketserver.TCPServer(("127.0.0.1", 0), Quiet)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{httpd.server_address[1]}/"

passed, failed = [], []


def check(name, condition, detail=""):
    if condition:
        passed.append(name)
        print(f"  OK   {name}")
    else:
        failed.append(f"{name}: {detail}")
        print(f"  СБОЙ {name}  {str(detail)[:300]}")


def prepare(page, library=None):
    """Справочник имён отдаём настоящий, библиотеку — по требованию."""
    page.route("**/static/sensor-names.js", lambda route: route.fulfill(
        status=200, content_type="application/javascript", body=SENSOR_NAMES))
    page.route("**/static/fonts.css*", lambda route: route.fulfill(
        status=200, content_type="text/css", body=""))
    page.route("**/api/**", lambda route: route.fulfill(
        status=200, content_type="application/json", body="{}"))
    if library:
        page.route("**/three*.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=library))
    else:
        page.route("**/three*.js", lambda route: route.abort())


try:
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:
            print(f"ПРОПУЩЕНО: Chromium не запускается ({str(exc)[:120]})")
            sys.exit(0)

        for name, filename, closing, mark, least in PAGES:
            print(f"\n— {name}")

            # ── 1. связи с интернетом нет ────────────────────────
            page = browser.new_page()
            prepare(page)
            page.goto(BASE + filename)
            page.wait_for_selector("#loadFail:not([hidden])", timeout=20000)

            check(f"{name}: видно сообщение, а не пустой экран",
                  page.locator("#loadFail").is_visible())
            why = page.locator("#failWhy").inner_text()
            check(f"{name}: сказано, что именно случилось", "связи" in why.lower(), why)
            box = page.locator("#loadFail .noteBox").inner_text()
            check(f"{name}: сказано, что цифры на «Главной» работают без неё",
                  "Главной" in box, box[:120])
            check(f"{name}: есть кнопка «Повторить»", page.locator("#failRetry").is_visible())

            got = page.evaluate(
                """() => new Promise(res => {
                     window.addEventListener('message', e => res(e.data), {once:true});
                     document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape'}));
                     setTimeout(() => res('нет сообщения'), 1500);
                   })""")
            check(f"{name}: Esc закрывает даже нерабочую схему", got == closing, got)
            page.close()

            # ── 2. парная: со связью всё строится ────────────────
            if not LIBRARY:
                print("  ПРОПУЩЕНО парная проверка со связью: библиотеку негде взять")
                continue

            page = browser.new_page()
            prepare(page, LIBRARY)
            page.goto(BASE + filename)
            page.wait_for_selector("canvas", timeout=20000)
            page.wait_for_timeout(4000)

            check(f"{name}: со связью сообщения об обрыве нет",
                  page.locator("#loadFail").is_hidden())
            check(f"{name}: со связью исчезает и строка ожидания",
                  page.locator("#loadNote").is_hidden())
            check(f"{name}: со связью схема построена",
                  page.locator(mark).count() >= least,
                  f"{mark}: {page.locator(mark).count()}")
            page.close()

        browser.close()
finally:
    httpd.shutdown()

print(f"\nСхемы без интернета: проверок {len(passed) + len(failed)}, сбоев {len(failed)}")
for item in failed:
    print("  -", item[:400])
sys.exit(1 if failed else 0)
