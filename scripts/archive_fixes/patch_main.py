"""
Подключение роутеров к main.py — автоматически.

Почему скриптом, а не заменой файла: ваш main.py уже содержит
подключения предыдущих модулей (чат, лаборатория, админка,
защищённые действия). Прислать свою копию значило бы затереть их.
Скрипт правит ВАШ файл, ничего не теряя.

Что делает:
    1. Копирует main.py в main.py.bak
    2. Находит app = FastAPI()
    3. После него (и после уже существующих include_router)
       вставляет недостающие подключения
    4. Проверяет синтаксис. Если что-то не так — откатывает.

Повторный запуск безопасен: уже подключённое пропускается.

Запуск: python patch_main.py
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))


import ast
import shutil
import sys
from pathlib import Path

from backend.config import BASE_DIR


MAIN = BASE_DIR / "backend" / "api" / "main.py"


# (модуль, имя, комментарий)
ROUTERS = [
    (
        "backend.api.conversation_routes",
        "conversation_router",
        "Переписка по обращениям",
    ),
    (
        "backend.api.admin_routes",
        "admin_router",
        "Управление пользователями из веба",
    ),
    (
        "backend.api.lab_routes",
        "lab_router",
        "Лабораторный журнал",
    ),
    (
        "backend.api.protected_routes",
        "protected_router",
        "Необратимые действия — только владелец",
    ),
    (
        "backend.api.regulation_routes",
        "regulation_router",
        "Регламенты: нормы, версии, замеры, обслуживание",
    ),
    (
        "backend.api.structure_routes",
        "structure_router",
        "Структура: этапы, оборудование, части, документы",
    ),
]


def main():

    if not MAIN.exists():
        print(f"Не найден {MAIN}")
        return 1

    source = MAIN.read_text(encoding="utf-8")

    missing = [
        item for item in ROUTERS
        if f"include_router({item[1]})" not in source
    ]

    if not missing:
        print("Все роутеры уже подключены — менять нечего.")
        return 0

    print("Подключаю:")
    for module, name, comment in missing:
        print(f"  {name:<22} {comment}")

    # -----------------------------------------
    # Куда вставлять
    # -----------------------------------------

    lines = source.split("\n")

    anchor = None

    # После последнего существующего include_router — так все
    # подключения окажутся рядом, а не разбросаны по файлу
    for index, line in enumerate(lines):
        if "include_router(" in line:
            anchor = index

    if anchor is None:

        for index, line in enumerate(lines):
            if line.strip().startswith("app = FastAPI("):
                # Учитываем многострочный вызов
                depth = line.count("(") - line.count(")")
                anchor = index
                while depth > 0 and anchor + 1 < len(lines):
                    anchor += 1
                    depth += lines[anchor].count("(") - lines[anchor].count(")")
                break

    if anchor is None:
        print("\nНе нашёл app = FastAPI() — вставлять некуда.")
        return 1

    block = [""]

    for module, name, comment in missing:
        block.append(f"# {comment}")
        block.append(f"from {module} import router as {name}")
        block.append(f"app.include_router({name})")
        block.append("")

    patched = "\n".join(lines[:anchor + 1] + block + lines[anchor + 1:])

    # -----------------------------------------
    # Проверяем и сохраняем
    # -----------------------------------------

    try:
        ast.parse(patched)

    except SyntaxError as error:
        print(f"\nПосле правки файл сломался бы: {error}")
        print("Ничего не изменено.")
        return 1

    backup = MAIN.with_suffix(".py.bak")
    shutil.copy(MAIN, backup)

    MAIN.write_text(patched, encoding="utf-8")

    print(f"\nГотово. Копия старого файла: {backup.name}")
    print(f"Вставлено после строки {anchor + 1}.")
    print("\nПерезапустите сервер:")
    print("  launchctl kickstart -k gui/$(id -u)/com.acai.server")

    return 0


if __name__ == "__main__":
    sys.exit(main())
