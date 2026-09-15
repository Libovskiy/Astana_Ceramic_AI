#!/usr/bin/env python3
"""
Переключает поиск по документации на многоязычную модель.

Модель и имя коллекции выносятся в .env, чтобы вернуться назад можно
было правкой одной строки, без изменения кода:

    ACAI_EMBED_MODEL=paraphrase-multilingual-MiniLM-L12-v2
    ACAI_COLLECTION=factory_manuals_ml

Меняются ДВА места. Поиск (vector_service) — чтобы искал в новой
коллекции. И загрузка документов (document_ingestion) — чтобы
прикреплённые PDF попадали туда же и той же моделью. Если поменять
только первое, свежие документы уйдут в старую коллекцию и поиск их
не увидит.

    cd /Users/champ_01/Documents/FactoryAssistant
    python3 fix_search_model.py

Идемпотентен, делает копии файлов.
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))

import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG = BASE_DIR / "backend" / "config.py"
VECTOR = BASE_DIR / "backend" / "services" / "vector_service.py"
INGEST = BASE_DIR / "backend" / "services" / "document_ingestion.py"
ENV = BASE_DIR / ".env"

NEW_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
NEW_COLLECTION = "factory_manuals_ml"

CONFIG_BLOCK = '''
# Модель поиска по документации и коллекция, в которой он ищет.
# Прежняя all-MiniLM-L6-v2 обучена на английском, а документация русская:
# она путала «залипание влажным сырьём» и «налипание массы на вал».
# Меняются через .env, старую коллекцию это не трогает — откат возможен.
EMBED_MODEL_NAME = _os.getenv("ACAI_EMBED_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
CHROMA_COLLECTION_NAME = _os.getenv("ACAI_COLLECTION", "factory_manuals_ml")
'''


def patch_config():
    text = CONFIG.read_text(encoding="utf-8")

    if "EMBED_MODEL_NAME" in text:
        print("✓ config: уже настроен")
        return True

    old_line = 'CHROMA_COLLECTION_NAME = "factory_manuals"'
    if old_line not in text:
        print("✗ config: не нашёл строку CHROMA_COLLECTION_NAME")
        return False

    shutil.copy2(CONFIG, CONFIG.with_suffix(".py.bak-search"))
    CONFIG.write_text(text.replace(old_line, CONFIG_BLOCK.strip(), 1), encoding="utf-8")
    print("✓ config: модель и коллекция читаются из .env")
    return True


def patch_file(path, label):
    text = path.read_text(encoding="utf-8")

    if "EMBED_MODEL_NAME" in text:
        print(f"✓ {label}: уже использует настройку")
        return True

    if 'model_name="all-MiniLM-L6-v2"' not in text and "model_name='all-MiniLM-L6-v2'" not in text:
        print(f"! {label}: строка с моделью не найдена, проверь вручную")
        return False

    shutil.copy2(path, path.with_suffix(path.suffix + ".bak-search"))

    text = text.replace('model_name="all-MiniLM-L6-v2"', "model_name=EMBED_MODEL_NAME")
    text = text.replace("model_name='all-MiniLM-L6-v2'", "model_name=EMBED_MODEL_NAME")

    # дотягиваем импорт настройки
    if "from backend.config import" in text and "EMBED_MODEL_NAME" not in text.split("\n\n")[0]:
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if line.startswith("from backend.config import"):
                if "(" in line:
                    lines[i] = line.replace("(", "(\n    EMBED_MODEL_NAME,", 1)
                else:
                    lines[i] = line.rstrip() + ", EMBED_MODEL_NAME"
                break
        text = "\n".join(lines)

    path.write_text(text, encoding="utf-8")
    print(f"✓ {label}: модель берётся из настройки")
    return True


def patch_env():
    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    have = {l.split("=")[0] for l in lines if "=" in l}

    added = []
    if "ACAI_EMBED_MODEL" not in have:
        lines.append(f"ACAI_EMBED_MODEL={NEW_MODEL}")
        added.append("ACAI_EMBED_MODEL")
    if "ACAI_COLLECTION" not in have:
        lines.append(f"ACAI_COLLECTION={NEW_COLLECTION}")
        added.append("ACAI_COLLECTION")

    if added:
        ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"✓ .env: добавлено {', '.join(added)}")
    else:
        print("✓ .env: уже настроен")


def main():
    for path, label in ((CONFIG, "config"), (VECTOR, "vector_service"), (INGEST, "document_ingestion")):
        if not path.exists():
            print(f"✗ {path} не найден — запускай из корня проекта")
            sys.exit(1)

    if not patch_config():
        sys.exit(1)

    patch_file(VECTOR, "vector_service")
    patch_file(INGEST, "document_ingestion")
    patch_env()

    import py_compile
    ok = True
    for path in (CONFIG, VECTOR, INGEST):
        try:
            py_compile.compile(str(path), doraise=True)
        except Exception as e:
            print(f"✗ {path.name}: {e}")
            ok = False
    if not ok:
        sys.exit(1)
    print("✓ все модули компилируются")

    print("\nОткат, если понадобится: в .env поставить")
    print("  ACAI_EMBED_MODEL=all-MiniLM-L6-v2")
    print("  ACAI_COLLECTION=factory_manuals")
    print("\nДальше: очистить __pycache__ и перезапустить сервер.")


if __name__ == "__main__":
    main()
