#!/usr/bin/env python3
"""
Подключает индексацию к загрузке документов через карточку станка.

Сейчас прикреплённый паспорт ложится на диск и виден в карточке, но в
базу знаний не попадает: индексация запускается только при подтверждении
документа в разделе структуры, которым никто не пользуется. Главный
инженер загрузит руководство, увидит его в списке и решит, что ИИ теперь
про него знает. ИИ знать не будет.

Правит оба роута загрузки — обычный и base64. Индексация идёт фоновой
задачей: она занимает секунды, и заставлять человека их ждать незачем.

    cd /Users/champ_01/Documents/FactoryAssistant
    python3 fix_upload_indexing.py

Идемпотентен, делает копию main.py.
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))

import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
MAIN = BASE_DIR / "backend" / "api" / "main.py"
SERVICE = BASE_DIR / "backend" / "services" / "quick_ingest.py"

OLD_MULTIPART_SIG = """@app.post("/api/equipment/{equipment_id}/documents/upload")
async def upload_equipment_doc("""

NEW_MULTIPART_SIG = """@app.post("/api/equipment/{equipment_id}/documents/upload")
async def upload_equipment_doc(
    background_tasks: BackgroundTasks,"""

OLD_MULTIPART_END = '''    return {"success": True, "name": clean_name, "url": f"/docs-files/{safe_name}/{clean_name}"}'''

NEW_MULTIPART_END = '''    # В базу знаний — фоном. Без этого ИИ не увидит документ: файл
    # окажется на диске, в карточке, но не в поиске.
    from backend.services.quick_ingest import index_uploaded_pdf
    background_tasks.add_task(index_uploaded_pdf, dest, safe_name)

    return {"success": True, "name": clean_name, "url": f"/docs-files/{safe_name}/{clean_name}"}'''

OLD_B64_SIG = '''async def upload_doc_b64(equipment_id: int, request: dict, user: dict = Depends(require_roles("admin","director","chief_engineer","chief_mechanic","chief_electrician"))):'''

NEW_B64_SIG = '''async def upload_doc_b64(equipment_id: int, request: dict, background_tasks: BackgroundTasks, user: dict = Depends(require_roles("admin","director","chief_engineer","chief_mechanic","chief_electrician"))):'''

OLD_B64_END = '''    return {"success": True, "name": filename, "url": f"/docs-files/{safe_name}/{filename}"}'''

NEW_B64_END = '''    from backend.services.quick_ingest import index_uploaded_pdf
    background_tasks.add_task(index_uploaded_pdf, folder / filename, safe_name)

    return {"success": True, "name": filename, "url": f"/docs-files/{safe_name}/{filename}"}'''


def main():
    if not MAIN.exists():
        print("✗ backend/api/main.py не найден — запускай из корня проекта")
        sys.exit(1)
    if not SERVICE.exists():
        print("✗ backend/services/quick_ingest.py не найден — сначала скопируй его")
        sys.exit(1)

    text = MAIN.read_text(encoding="utf-8")

    if "index_uploaded_pdf" in text:
        print("✓ уже подключено")
    else:
        done = []

        # BackgroundTasks должен быть импортирован
        if "BackgroundTasks" not in text.split("\n\n")[0] and "BackgroundTasks" not in text[:4000]:
            lines = text.split("\n")
            for i, line in enumerate(lines):
                if line.startswith("from fastapi import"):
                    if "BackgroundTasks" not in line:
                        lines[i] = line.rstrip() + ", BackgroundTasks"
                        done.append("импорт BackgroundTasks")
                    break
            text = "\n".join(lines)

        for label, old, new in (
            ("обычная загрузка: параметр", OLD_MULTIPART_SIG, NEW_MULTIPART_SIG),
            ("обычная загрузка: индексация", OLD_MULTIPART_END, NEW_MULTIPART_END),
            ("base64: параметр", OLD_B64_SIG, NEW_B64_SIG),
            ("base64: индексация", OLD_B64_END, NEW_B64_END),
        ):
            if old not in text:
                print(f"✗ не нашёл фрагмент: {label}")
                print("   Возможно, fix_security.py ещё не применялся.")
                sys.exit(1)
            text = text.replace(old, new, 1)
            done.append(label)

        shutil.copy2(MAIN, MAIN.with_suffix(".py.bak-indexing"))
        MAIN.write_text(text, encoding="utf-8")
        for item in done:
            print(f"✓ {item}")
        print("  копия: backend/api/main.py.bak-indexing")

    import py_compile
    try:
        py_compile.compile(str(MAIN), doraise=True)
        print("✓ main.py компилируется")
    except Exception as error:
        print(f"✗ синтаксическая ошибка: {error}")
        sys.exit(1)

    print("\nДальше: очистить __pycache__ и перезапустить сервер.")
    print("Проверка: прикрепите PDF к станку и задайте по нему вопрос на /diagnostics.")


if __name__ == "__main__":
    main()
