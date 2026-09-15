"""
Уборка проекта: что можно убрать и почему.

НИЧЕГО НЕ УДАЛЯЕТ. С флагом --archive переносит найденное в папку
_archive_ГГГГ-ММ-ДД. Если что-то понадобится — вернёте оттуда.
Удалять руками будете потом, когда убедитесь, что не сломалось.

Запуск:
    python cleanup_project.py            — показать
    python cleanup_project.py --archive   — перенести в архив
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))


import sys
import shutil
from pathlib import Path
from datetime import datetime

from backend.config import BASE_DIR


# (путь, причина)
CANDIDATES = [

    # -----------------------------------------
    # Тестовые скрипты, пишущие в БОЕВУЮ базу
    # -----------------------------------------
    ("test_chat.py",
     "ОПАСНО: при запуске пишет фейковые сообщения в обращение №1 "
     "боевой базы. Тест, оставшийся с первых дней."),

    ("test_symptom.py",
     "Проверка детектора симптомов вручную. Логика с тех пор "
     "переписана на ИИ, скрипт проверяет то, чего больше нет."),

    # -----------------------------------------
    # Отладочные утилиты
    # -----------------------------------------
    ("backend/api/chat.py",
     "Отладочный CLI для поиска по документации. Открывает ChromaDB "
     "напрямую в обход vector_service, поэтому не знает ни про "
     "сопоставление станков, ни про фильтры. Всё то же делает "
     "debug_advice.py, только правильно."),

    # -----------------------------------------
    # Заменённые модули
    # -----------------------------------------
    ("backend/database.py",
     "Создание схемы БД первой версии. Таблицы давно создаются "
     "init-функциями в сервисах, а здесь ещё и путь к базе зашит "
     "строкой 'factory.db' в обход config.py."),

    # -----------------------------------------
    # Мёртвые справочники
    # -----------------------------------------
    ("backend/core/symptoms/symptoms.json",
     "Дубликат messersi.json в старом формате. Ни одна строка кода "
     "его не читает — symptom_service ищет файлы по имени станка."),

    ("knowledge_base/__errors_index.json",
     "Копия errors_index.json, оставшаяся от ручного эксперимента."),

    ("knowledge_base/chunks.json",
     "Промежуточная выгрузка кусков текста. База знаний живёт в "
     "ChromaDB, этот файл никем не читается."),

    ("knowledge_base/equipment_index.json",
     "Пустая заготовка индекса оборудования — оборудование лежит "
     "в таблице equipment."),

    ("knowledge_base/parts_index.json",
     "Пустая заготовка под запчасти. Раздел не реализован."),

    ("backend/core/machines/clay.json",
     "Пустая заготовка описания участка."),

    ("backend/core/machines/drying.json",
     "Пустая заготовка описания участка."),

    ("backend/core/machines/forming.json",
     "Пустая заготовка описания участка."),

    ("backend/core/machines/kiln.json",
     "Пустая заготовка описания участка."),

    # -----------------------------------------
    # Мусор macOS и старые копии
    # -----------------------------------------
    ("Searching__FactoryAssistant_.savedSearch",
     "Сохранённый поиск Finder, попал в папку случайно."),

    ("backend/knowledge_base",
     "СТАРОЕ МЕСТО базы знаний. config.py читает knowledge_base/ в "
     "корне проекта — именно оттуда сейчас работает поиск. Здесь "
     "лежит копия, включая chroma_db_73 (та самая неудачная сборка "
     "на 73 куска). Проверьте, что поиск работает, и убирайте."),

    ("conversation_block.html",
     "Кусок разметки переписки для вставки в diagnostics.html. "
     "Переписка переехала в отдельную страницу chat.html."),

    ("users_passwords.txt",
     "ПАРОЛИ ОТКРЫТЫМ ТЕКСТОМ. Если раздали — убирайте немедленно. "
     "Забыл пароль — сбрасывается: python manage_admin.py reset ЛОГИН"),
]


# Файлы, которые выглядят ненужными, но трогать НЕЛЬЗЯ
KEEP_WITH_REASON = [
    ("frontend/templates/diagnostics.html",
     "Из меню убрана, но роут /diagnostics жив. Инженеру иногда "
     "удобно разобрать станок не заводя обращение."),

    ("frontend/static/diagnostics.js",
     "То же самое — работает вместе с diagnostics.html."),

    ("backend/services/instruction_service.py",
     "Легаси-сценарий про плёнку. Сейчас ограничен упаковочной "
     "машиной и стоит выше ИИ по приоритету — работает даже без "
     "интернета. Удалять после того, как те же три шага заведут "
     "через раздел 'Инструкции'."),

    ("backend/services/chat_service.py",
     "Простое сохранение сообщений. Используется в /diagnose при "
     "создании обращения, до того как включается conversation_service."),

    ("frontend/static/script.js",
     "Скрипт дашборда. С diagnostics.html убран, но index.html на "
     "нём держится целиком."),
]


def size_of(path: Path) -> str:

    if path.is_dir():
        total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    else:
        total = path.stat().st_size

    if total > 1024 * 1024:
        return f"{total / 1024 / 1024:.1f} МБ"

    return f"{total / 1024:.0f} КБ"


def main():

    archive_mode = "--archive" in sys.argv

    found = []
    missing = 0

    print("\nЛИШНЕЕ В ПРОЕКТЕ")
    print("=" * 74)

    for relative, reason in CANDIDATES:

        path = BASE_DIR / relative

        if not path.exists():
            missing += 1
            continue

        found.append((path, relative, reason))

        print(f"\n  {relative}   [{size_of(path)}]")

        for line in _wrap(reason):
            print(f"      {line}")

    if not found:
        print("\n  Ничего лишнего не найдено — уже убрано.")

    print("\n\nПОХОЖЕ НА ЛИШНЕЕ, НО НУЖНО")
    print("=" * 74)

    for relative, reason in KEEP_WITH_REASON:

        path = BASE_DIR / relative

        if not path.exists():
            continue

        print(f"\n  {relative}")

        for line in _wrap(reason):
            print(f"      {line}")

    # -----------------------------------------

    print("\n" + "=" * 74)

    if not found:
        return

    if not archive_mode:
        print(f"Найдено к уборке: {len(found)}")
        print("\nЭто ПРОСМОТР — ничего не тронуто.")
        print("Перенести в архив: python cleanup_project.py --archive\n")
        return

    archive = BASE_DIR / f"_archive_{datetime.now().strftime('%Y-%m-%d')}"
    archive.mkdir(exist_ok=True)

    print(f"Переношу в {archive.name}\n")

    for path, relative, _ in found:

        target = archive / relative.replace("/", "__")

        try:
            shutil.move(str(path), str(target))
            print(f"  перенесено: {relative}")
        except Exception as error:
            print(f"  ОШИБКА {relative}: {error}")

    print(f"\nГотово. Ничего не удалено — всё в {archive.name}")
    print("Перезапустите сервер и проверьте, что работает:")
    print("    python check_pilot_ready.py")
    print("    python smoke_test.py --user ЛОГИН_РАБОЧЕГО")
    print("\nЕсли что-то сломалось — верните файл из архива обратно.\n")


def _wrap(text, width=64):

    words = text.split()
    lines = []
    current = ""

    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()

    if current:
        lines.append(current)

    return lines


if __name__ == "__main__":
    main()
