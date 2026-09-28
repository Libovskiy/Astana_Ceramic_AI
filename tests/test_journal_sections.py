"""
Лаборатория, склад и переписка: след там, где он нужен, и нигде больше.

Аудит изменяющих ручек оставил эти три раздела без записи в журнал.
Закрываем по правилам владельца — и по-разному, потому что данные
разные:

  • лаборатория: дозапись пустого поля — это ввод (утром лаборант
    знает шихту, а вес и марку только через несколько суток), а вот
    исправление уже записанной цифры — правка, и она в журнале с
    «было → стало». Отметка «отчёт закончен» — одной строкой;

  • склад: движения (приход и расход) свой след уже пишут в parts_log,
    а начальный остаток при заведении детали не писался никуда —
    деталь с количеством появлялась из ниоткуда;

  • переписка: пишем ТОЛЬКО удаления и только факт с автором. Текста
    сообщений в журнале нет намеренно: журнал читают директор и
    аналитик, и он не должен становиться способом прочитать удалённую
    переписку сотрудников. Отправка, чтение, выход из группы и
    переименование не пишутся вовсе.

Базы временные, боевые не трогаются.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sandbox import Sandbox, check, finish   # noqa: E402

sb = Sandbox()
lab = sb.user("lab_technician")
chief_mech = sb.user("chief_mechanic")
worker1 = sb.user("worker")
worker2 = sb.user("worker")


def journal(action):
    conn = sb.db()
    rows = conn.execute("SELECT * FROM audit_log WHERE action=? ORDER BY id DESC",
                        (action,)).fetchall()
    conn.close()
    return rows


# ── Лаборатория ─────────────────────────────────────────────────────
r = lab.post("/api/lab/entries", json={"data": {
    "log_date": "2026-09-28", "brigade": "А", "clay_percent": 70}})
check("лаборант завёл запись", r.status_code == 200 and r.json().get("success"), r.text[:200])
entry_id = r.json()["id"]

# Дозапись пустого поля — ввод данных, следа быть не должно.
r = lab.put(f"/api/lab/entries/{entry_id}", json={"data": {"sand_percent": 30}})
check("дозапись принята", r.status_code == 200, r.text[:200])
check("дозапись пустого поля в журнал не идёт",
      len(journal("lab_entry_corrected")) == 0, len(journal("lab_entry_corrected")))

# Исправление уже записанного — правка.
r = lab.put(f"/api/lab/entries/{entry_id}", json={"data": {"clay_percent": 65}})
check("исправление принято", r.status_code == 200, r.text[:200])
rows = journal("lab_entry_corrected")
check("исправление записанного попало в журнал", len(rows) == 1, len(rows))
check("с «было → стало»",
      "70" in (rows[0]["before_json"] or "") and "65" in (rows[0]["after_json"] or ""),
      dict(rows[0]))

# Парная проверка: сценарий должен уметь покраснеть. Если бы в журнал
# шла любая правка, запись появилась бы и от дозаписи выше — а её нет,
# и это видно по тому, что счётчик не вырос со второй дозаписи.
r = lab.put(f"/api/lab/entries/{entry_id}", json={"data": {"raw_weight": 3.2}})
check("контрольная: ещё одна дозапись счётчик не двигает",
      len(journal("lab_entry_corrected")) == 1, len(journal("lab_entry_corrected")))

r = lab.post(f"/api/lab/entries/{entry_id}/complete", json={"complete": True})
check("отчёт отмечен законченным", r.status_code == 200, r.text[:200])
check("отметка записана одной строкой", len(journal("lab_entry_completed")) == 1)

r = lab.post(f"/api/lab/entries/{entry_id}/complete", json={"complete": False})
check("снятие отметки записано отдельно", len(journal("lab_entry_reopened")) == 1)

# ── Склад ───────────────────────────────────────────────────────────
r = worker1.post("/api/parts", json={"name": "Подшипник проверочный", "quantity": 5})
check("рабочий деталь не заводит", r.status_code == 403, r.status_code)

r = chief_mech.post("/api/parts", json={
    "name": "Подшипник проверочный", "part_number": "6208", "quantity": 5, "unit": "шт"})
check("главный механик завёл деталь", r.status_code == 200 and r.json().get("success"),
      r.text[:200])
part_id = r.json()["id"]

rows = journal("part_created")
check("заведение детали записано", len(rows) == 1, len(rows))
check("и виден начальный остаток",
      "5" in (rows[0]["details"] or "") and "6208" in (rows[0]["details"] or ""),
      dict(rows[0]))

# Движение свой след пишет в parts_log — в общий журнал не дублируем.
r = chief_mech.post(f"/api/parts/{part_id}/move", json={"quantity": -2})
check("расход проведён", r.status_code == 200, r.text[:200])
conn = sb.db()
moves = conn.execute("SELECT * FROM parts_log WHERE part_id=?", (part_id,)).fetchall()
conn.close()
check("движение записано в свой журнал склада", len(moves) == 1, len(moves))
check("и в общий журнал не продублировано",
      len(journal("part_moved")) == 0, len(journal("part_moved")))

# ── Переписка ───────────────────────────────────────────────────────
r = worker1.post("/api/messenger/conversations/dm", json={"user_id": worker2.id})
check("личная переписка открыта", r.status_code == 200, r.text[:200])
conv_id = r.json()["conversation_id"]

r = worker1.post(f"/api/messenger/conversations/{conv_id}/messages",
                 json={"text": "Секретный текст, которого в журнале быть не должно"})
check("сообщение отправлено", r.status_code == 200, r.text[:200])
msg_id = r.json()["message"]["id"]

check("отправка сообщения в журнал не пишется",
      len(journal("chat_message_sent")) == 0)

r = worker1.delete(f"/api/messenger/messages/{msg_id}")
check("своё сообщение удалено", r.status_code == 200, r.text[:200])
rows = journal("chat_message_deleted")
check("удаление записано фактом", len(rows) == 1, len(rows))
check("и автор виден", (rows[0]["username"] or "") == worker1.full_name, dict(rows[0]))

conn = sb.db()
leaked = conn.execute(
    "SELECT COUNT(*) FROM audit_log WHERE details LIKE '%Секретный текст%' "
    "OR COALESCE(before_json,'') LIKE '%Секретный текст%'").fetchone()[0]
conn.close()
check("текста сообщения в журнале нет ни в одном поле", leaked == 0, leaked)

r = worker1.post("/api/messenger/conversations/group",
                 json={"title": "Проверочная группа", "member_ids": [worker2.id]})
check("группа создана", r.status_code == 200, r.text[:200])
group_id = r.json()["conversation_id"]
check("создание группы в журнал не идёт", len(journal("chat_group_created")) == 0)

r = worker1.delete(f"/api/messenger/conversations/{group_id}/members/{worker2.id}")
check("участник исключён", r.status_code == 200, r.text[:200])
check("исключение записано", len(journal("chat_member_removed")) == 1)

r = worker1.delete(f"/api/messenger/conversations/{group_id}")
check("группа удалена", r.status_code == 200, r.text[:200])
rows = journal("chat_group_deleted")
check("удаление группы записано", len(rows) == 1, len(rows))
check("и сказано, что пропало у всех",
      "всех" in (rows[0]["details"] or ""), dict(rows[0]))

finish("Лаборатория, склад и переписка: журнал по назначению")
