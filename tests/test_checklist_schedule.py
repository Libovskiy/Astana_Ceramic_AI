"""
Обход смены — раз в неделю.

Срок задал владелец 21.09.2026. До этого срока не было нигде, и
страницы писали «обходы за период не проводились» в день, когда обхода
и не должно быть. Это не мелочь: страница, которая упрекает без
повода, обесценивает и настоящие упрёки — их перестают читать.

Отсюда три правила, и здесь проверяется каждое:

  1. срок живёт в ОДНОМ месте (`checklist_service.EVERY_DAYS`), и все
     страницы спрашивают у него, а не считают дни у себя;
  2. просрочка называется числом («просрочен на 3 дн.»), а не общими
     словами;
  3. напоминание приходит тому, кто обход проводит, и заранее — за
     день до срока обойти цех уже поздно.

Запуск из корня проекта: python tests/test_checklist_schedule.py
"""

from datetime import datetime, timedelta

from sandbox import Sandbox, check, finish

sb = Sandbox()

from backend.services import checklist_service
from backend.services.checklist_service import EVERY_DAYS, status
from backend.services.notification_service import _checklist_notifications


def add_round(days_ago: int):
    when = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
    conn = sb.db()
    conn.execute(
        """
        INSERT INTO checklist_rounds
            (username, full_name, shift, started_at, finished_at,
             total_count, ok_count, warn_count, bad_count)
        VALUES ('t-owner', 'Проверка', 'День', ?, ?, 10, 9, 1, 0)
        """,
        (when, when)
    )
    conn.commit()
    conn.close()


def clear():
    conn = sb.db()
    conn.execute("DELETE FROM checklist_rounds")
    conn.commit()
    conn.close()


clear()

print("\n1. Срок — раз в неделю, и он в одном месте")

check("срок недельный", EVERY_DAYS == 7, EVERY_DAYS)
check("напоминаем заранее, а не в последний день",
      checklist_service.REMIND_BEFORE_DAYS >= 1, checklist_service.REMIND_BEFORE_DAYS)


print("\n2. Пока обходов нет, так и сказано")

state = status()
check("состояние «ни одного»", state["state"] == "never", state)
check("и это сказано словами, а не нулём",
      "ещё не было" in state["text"], state["text"])
check("срок назван в тексте", str(EVERY_DAYS) in state["text"], state["text"])


print("\n3. Свежий обход — не нарушение")

add_round(1)
state = status()
check("состояние «в порядке»", state["state"] == "ok", state)
check("названа дата следующего", state["due_date"], state)
check("и дней в запасе больше нуля", state["days_left"] > 0, state)
check("просрочки нет", state["overdue_days"] == 0, state)


print("\n4. Срок подходит — предупреждаем заранее")

clear()
add_round(EVERY_DAYS - 1)
state = status()
check("состояние «пора»", state["state"] == "soon", state)
check("и в тексте есть слово «пора»", "пора" in state["text"], state["text"])


print("\n5. Просрочка названа числом дней")

clear()
add_round(EVERY_DAYS + 3)
state = status()
check("состояние «просрочен»", state["state"] == "overdue", state)
check("просрочка посчитана", state["overdue_days"] == 3, state)
check("и написана в тексте", "на 3 дн" in state["text"], state["text"])


print("\n6. Напоминание — тому, кто обход проводит")

for role in ("shift_supervisor", "chief_mechanic", "chief_engineer"):
    check(f"{role} получает напоминание", _checklist_notifications({"role": role}),
          role)

for role in ("worker", "mechanic", "lab_technician", "analyst"):
    check(f"{role} — не получает: обход проводит не он",
          not _checklist_notifications({"role": role}), role)

alert = _checklist_notifications({"role": "shift_supervisor"})[0]
check("просрочка — это предупреждение", alert["severity"] == "warning", alert)
check("ведёт на страницу обхода", alert["url"] == "/checklist", alert)
check("и говорит, на сколько просрочено", "3 дн" in alert["title"], alert["title"])

clear()
add_round(1)
quiet = _checklist_notifications({"role": "shift_supervisor"})
check("а когда обход свежий — не дёргаем вовсе", not quiet, quiet)


print("\n7. Срок не выдумывается на страницах")

import re
from pathlib import Path

pages = ["frontend/templates/checklist.html", "frontend/templates/analytics.html",
         "frontend/templates/reports.html"]
for page in pages:
    text = Path(page).read_text()
    # Ищем «раз в 7 дней»/«7 дн» прямо в разметке: срок должен
    # приходить с сервера, иначе при смене EVERY_DAYS страница
    # останется со старым числом.
    hardcoded = re.search(r"раз в 7 дн|каждые 7 дн", text)
    check(f"{Path(page).name} не хранит срок у себя", not hardcoded,
          hardcoded.group(0) if hardcoded else "")

finish("Обход смены раз в неделю")
