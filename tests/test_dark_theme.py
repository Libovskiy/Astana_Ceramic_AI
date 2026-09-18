"""
Тёмная тема не должна ломаться от зашитого цвета.

18.09.2026 главный механик открыл «Руководство оборудования» в тёмной
теме и увидел белое окно со светло-серым текстом — читать невозможно.
Причина простая: окно рисуется из JS, и в нём стояло
`background: #fff`, а цвет текста брался из темы. То же было в
«Истории оборудования» и в плашке простоя.

Проверка статическая: ищем в файлах интерфейса цвета, зашитые под
светлую тему. Она дешевле экранного сравнения и ловит беду до того,
как её увидит человек в цеху.

Что разрешено и почему — в ALLOWED ниже: белый текст на цветной
заливке читается в обеих темах, QR-коду белый фон нужен физически.

Запуск из корня проекта: python tests/test_dark_theme.py
"""

import re
from pathlib import Path

from sandbox import check, finish

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

# Цвета, зашитые под светлую тему. В тёмной дают белые пятна и
# нечитаемый текст.
RISKY = re.compile(
    r"background:\s*(#fff\b|#ffffff\b|white\b|#f8f9fa|#f1f5f9|#eef1f6|#fef3c7|#fef2f2|#eff6ff|#fffbeb)"
    r"|color:\s*(#888|#666|#333|#475569)\b",
    re.IGNORECASE,
)

# Строки, где зашитый цвет уместен.
ALLOWED = (
    "color:#fff",            # белый текст на цветной заливке
    "color: #fff",
    "var(--surface,",        # запасное значение у переменной
    "var(--text,",
    "data-theme=dark",       # правило именно для тёмной темы
    'data-theme="dark"',
    "qr img",                # QR-коду нужен белый фон, иначе камера не прочтёт
    "has-task::after",       # точка на цветном кружке календаря
    "voice-rec",             # кнопка записи одинакова в обеих темах
    "background:#fff;margin",  # та же точка в календаре
    "mg-up-fill",            # полоса загрузки поверх цветной плашки
)

def dark_overrides(text: str) -> str:
    """Часть файла, которая относится только к тёмной теме."""
    marker = text.find('[data-theme="dark"]')
    return text[marker:] if marker >= 0 else ""


def selector_of(lines, index: int) -> str:
    """Ближайший селектор выше строки: '.msg-system {' → '.msg-system'."""
    for line in reversed(lines[:index]):
        if "{" in line and not line.strip().startswith(("/*", "*", "//")):
            return line.split("{")[0].strip().rstrip(",")
    return ""


problems = []
scanned = 0

for path in sorted(list(FRONTEND.glob("static/*.js")) + list(FRONTEND.glob("static/*.css"))
                   + list(FRONTEND.glob("templates/*.html"))):
    scanned += 1
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    dark_part = dark_overrides(text)

    for number, line in enumerate(lines, 1):
        if not RISKY.search(line):
            continue
        if any(mark in line for mark in ALLOWED):
            continue

        # Цвет под светлую тему допустим, если для этого же селектора
        # файл задаёт своё правило в тёмной теме (так сделано в
        # chat.css: светлые значения сверху, тёмные — ниже).
        selector = selector_of(lines, number - 1)
        if selector and dark_part and selector in dark_part:
            continue

        problems.append(f"{path.relative_to(ROOT)}:{number}  ({selector or '—'}) {line.strip()[:80]}")

check(f"просмотрено файлов интерфейса: {scanned}", scanned > 20)
check("нет цветов, зашитых под светлую тему",
      not problems, "\n        " + "\n        ".join(problems[:12]))

# Переменные темы объявлены для обеих тем — иначе var() отдаст пустоту.
css = (FRONTEND / "static/acai.css").read_text(encoding="utf-8")
for name in ("--surface", "--surface-2", "--text", "--text-dim", "--border",
             "--ok", "--ok-solid", "--warn", "--danger", "--accent"):
    check(f"{name} задан дважды (тёмная и светлая)",
          css.count(f"{name}:") >= 2, css.count(f"{name}:"))

finish("Тёмная тема")
