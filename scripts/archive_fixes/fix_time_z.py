#!/usr/bin/env python3
"""
Убирает дописывание 'Z' к датам из БД в инлайновых скриптах шаблонов.

БД хранит МЕСТНОЕ время завода (datetime.now()), а код добавлял 'Z' и
читал его как UTC — отсюда «-17713с назад» на /production. У каждой
страницы своя копия timeAgo, поэтому правим все разом.

    cd /Users/champ_01/Documents/FactoryAssistant
    python3 fix_time_z.py

Идемпотентен: повторный запуск ничего не меняет. Делает .bak-копии.
"""
import re
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
TEMPLATES = BASE_DIR / "frontend" / "templates"
STATIC = BASE_DIR / "frontend" / "static"

# (что искать, чем заменить)
RULES = [
    # обычный случай: .replace(' ','T')+'Z'  →  .replace(' ','T')
    (re.compile(r"""\.replace\(\s*['"] ['"]\s*,\s*['"]T['"]\s*\)\s*\+\s*['"]Z['"]"""),
     ".replace(' ','T')"),
    # голая конкатенация: new Date(что_то+'Z')  →  new Date(String(что_то).replace(' ','T'))
    (re.compile(r"""new Date\(\s*([A-Za-z_$][\w.$]*)\s*\+\s*['"]Z['"]\s*\)"""),
     r"new Date(String(\1).replace(' ','T'))"),
]


def patch(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    original = text
    for pattern, repl in RULES:
        text = pattern.sub(repl, text)
    if text == original:
        return 0
    shutil.copy2(path, path.with_suffix(path.suffix + ".bak-timez"))
    path.write_text(text, encoding="utf-8")
    # считаем, сколько мест поменялось
    return original.count("'Z'") - text.count("'Z'")


def main():
    if not TEMPLATES.exists():
        print("✗ frontend/templates не найден — запускай из корня проекта")
        sys.exit(1)

    total_files = 0
    total_spots = 0

    for folder, mask in ((TEMPLATES, "*.html"), (STATIC, "*.js")):
        if not folder.exists():
            continue
        for f in sorted(folder.glob(mask)):
            if f.name.endswith(".bak-timez"):
                continue
            n = patch(f)
            if n:
                total_files += 1
                total_spots += n
                print(f"  ✓ {f.relative_to(BASE_DIR)} — мест: {n}")

    if total_spots:
        print(f"\n✓ файлов: {total_files}, исправлений: {total_spots}")
        print("Копии оригиналов рядом, с суффиксом .bak-timez")
        print("\nНе забудь поднять ?v= у изменённых .js, если они есть в списке.")
    else:
        print("Нечего исправлять — все даты уже читаются как местные.")


if __name__ == "__main__":
    main()
