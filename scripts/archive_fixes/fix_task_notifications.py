#!/usr/bin/env python3
"""
Добавляет просроченные задачи в оповещения.

Сервис оповещений уже показывает простои, эскалации, ожидающие
подтверждения обращения и повторяющиеся неисправности. Задач в нём нет —
а именно их просил главный инженер: задача с просроченным сроком никак
не напоминает о себе, и о ней вспоминают, когда спрашивают.

Добавляем два вида:
  просроченные — срок прошёл, задача не закрыта;
  срок сегодня — предупредить до того, как станет просрочкой.

Право видеть соблюдаем существующее: задачу видит тот, кому она
назначена, её автор и руководители. Чужие задачи в чужой колокольчик
не попадают.

    cd /Users/champ_01/Documents/FactoryAssistant
    python3 fix_task_notifications.py

Идемпотентен, делает копию файла.
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))

import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SERVICE = BASE_DIR / "backend" / "services" / "notification_service.py"

BLOCK = '''

# =========================================================
# ЗАДАЧИ: ПРОСРОЧЕННЫЕ И С СЕГОДНЯШНИМ СРОКОМ
# =========================================================

def _task_notifications(user):
    """
    Задачи, о которых стоит напомнить.

    Руководитель видит все задачи участка, остальные — только свои:
    назначенные на них или созданные ими. Иначе колокольчик мастера
    забьётся чужими делами и его перестанут открывать.
    """
    import sqlite3
    from datetime import datetime

    from backend.config import DB_NAME

    MANAGER_ROLES = {
        "admin", "director", "chief_engineer",
        "chief_mechanic", "chief_electrician", "shift_supervisor",
    }

    role = user.get("role")
    user_id = user.get("id")
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    out = []

    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        conn.row_factory = sqlite3.Row
    except Exception:
        return out

    try:
        if role in MANAGER_ROLES:
            rows = conn.execute(
                """SELECT id, title, due_at, priority, status
                   FROM tasks
                   WHERE status NOT IN ('done', 'cancelled')
                     AND due_at IS NOT NULL AND due_at != ''
                   ORDER BY due_at
                   LIMIT 50"""
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT DISTINCT t.id, t.title, t.due_at, t.priority, t.status
                   FROM tasks t
                   LEFT JOIN task_assignees ta ON ta.task_id = t.id
                   WHERE t.status NOT IN ('done', 'cancelled')
                     AND t.due_at IS NOT NULL AND t.due_at != ''
                     AND (ta.user_id = ? OR t.created_by = ?)
                   ORDER BY t.due_at
                   LIMIT 50""",
                (user_id, user_id),
            ).fetchall()
    except sqlite3.OperationalError:
        # таблицы задач ещё нет — не ломаем колокольчик
        conn.close()
        return out
    finally:
        try:
            conn.close()
        except Exception:
            pass

    for row in rows:
        due = (row["due_at"] or "")[:10]
        if not due:
            continue

        if due < today:
            try:
                days = (now - datetime.strptime(due, "%Y-%m-%d")).days
            except ValueError:
                days = 0

            out.append({
                "type": "task_overdue",
                "severity": "critical" if days > 3 else "warning",
                "title": f"Просрочена: {row['title']}",
                "message": f"Срок был {days} дн. назад" if days else "Срок прошёл",
                "link": "/events",
                "task_id": row["id"],
            })

        elif due == today:
            out.append({
                "type": "task_today",
                "severity": "info",
                "title": f"Срок сегодня: {row['title']}",
                "message": "Задача не закрыта",
                "link": "/events",
                "task_id": row["id"],
            })

    return out
'''

CALL = '''    # Задачи с истёкшим сроком: без напоминания о них вспоминают,
    # только когда спросят.
    try:
        notifications.extend(_task_notifications(user))
    except Exception as error:
        print(f"[notification_service] Задачи пропущены: {error}")

'''


def main():
    if not SERVICE.exists():
        print("✗ backend/services/notification_service.py не найден")
        sys.exit(1)

    text = SERVICE.read_text(encoding="utf-8")

    if "_task_notifications" in text:
        print("✓ уже применено")
    else:
        # функция — в конец файла
        text = text.rstrip() + "\n" + BLOCK

        # вызов — перед возвратом из get_notifications
        marker = None
        for candidate in ("    return notifications", "    return sorted(notifications"):
            if candidate in text:
                marker = candidate
                break

        if marker is None:
            print("✗ не нашёл, куда вставить вызов — проверьте get_notifications вручную")
            sys.exit(1)

        text = text.replace(marker, CALL + marker, 1)

        shutil.copy2(SERVICE, SERVICE.with_suffix(".py.bak-tasks"))
        SERVICE.write_text(text, encoding="utf-8")
        print("✓ просроченные задачи попадают в оповещения")
        print("  копия: backend/services/notification_service.py.bak-tasks")

    import py_compile
    try:
        py_compile.compile(str(SERVICE), doraise=True)
        print("✓ модуль компилируется")
    except Exception as error:
        print(f"✗ синтаксическая ошибка: {error}")
        sys.exit(1)

    print("\nДальше: очистить __pycache__ и перезапустить сервер.")


if __name__ == "__main__":
    main()
