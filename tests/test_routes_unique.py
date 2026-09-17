"""
Один адрес — один обработчик.

При совпадении адреса и метода отвечает маршрут, подключённый раньше,
второй молча не работает. Так в разделе оборудования годами лежали
«исправленные» загрузка и список документов, до которых не доходил ни
один запрос. Проверка читает приложение и падает на первом дубле.

Запуск из корня проекта: python tests/test_routes_unique.py
"""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.routing import APIRoute
from backend.api.main import app


def flat(routes):
    for route in routes:
        if type(route).__name__ == "_IncludedRouter":
            yield from flat(route.original_router.routes)
        else:
            yield route


seen, duplicates = {}, []
for route in flat(app.routes):
    if not isinstance(route, APIRoute):
        continue
    where = f"{Path(inspect.getsourcefile(route.endpoint)).name}:{route.endpoint.__name__}"
    for method in route.methods:
        key = (method, route.path)
        if key in seen:
            duplicates.append(f"{method} {route.path}: работает {seen[key]}, мёртвый {where}")
        else:
            seen[key] = where

print(f"  маршрутов: {len(seen)}")
for item in duplicates:
    print("  СБОЙ", item)
print("Дублей нет." if not duplicates else f"Дублей: {len(duplicates)}")
sys.exit(1 if duplicates else 0)
