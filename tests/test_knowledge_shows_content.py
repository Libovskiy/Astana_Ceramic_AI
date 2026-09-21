"""
База знаний показывает решение, а не пустой бланк.

21.09.2026 владелец открыл «Базу знаний»: карточки есть, а в них
пусто — «Общее решение» без единой строки описания. При этом решение
лежало в базе целиком («неисправность клапана подачи воды», обращение
№64).

Причина не в записи, а в именах полей: в базе колонки `symptom_text`
и `resolution_comment`, а страницы читают `symptom` и `resolution`.
Сервер отдавал одно, интерфейс спрашивал другое — и молча показывал
пустоту.

Поэтому проверяем не «работает ли endpoint», а то, что человек увидит:
поля, которые читает страница, приходят с сервера и не пустые.

Запуск из корня проекта: python tests/test_knowledge_shows_content.py
"""

import re
from pathlib import Path

from sandbox import Sandbox, check, finish

sb = Sandbox()

ROOT = Path(__file__).resolve().parent.parent
CODE = sb.db().execute(
    "SELECT code FROM plc_error_codes WHERE is_active = 1 AND solution LIKE '%1)%2)%' ORDER BY id LIMIT 1"
).fetchone()["code"]

REPAIR = "Заменил клапан подачи воды, продул рубашку"


print("\n1. Решение специалиста попадает в базу знаний")

worker = sb.user("worker", equipment=[sb.equipment_id])
supervisor = sb.user("shift_supervisor")
chief = sb.user("chief_engineer")

case_id = worker.post("/diagnose", json={
    "equipment_id": sb.equipment_id,
    "question": f"Температура бруса высокая, код {CODE}",
}).json().get("case_id")
check("обращение создано", bool(case_id))

worker.post(f"/api/conversation/{case_id}/escalate")
supervisor.post(f"/api/conversation/{case_id}/draft-close", json={"comment": REPAIR})

# Инженер подтверждает, ничего не дописывая: текст ремонта не должен
# потеряться (на этом уже обжигались — COALESCE затирал его пустотой).
chief.post(f"/api/conversation/{case_id}/approve", json={"comment": ""})

row = sb.db().execute(
    "SELECT * FROM resolution_knowledge_base WHERE case_id = ?", (case_id,)
).fetchone()
check("запись в базе знаний появилась", row is not None)
check("в ней сохранён текст ремонта", row and row["resolution_comment"] == REPAIR,
      dict(row) if row else None)


print("\n2. Страница получает ровно те поля, которые читает")

data = chief.get("/api/knowledge").json()
items = [item for group in (data.get("grouped") or {}).values() for item in group]
mine = [item for item in items if item.get("case_id") == case_id] or items
check("решение отдаётся странице", bool(mine), data)

item = mine[0] if mine else {}
check("поле symptom не пустое", bool((item.get("symptom") or "").strip()), item)
check("поле resolution не пустое", bool((item.get("resolution") or "").strip()), item)
check("resolution — это текст ремонта", item.get("resolution") == REPAIR, item.get("resolution"))
check("станок указан", bool(item.get("machine")), item)


print("\n3. Имена полей в шаблонах совпадают с ответом сервера")

# Берём поля, которые страницы читают у элемента базы знаний, и
# проверяем, что сервер такие отдаёт. Расхождение — это и есть пустой
# бланк, только увиденный до того, как его увидит человек.
for name in ("frontend/templates/knowledge.html", "frontend/templates/instructions.html"):
    page = (ROOT / name).read_text(encoding="utf-8")
    used = set(re.findall(r"item\.([a-z_]+)", page))
    # steps и use_count страницы рисуют «если есть» — их отсутствие не ломает
    used -= {"steps", "use_count", "description", "details", "title", "action"}
    missing = sorted(field for field in used if field not in item)
    check(f"{Path(name).name}: все читаемые поля приходят с сервера",
          not missing, f"нет в ответе: {missing}")


print("\n4. Пустое решение в базу знаний не попадает")

before = sb.db().execute("SELECT COUNT(*) FROM resolution_knowledge_base").fetchone()[0]
case_two = worker.post("/diagnose", json={
    "equipment_id": sb.equipment_id,
    "question": f"Снова греется, код {CODE}",
}).json().get("case_id")
worker.post(f"/api/conversation/{case_two}/resolve")   # рабочий сам сказал «помогло»
after = sb.db().execute("SELECT COUNT(*) FROM resolution_knowledge_base").fetchone()[0]
check("«помогло» от рабочего не плодит пустых записей", after == before, f"{before} → {after}")

print("\n5. Решение находится, даже если сказано другими словами")

from backend.services.knowledge_service import get_relevant_resolutions

machine = sb.db().execute("SELECT machine FROM cases WHERE id = ?", (case_id,)).fetchone()["machine"]

# Оператор пишет одно, механик — другое. Раньше сравнивались слова как
# есть, и знание доходило только до того, кто повторил формулировку
# дословно.
for question in ("Температура бруса высокая", "греется брус", "брус горячий"):
    found = get_relevant_resolutions(machine, question)
    check(f"«{question}» → решение найдено", REPAIR in found, found)

check("по тексту самого ремонта тоже находится",
      REPAIR in get_relevant_resolutions(machine, "клапан подачи воды"),
      get_relevant_resolutions(machine, "клапан подачи воды"))

check("постороннее не подсовывается",
      not get_relevant_resolutions(machine, "не работает освещение в цеху"),
      get_relevant_resolutions(machine, "не работает освещение в цеху"))

check("решение по другому станку не предлагается",
      not get_relevant_resolutions("Печь обжига", "греется брус"),
      get_relevant_resolutions("Печь обжига", "греется брус"))

finish("База знаний показывает решение")
