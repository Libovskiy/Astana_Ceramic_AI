#!/usr/bin/env python3
"""
Простой закрывается, когда станок вернули в работу.

Сейчас простой стартует автоматически, а закрывается только вместе с
обращением. Станок починили, статус вернули на «Работает», обращение
осталось открытым по бумажным причинам — и система считает, что завод
четвёртые сутки стоит. Отсюда 149 часов простоя при работающем заводе.

Статус оборудования — честный сигнал: его ставит человек, который
видит станок. Закрытие обращения им не является.

Заодно убирает второй, дословно повторяющий первый, роут set-status.

    cd /Users/champ_01/Documents/FactoryAssistant
    python3 fix_downtime_close.py

Идемпотентен, делает копию main.py.
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))

import re
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
MAIN = BASE_DIR / "backend" / "api" / "main.py"

OLD_ROUTE = '''@app.post("/api/equipment/{equipment_id}/set-status")
def set_equipment_status_route(
    equipment_id: int,
    request: dict,
    user: dict = Depends(get_current_user)
):
    from backend.services.equipment_service import update_equipment_status
    status = request.get("status")
    if not status:
        raise HTTPException(status_code=400, detail="Статус не указан")
    update_equipment_status(equipment_id, status)
    log_action(username=user["username"], role=user["role"],
        action="equipment_status_changed",
        target=f"equipment:{equipment_id}", details=status)
    return {"success": True}'''

NEW_ROUTE = '''@app.post("/api/equipment/{equipment_id}/set-status")
def set_equipment_status_route(
    equipment_id: int,
    request: dict,
    user: dict = Depends(get_current_user)
):
    from backend.services.equipment_service import update_equipment_status
    from backend.services.downtime_service import (
        get_active_downtime_for_equipment,
        end_downtime,
    )

    status = request.get("status")
    if not status:
        raise HTTPException(status_code=400, detail="Статус не указан")

    update_equipment_status(equipment_id, status)

    # Станок вернули в работу — простой закончился. Раньше он закрывался
    # только вместе с обращением, а оно может висеть неделями, пока
    # станок давно крутится: простой копился и врал в аналитике.
    closed_minutes = None
    if status == "Работает":
        active = get_active_downtime_for_equipment(equipment_id)
        if active:
            try:
                closed_minutes = end_downtime(
                    active["id"],
                    ended_by=user.get("full_name") or user["username"],
                )
            except Exception:
                closed_minutes = None

    log_action(username=user["username"], role=user["role"],
        action="equipment_status_changed",
        target=f"equipment:{equipment_id}", details=status)

    if closed_minutes is not None:
        log_action(username=user["username"], role=user["role"],
            action="downtime_closed_by_status",
            target=f"equipment:{equipment_id}",
            details=f"простой закрыт: {closed_minutes} мин")

    return {"success": True, "downtime_closed_minutes": closed_minutes}'''


def main():
    if not MAIN.exists():
        print("✗ backend/api/main.py не найден — запускай из корня проекта")
        sys.exit(1)

    text = MAIN.read_text(encoding="utf-8")

    if "downtime_closed_by_status" in text:
        print("✓ уже применено")
    else:
        count = text.count(OLD_ROUTE)
        if count == 0:
            print("✗ не нашёл роут set-status — проверь main.py вручную")
            sys.exit(1)
        print(f"  найдено одинаковых роутов set-status: {count}")

        # первый заменяем на новый, остальные — выбрасываем как дубли
        text = text.replace(OLD_ROUTE, NEW_ROUTE, 1)
        while OLD_ROUTE in text:
            text = text.replace(OLD_ROUTE + "\n\n\n", "", 1)
            text = text.replace(OLD_ROUTE, "", 1)

        shutil.copy2(MAIN, MAIN.with_suffix(".py.bak-downtime"))
        MAIN.write_text(text, encoding="utf-8")
        print("✓ простой закрывается при возврате в работу")
        if count > 1:
            print(f"✓ убрано дублей роута: {count - 1}")
        print("  копия: backend/api/main.py.bak-downtime")

    left = len(re.findall(r'@app\.post\("/api/equipment/\{equipment_id\}/set-status"\)',
                          MAIN.read_text(encoding="utf-8")))
    print(f"  роутов set-status осталось: {left} (должен быть 1)")

    import py_compile
    try:
        py_compile.compile(str(MAIN), doraise=True)
        print("✓ main.py компилируется")
    except Exception as e:
        print(f"✗ синтаксическая ошибка: {e}")
        sys.exit(1)

    print("\nДальше: очистить __pycache__ и перезапустить сервер.")


if __name__ == "__main__":
    main()
