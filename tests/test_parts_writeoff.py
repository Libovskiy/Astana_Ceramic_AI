"""
Ремонт и склад: кто списывает запчасть и как об этом узнаёт.

Проверяется весь путь, ради которого это делалось:

  1. ИИ советует заменить деталь — рабочий видит в переписке, есть ли
     она на складе (строка «📦 …»), и не идёт к полке зря;
  2. специалист отмечает ремонт — остаток НЕ меняется сам, но
     появляется заявка ответственному за эту часть;
  3. механика уходит главному механику, электрика — главному
     энергетику; слесарь и рабочий заявок не видят и провести их не
     могут;
  4. списание снимает остаток, пишет в журнал склада обращение и
     станок, и повторно провести ту же заявку нельзя;
  5. «ничего не брали» закрывает заявку, не трогая склад;
  6. списать больше, чем есть, нельзя — остаток не уходит в минус, и
     расхождение называется вслух.

Работает на копии базы (tests/sandbox.py), живые данные не трогает.
Запуск из корня проекта: python tests/test_parts_writeoff.py
"""

from sandbox import Sandbox, check, finish

sb = Sandbox()

from backend.services.part_usage_service import add_stock_note, stock_note

PLC_CODE = sb.db().execute(
    "SELECT code FROM plc_error_codes WHERE is_active = 1 AND solution LIKE '%1)%2)%' ORDER BY id LIMIT 1"
).fetchone()["code"]


def add_part(name, number, category, quantity, equipment_id=None, minimum=1):
    conn = sb.db()
    cur = conn.execute(
        """
        INSERT INTO parts (name, part_number, category, equipment_id, unit,
                           quantity, min_quantity, created_by, created_at)
        VALUES (?, ?, ?, ?, 'шт', ?, ?, 'проверка', datetime('now', 'localtime'))
        """,
        (name, number, category, equipment_id, quantity, minimum)
    )
    conn.commit()
    part_id = cur.lastrowid
    conn.close()
    return part_id


def quantity_of(part_id):
    conn = sb.db()
    value = conn.execute("SELECT quantity FROM parts WHERE id = ?", (part_id,)).fetchone()[0]
    conn.close()
    return value


def set_discipline(equipment_id, discipline):
    conn = sb.db()
    conn.execute("UPDATE equipment SET discipline = ? WHERE id = ?", (discipline, equipment_id))
    conn.commit()
    conn.close()


set_discipline(sb.equipment_id, "mechanical")
set_discipline(sb.other_equipment_id, "electrical")

bearing = add_part("Подшипник 6208", "6208", "mechanical", 3, sb.equipment_id, minimum=2)
contactor = add_part("Контактор LC1D25", "LC1D25", "electrical", 2, sb.other_equipment_id)
belt = add_part("Ремень A-1400", "A1400", "mechanical", 0, sb.equipment_id)

worker = sb.user("worker", equipment=[sb.equipment_id, sb.other_equipment_id])
mechanic = sb.user("mechanic")
electrician = sb.user("electrician")
chief_mechanic = sb.user("chief_mechanic")
chief_electrician = sb.user("chief_electrician")
supervisor = sb.user("shift_supervisor")


print("\n1. Подсказка по складу в совете ИИ")

note = stock_note("Замените подшипник 6208 на валу", equipment_id=sb.equipment_id, discipline="mechanical")
check("есть на складе — видно остаток", "Подшипник 6208" in note and "3" in note, note)

missing = stock_note("Натяните ремень A-1400", equipment_id=sb.equipment_id, discipline="mechanical")
check("нет на складе — сказано прямо, чтобы не искали",
      "НЕТ" in missing and "снабжен" in missing.lower(), missing)

check("совет без запчастей не обрастает подсказкой",
      stock_note("Проверьте давление воздуха", equipment_id=sb.equipment_id) == "")

check("механику не подсовываем электрику",
      "Контактор" not in stock_note("Замените контактор LC1D25", discipline="mechanical"))


print("\n2. Обращение: подсказка попадает в переписку")

r = worker.post("/diagnose", json={"equipment_id": sb.equipment_id,
                                   "question": f"Стучит вал, код: {PLC_CODE}"})
case_id = r.json().get("case_id")
check("обращение создано", r.status_code == 200 and case_id, r.text[:200])

add_stock_note(case_id, "Замените подшипник 6208 на валу")
messages = worker.get(f"/api/conversation/{case_id}").json().get("messages", [])
stock_lines = [m for m in messages if m["role"] == "system" and m["message"].startswith("📦")]
check("строка про склад видна рабочему в переписке", len(stock_lines) == 1, [m["message"] for m in messages])

check("повторно та же строка не пишется",
      add_stock_note(case_id, "Замените подшипник 6208 на валу") is None)

# ИИ сравнивает свои прошлые советы с шагами: подсказка не должна
# попасть в этот список, иначе шаги начнут повторяться по кругу.
from backend.services.conversation_service import _tried_actions
check("подсказка не считается советом ИИ",
      all(not text.startswith("📦") for text in _tried_actions(messages)))


print("\n3. Отметка ремонта: склад не трогаем, но зовём ответственного")

before = quantity_of(bearing)
supervisor.post(f"/api/conversation/{case_id}/draft-close",
                json={"comment": "Заменил подшипник 6208, смазал"})
check("остаток сам не изменился", quantity_of(bearing) == before, quantity_of(bearing))

pending_chief = chief_mechanic.get("/api/parts/writeoffs").json().get("writeoffs", [])
check("заявка ушла главному механику", len(pending_chief) == 1, pending_chief)

writeoff = pending_chief[0] if pending_chief else {}
suggested = [item["name"] for item in writeoff.get("suggested", [])]
check("в заявке названа нужная деталь", "Подшипник 6208" in suggested, suggested)
check("в заявке видно обращение и станок",
      writeoff.get("case_id") == case_id and writeoff.get("equipment_name"), writeoff)

check("слесарь заявок не видит — списывает не он",
      mechanic.get("/api/parts/writeoffs").json().get("writeoffs") == [])
check("рабочий заявок не видит",
      worker.get("/api/parts/writeoffs").json().get("writeoffs") == [])
check("главному энергетику чужая дисциплина не показана",
      chief_electrician.get("/api/parts/writeoffs").json().get("writeoffs") == [])


print("\n4. Списание проводит ответственный")

writeoff_id = writeoff.get("id")

r = chief_electrician.post(f"/api/parts/writeoffs/{writeoff_id}/apply",
                           json={"items": [{"part_id": bearing, "quantity": 1}]})
check("энергетик не может списать механику", r.status_code == 403, r.text[:200])
check("после отказа остаток на месте", quantity_of(bearing) == before)

r = mechanic.post(f"/api/parts/writeoffs/{writeoff_id}/apply",
                  json={"items": [{"part_id": bearing, "quantity": 1}]})
check("слесарь не может списать сам", r.status_code == 403, r.text[:200])

r = chief_mechanic.post(f"/api/parts/writeoffs/{writeoff_id}/apply",
                        json={"items": [{"part_id": bearing, "quantity": 1}]})
check("главный механик списал", r.status_code == 200 and r.json().get("success"), r.text[:200])
check("остаток уменьшился на списанное", quantity_of(bearing) == before - 1, quantity_of(bearing))

conn = sb.db()
log = conn.execute(
    "SELECT * FROM parts_log WHERE part_id = ? ORDER BY id DESC LIMIT 1", (bearing,)
).fetchone()
conn.close()
check("в журнале склада записано, на что ушло",
      log and log["case_id"] == case_id and log["direction"] == "out", dict(log) if log else None)
check("в журнале склада записан станок", log and log["equipment_id"] == sb.equipment_id)

check("заявка ушла из списка", chief_mechanic.get("/api/parts/writeoffs").json().get("writeoffs") == [])

r = chief_mechanic.post(f"/api/parts/writeoffs/{writeoff_id}/apply",
                        json={"items": [{"part_id": bearing, "quantity": 1}]})
check("повторно ту же заявку не провести", r.status_code == 400, r.text[:200])
check("остаток от повторной попытки не уплыл", quantity_of(bearing) == before - 1)


print("\n5. Электрика идёт главному энергетику")

r = worker.post("/diagnose", json={"equipment_id": sb.other_equipment_id,
                                   "question": f"Не запускается, код: {PLC_CODE}"})
case_electrical = r.json().get("case_id")
supervisor.post(f"/api/conversation/{case_electrical}/draft-close",
                json={"comment": "Поменял контактор LC1D25"})

pending_energy = chief_electrician.get("/api/parts/writeoffs").json().get("writeoffs", [])
check("заявка по электрике — у главного энергетика", len(pending_energy) == 1, pending_energy)
check("главному механику её не показали",
      chief_mechanic.get("/api/parts/writeoffs").json().get("writeoffs") == [])


print("\n6. «Ничего не брали» и нехватка на складе")

energy_writeoff = pending_energy[0]["id"] if pending_energy else None
contactor_before = quantity_of(contactor)
r = chief_electrician.post(f"/api/parts/writeoffs/{energy_writeoff}/skip", json={})
check("заявку можно закрыть без списания", r.status_code == 200, r.text[:200])
check("склад при этом не тронут", quantity_of(contactor) == contactor_before)
check("заявка больше не висит",
      chief_electrician.get("/api/parts/writeoffs").json().get("writeoffs") == [])

r = worker.post("/diagnose", json={"equipment_id": sb.equipment_id,
                                   "question": f"Снова стучит, код: {PLC_CODE}"})
case_again = r.json().get("case_id")
supervisor.post(f"/api/conversation/{case_again}/draft-close",
                json={"comment": "Опять менял подшипник 6208"})
again = chief_mechanic.get("/api/parts/writeoffs").json().get("writeoffs", [])
check("на новый ремонт — новая заявка", len(again) == 1, again)

if again:
    r = chief_mechanic.post(f"/api/parts/writeoffs/{again[0]['id']}/apply",
                            json={"items": [{"part_id": bearing, "quantity": 99}]})
    data = r.json() if r.status_code == 200 else {}
    check("списать больше, чем есть, не даём — остаток не уходит в минус",
          quantity_of(bearing) == 0, quantity_of(bearing))
    check("о расхождении сказано вслух", bool(data.get("shortages")), data)


finish("Ремонт и склад")
