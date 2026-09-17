"""
Сквозной сценарий поломки — путь, который пройдёт каждое настоящее
обращение. Ломается он чаще всего на стыках: обращение создалось, а
простой не начался; механик взял, а рабочий не видит; инженер закрыл, а
простой висит.

  A. Рабочий сам справился:
     обращение → ИИ дал шаг 1 → «Не помогло» → шаг 2 → «Помогло» →
     закрыто, простой закончился.

  B. Нужен специалист:
     обращение → «Позвать мастера» → в очереди механика → механик взял →
     написал рабочему → ремонт выполнен (черновик закрытия) →
     главный инженер подтвердил → закрыто, простой закончился,
     решение попало в базу знаний, всё записано в журнал.

Работает на копии базы (tests/sandbox.py), живые данные не трогает.
Запуск из корня проекта: python tests/test_e2e_breakdown.py
"""

from sandbox import Sandbox, check, finish

sb = Sandbox()

# Вопрос с кодом ошибки PLC: ответ берётся из базы кодов, без ИИ и сети
PLC_CODE = sb.db().execute(
    "SELECT code FROM plc_error_codes WHERE is_active = 1 AND solution LIKE '%1)%2)%' ORDER BY id LIMIT 1"
).fetchone()["code"]
QUESTION = f"Ошибка на панели, код: {PLC_CODE}"


def case_row(case_id):
    return dict(sb.db().execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone())


def open_downtime(case_id):
    return sb.db().execute(
        "SELECT COUNT(*) FROM downtime_log WHERE case_id = ? AND ended_at IS NULL", (case_id,)
    ).fetchone()[0]


def messages(client, case_id):
    r = client.get(f"/api/conversation/{case_id}")
    return r.json().get("messages", []) if r.status_code == 200 else []


def start_case(worker, label):
    r = worker.post("/diagnose", json={"equipment_id": sb.equipment_id, "question": QUESTION})
    data = r.json() if r.status_code == 200 else {}
    check(f"{label}: обращение создано", r.status_code == 200 and data.get("success") and data.get("case_id"), r.text[:200])
    case_id = data.get("case_id")
    check(f"{label}: первый ответ — один шаг, не всё решение",
          "Шаг 1" in (data.get("recommendation") or "") and "Шаг 2" not in (data.get("recommendation") or ""),
          data.get("recommendation"))
    check(f"{label}: простой начался автоматически", case_id and open_downtime(case_id) == 1)
    return case_id


print("\nA. Рабочий справился сам")

worker = sb.user("worker", equipment=[sb.equipment_id])
case_a = start_case(worker, "A")

r = worker.post(f"/api/conversation/{case_a}/message", json={"text": "Не помогло"})
reply = (r.json().get("reply") or {}) if r.status_code == 200 else {}
check("A: «Не помогло» → следующий шаг", "Шаг 2" in (reply.get("message") or ""), r.text[:300])

r = worker.post(f"/api/conversation/{case_a}/resolve")
check("A: «Помогло» закрывает обращение", r.status_code == 200 and case_row(case_a)["status"] == "Закрыто", r.text[:200])
check("A: простой закончился", open_downtime(case_a) == 0)

r = worker.post(f"/api/conversation/{case_a}/message", json={"text": "ещё вопрос"})
check("A: в закрытое обращение писать нельзя", r.status_code == 400, r.status_code)


print("\nB. Через механика и главного инженера")

worker_b = sb.user("worker", equipment=[sb.equipment_id])
mechanic = sb.user("mechanic")
chief = sb.user("chief_engineer")

case_b = start_case(worker_b, "B")

r = worker_b.post(f"/api/conversation/{case_b}/escalate")
check("B: «Позвать мастера» передаёт специалисту",
      r.status_code == 200 and case_row(case_b)["status"] == "Требует специалиста", r.text[:200])

r = mechanic.get("/api/work-queue")
queue_ids = [item.get("id") or item.get("case_id") for item in r.json().get("queue", [])] if r.status_code == 200 else []
check("B: обращение в очереди механика", case_b in queue_ids, r.text[:200])

r = mechanic.post(f"/api/conversation/{case_b}/take")
row = case_row(case_b)
check("B: механик взял в работу", r.status_code == 200 and row["status"] == "В работе" and row["assigned_to"], r.text[:200])
check("B: рабочий видит, кто взял",
      any(m["role"] == "system" and "взял" in m["message"] for m in messages(worker_b, case_b)))

r = mechanic.post(f"/api/conversation/{case_b}/message", json={"text": "Иду, буду через 10 минут"})
check("B: механик пишет в обращение", r.status_code == 200, r.text[:200])
check("B: рабочий видит ответ механика",
      any(m["role"] == "specialist" and "10 минут" in m["message"] for m in messages(worker_b, case_b)))

r = worker_b.post(f"/api/conversation/{case_b}/approve", json={"comment": "сам себе закрою"})
check("B: рабочий не может подтвердить закрытие", r.status_code == 403, r.status_code)

r = mechanic.post(f"/api/conversation/{case_b}/complete", json={"comment": "Взвёл реле аварийной остановки, проверил кнопки"})
check("B: ремонт выполнен → черновик закрытия",
      r.status_code == 200 and case_row(case_b)["status"] == "Черновик закрытия", r.text[:200])
check("B: простой ещё идёт, пока не подтвердили", open_downtime(case_b) == 1)

r = mechanic.post(f"/api/conversation/{case_b}/approve", json={"comment": ""})
check("B: механик не подтверждает своё же закрытие", r.status_code == 403, r.status_code)

knowledge_before = sb.db().execute("SELECT COUNT(*) FROM resolution_knowledge_base").fetchone()[0]
r = chief.post(f"/api/conversation/{case_b}/approve", json={"comment": ""})
row = case_row(case_b)
check("B: главный инженер подтвердил → закрыто", r.status_code == 200 and row["status"] == "Закрыто", r.text[:200])
check("B: простой закончился", open_downtime(case_b) == 0)
check("B: решение попало в базу знаний",
      sb.db().execute("SELECT COUNT(*) FROM resolution_knowledge_base").fetchone()[0] > knowledge_before)

actions = {r["action"] for r in sb.db().execute(
    "SELECT action FROM audit_log WHERE target = ?", (f"case:{case_b}",)
)}
check("B: путь записан в журнал действий", len(actions) >= 2, actions)

r = worker_b.get("/api/conversation")
closed_in_active = any(c.get("id") == case_b for c in r.json().get("conversations", [])) if r.status_code == 200 else True
check("B: у рабочего закрытое не висит в открытых", not closed_in_active)

print("\nC. Новая жалоба по станку с уже открытым обращением")

worker_c = sb.user("worker", equipment=[sb.other_equipment_id])
codes = [r["code"] for r in sb.db().execute(
    "SELECT code FROM plc_error_codes WHERE is_active = 1 AND solution LIKE '%1)%2)%' ORDER BY id LIMIT 40"
)]
from backend.services.plc_error_service import find_by_code, split_solution_steps
# два кода, у которых разные решения
first_code = codes[0]
second_code = next(c for c in codes if find_by_code(c)[0]["solution"] != find_by_code(first_code)[0]["solution"])

r1 = worker_c.post("/diagnose", json={"equipment_id": sb.other_equipment_id, "question": f"ошибка {first_code}"}).json()
r2 = worker_c.post("/diagnose", json={"equipment_id": sb.other_equipment_id, "question": f"теперь ошибка {second_code}"}).json()
check("C: вторая жалоба дописалась в то же обращение", r1.get("case_id") == r2.get("case_id"), (r1.get("case_id"), r2.get("case_id")))

r = worker_c.post(f"/api/conversation/{r2['case_id']}/message", json={"text": "Не помогло"})
expected = split_solution_steps(find_by_code(second_code)[0]["solution"])[1]
got = (r.json().get("reply") or {}).get("message") if r.status_code == 200 else None
check("C: «Не помогло» → шаг 2 по последней названной ошибке, не по старой", got == expected, f"{got!r} ≠ {expected!r}")

finish("Сквозной сценарий поломки")
