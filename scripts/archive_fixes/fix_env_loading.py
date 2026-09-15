#!/usr/bin/env python3
"""
Учит config.py читать .env.

Сейчас ключи берутся только из переменных окружения процесса, а launchd
их не передаёт — в plist задан лишь PATH. Файл .env при этом лежит в
проекте и никем не читается, поэтому OPENAI_API_KEY не доходит до
ai_service, клиент становится None и каждое обращение уходит в эскалацию.

Разбираем .env сами, без python-dotenv: одной зависимостью меньше, и при
переезде на сервер ничего доустанавливать не придётся.

    cd /Users/champ_01/Documents/FactoryAssistant
    python3 fix_env_loading.py

Идемпотентен. Делает копию config.py рядом.
"""
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG = BASE_DIR / "backend" / "config.py"

LOADER = '''
# =========================================
# ЧТЕНИЕ .env
# =========================================
# launchd передаёт процессу только PATH, поэтому ключи из окружения
# оболочки до сервера не доходят. Читаем .env из корня проекта сами —
# без python-dotenv, чтобы не тянуть зависимость.
# Уже заданные переменные окружения имеют приоритет: так на сервере
# можно переопределить значение, не трогая файл.
def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:
        # проблема с .env не должна ронять запуск сервера
        pass


_load_dotenv(BASE_DIR / ".env")
'''


def main():
    if not CONFIG.exists():
        print("✗ backend/config.py не найден — запускай из корня проекта")
        sys.exit(1)

    text = CONFIG.read_text(encoding="utf-8")

    if "_load_dotenv" in text:
        print("✓ чтение .env уже добавлено")
    else:
        anchor = "BASE_DIR = Path(__file__).resolve().parent.parent"
        if anchor not in text:
            print("✗ не нашёл строку с BASE_DIR — добавь блок руками")
            sys.exit(1)

        shutil.copy2(CONFIG, CONFIG.with_suffix(".py.bak-env"))
        text = text.replace(anchor, anchor + "\n" + LOADER, 1)
        CONFIG.write_text(text, encoding="utf-8")
        print("✓ config.py читает .env (копия: backend/config.py.bak-env)")

    # проверяем результат, не показывая значение
    sys.path.insert(0, str(BASE_DIR))
    for mod in [m for m in list(sys.modules) if m.startswith("backend")]:
        del sys.modules[mod]
    try:
        from backend.config import OPENAI_API_KEY
    except Exception as e:
        print(f"✗ config.py не импортируется: {e}")
        sys.exit(1)

    if OPENAI_API_KEY:
        print(f"✓ OPENAI_API_KEY подхватился (длина {len(OPENAI_API_KEY)})")
    else:
        print("✗ OPENAI_API_KEY пуст — проверь имя переменной в .env:")
        print("  cut -d= -f1 .env")

    print("\nДальше: очистить __pycache__ и перезапустить сервер.")


if __name__ == "__main__":
    main()
