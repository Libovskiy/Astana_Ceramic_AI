#!/usr/bin/env python3
"""
Чинит backup_service: он бэкапил не ту базу и падал при каждом запуске.

Две ошибки:
  1. брал DB_PATH из конфига — это monitoring.db, вспомогательная база
     модуля мониторинга. Настоящая факта завода лежит в DB_NAME
     (factory.db), хотя файл копии называется factory_*.db;
  2. DB_PATH — строка, а код вызывает у неё .exists() → AttributeError,
     то есть create_backup падал, ни одной копии так и не создалось.

    cd /Users/champ_01/Documents/FactoryAssistant
    python3 fix_backup_db.py

Идемпотентен, делает копию файла рядом.
"""
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SERVICE = BASE_DIR / "backend" / "services" / "backup_service.py"

OLD_IMPORT = "from backend.config import BASE_DIR, DB_PATH, is_owner"
NEW_IMPORT = """from backend.config import BASE_DIR, DB_NAME, is_owner

# DB_PATH из конфига указывает на monitoring.db (база модуля мониторинга)
# и приходит строкой. Бэкапить надо factory.db — это DB_NAME, — и работать
# с ней как с Path, иначе .exists() роняет создание копии.
DB_PATH = Path(DB_NAME)"""


def main():
    if not SERVICE.exists():
        print("✗ backend/services/backup_service.py не найден — запускай из корня проекта")
        sys.exit(1)

    text = SERVICE.read_text(encoding="utf-8")

    if "DB_PATH = Path(DB_NAME)" in text:
        print("✓ уже исправлено")
    elif OLD_IMPORT not in text:
        print("✗ не нашёл строку импорта — посмотри файл руками:")
        print(f"   ожидалось: {OLD_IMPORT}")
        sys.exit(1)
    else:
        shutil.copy2(SERVICE, SERVICE.with_suffix(".py.bak-dbpath"))
        SERVICE.write_text(text.replace(OLD_IMPORT, NEW_IMPORT, 1), encoding="utf-8")
        print("✓ backup_service бэкапит factory.db (копия: .bak-dbpath)")

    # проверяем, что теперь и правда та база
    sys.path.insert(0, str(BASE_DIR))
    for mod in [m for m in list(sys.modules) if m.startswith("backend")]:
        del sys.modules[mod]
    try:
        from backend.services import backup_service as bs
    except Exception as e:
        print(f"✗ модуль не импортируется: {e}")
        sys.exit(1)

    print(f"  база для копий: {bs.DB_PATH}")
    print(f"  существует: {'да' if bs.DB_PATH.exists() else 'НЕТ'}")

    print("\nДальше: очистить __pycache__ и перезапустить сервер.")


if __name__ == "__main__":
    main()
