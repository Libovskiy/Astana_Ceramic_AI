"""
Карта массаподготовки без интернета: вместо пустого экрана — объяснение.

Схему рисует Three.js, она подгружается с cdn.jsdelivr.net. На
заводском компьютере интернета может не быть вовсе. Проверяется
настоящим браузером, с оборванной загрузкой библиотеки:

  «не висит пустым» — страница нарисована, видно, что случилось, и
  есть «Повторить»;

  парная проверка «не ругается зря» — когда библиотека доступна
  (подсовываем её локально), сообщения об обрыве нет, а сцена
  строится: без этой пары первая проверка зелёная и на странице,
  которая ругается всегда.

Браузер нужен настоящий: ошибка загрузки скрипта в исходниках не
видна. Если playwright или Chromium не установлены (сервер), проверка
честно печатает, что пропущена, и не притворяется пройденной.

Запуск (из корня проекта): python tests/test_massaprep_map_offline.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "frontend" / "templates" / "massaprep_map.html"

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("ПРОПУЩЕНО: playwright не установлен, браузерная проверка не шла")
    sys.exit(0)

passed, failed = [], []


def check(name, condition, detail=""):
    if condition:
        passed.append(name)
        print(f"  OK   {name}")
    else:
        failed.append(f"{name}: {detail}")
        print(f"  СБОЙ {name}  {str(detail)[:300]}")


CDN = "**/three*.js"

# Страницу отдаём по http, а не открываем файлом: file:// не имеет
# происхождения, и postMessage из карты наружу там не проходит — проверка
# Esc мерила бы не код, а ограничение браузера.
import http.server
import socketserver
import threading

class Quiet(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(PAGE.parent), **kw)

    def log_message(self, *a):
        pass


httpd = socketserver.TCPServer(("127.0.0.1", 0), Quiet)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{httpd.server_address[1]}/{PAGE.name}"


# Живая копия библиотеки для парной проверки: берём лежащую рядом,
# иначе скачиваем один раз и кладём в theme/ (папка не в гите).
def three_js():
    local = ROOT / "theme" / "three.min.js"
    if local.exists():
        return local.read_text(encoding="utf-8")
    try:
        import urllib.request
        src = urllib.request.urlopen(
            "https://cdn.jsdelivr.net/npm/three@0.128.0/build/three.min.js",
            timeout=20,
        ).read().decode("utf-8")
    except Exception:
        return None
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(src, encoding="utf-8")
    return src


LIBRARY = three_js()

try:
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:
            print(f"ПРОПУЩЕНО: Chromium не запускается ({str(exc)[:120]})")
            sys.exit(0)

        # ── 1. связи с CDN нет ───────────────────────────────────
        page = browser.new_page()
        page.route(CDN, lambda route: route.abort())
        page.goto(URL)
        page.wait_for_selector("#loadFail:not([hidden])", timeout=15000)

        check("без интернета видно сообщение, а не пустой экран",
              page.locator("#loadFail").is_visible())

        why = page.locator("#failWhy").inner_text()
        check("сказано, что именно случилось", "связи" in why.lower(), why)

        box = page.locator("#loadFail .noteBox").inner_text()
        check("сказано, что цифры на «Главной» работают без неё",
              "Главной" in box, box[:120])

        check("есть кнопка «Повторить»", page.locator("#failRetry").is_visible())
        check("шапка страницы нарисована", page.locator("header p").is_visible())
        check("бесполезные кнопки вида убраны",
              not page.locator(".controls").is_visible())

        # Esc должен работать и в нерабочей карте: иначе из неё не выйти.
        got = page.evaluate(
            """() => new Promise(res => {
                 window.addEventListener('message', e => res(e.data), {once:true});
                 document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape'}));
                 setTimeout(() => res('нет сообщения'), 1500);
               })"""
        )
        check("Esc закрывает даже нерабочую карту", got == "acai-massaprep-close", got)

        # «Повторить» со связью — сцена всё-таки строится
        if LIBRARY:
            page.unroute(CDN)
            page.route(CDN, lambda route: route.fulfill(
                status=200, content_type="application/javascript",
                body=LIBRARY))
            page.locator("#failRetry").click()
            page.wait_for_selector("canvas#c", timeout=15000)
            page.wait_for_timeout(3000)
            check("«Повторить» со связью строит схему",
                  page.locator("#loadFail").is_hidden()
                  and page.locator(".chip").count() >= 10,
                  f"подписей {page.locator('.chip').count()}")
        page.close()

        # ── 2. парная: связь есть — сообщения об обрыве нет ──────
        if LIBRARY:
            page = browser.new_page()
            page.route(CDN, lambda route: route.fulfill(
                status=200, content_type="application/javascript",
                body=LIBRARY))
            page.goto(URL)
            page.wait_for_selector("canvas#c", timeout=15000)
            page.wait_for_timeout(3000)
            check("со связью сообщения об обрыве нет",
                  page.locator("#loadFail").is_hidden())
            check("со связью исчезает и «Загружаю карту…»",
                  page.locator("#loadNote").is_hidden())
            check("со связью схема построена",
                  page.locator(".chip").count() >= 10,
                  f"подписей {page.locator('.chip').count()}")
            page.close()
        else:
            # Ни копии рядом, ни интернета — вторую половину проверить
            # нечем. Молчать об этом нельзя: половина проверки не шла.
            print("  ПРОПУЩЕНО парная проверка со связью: библиотеку "
                  "негде взять (нет theme/three.min.js и нет интернета)")

        browser.close()
finally:
    httpd.shutdown()

print(f"\nКарта без интернета: проверок {len(passed) + len(failed)}, сбоев {len(failed)}")
for item in failed:
    print("  -", item[:400])
sys.exit(1 if failed else 0)
