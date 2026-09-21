"""
Все проверки подряд. Запуск из корня проекта: python tests/run_all.py

Быстрые (читают исходники) идут первыми, сквозные — на копии базы,
живые данные не трогают. Код выхода 1, если хоть одна упала.
"""

import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORDER = [
    "test_page_roles.py",
    "test_structure.py",
    "test_regulations.py",
    "test_regulations_crud.py",
    "test_regulation_persistence.py",
    "test_regulations_ui_contract.py",
    "test_e2e_breakdown.py",
    "test_access_denied.py",
    "test_files.py",
    "test_routes_unique.py",
    "test_restore.py",
    "test_layout_init.py",
    "test_parts_writeoff.py",
    "test_buttons_match_rights.py",
    "test_dark_theme.py",
    "test_ai_answers_everyone.py",
    "test_knowledge_shows_content.py",
    "test_production_import.py",
]

failed = []
names = ORDER + sorted(p.name for p in HERE.glob("test_*.py") if p.name not in ORDER)
for name in names:
    started = time.time()
    result = subprocess.run([sys.executable, str(HERE / name)], capture_output=True, text=True, cwd=HERE.parent)
    took = time.time() - started
    status = "OK  " if result.returncode == 0 else "СБОЙ"
    print(f"{status} {name:<36} {took:5.1f} с")
    if result.returncode != 0:
        failed.append(name)
        lines = [l for l in (result.stdout + result.stderr).splitlines() if "СБОЙ" in l or "Error" in l]
        for line in lines[-8:]:
            print("       ", line[:200])

print(f"\nИтого файлов: {len(names)}, упало: {len(failed)}")
sys.exit(1 if failed else 0)
