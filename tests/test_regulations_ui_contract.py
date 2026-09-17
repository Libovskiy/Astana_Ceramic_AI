"""
Договорённости интерфейса регламентов.

Раньше тест читал frontend/static/regulations.js — файл, который
страница давно не подключает: вся логика регламентов живёт прямо в
шаблоне regulations.html. Тест проходил, но проверял мёртвый файл,
а живую страницу — нет. Теперь смотрит в шаблон.

Запуск (из корня проекта): python tests/test_regulations_ui_contract.py
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
html = (ROOT / "frontend/templates/regulations.html").read_text()
api = (ROOT / "backend/api/regulation_routes.py").read_text()

# Оптимум убран из модели нормы: у параметра бывает диапазон, цель с
# допуском или граница, а «оптимум» путал технологов.
assert "ОПТИМУМ" not in html, "в интерфейсе регламентов снова появился ОПТИМУМ"
assert 'id="paramOptimal"' not in html, "вернулось поле оптимума"

# Этапы регламента правятся и удаляются через API.
assert '@router.put("/api/regulations/{regulation_id}/stages/{stage_id}")' in api
assert '@router.delete("/api/regulations/{regulation_id}/stages/{stage_id}")' in api

print("regulation UI contract: OK")
