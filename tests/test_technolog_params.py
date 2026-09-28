"""
Нормы технолога: кто может их менять и остаётся ли след.

Зачем. Нормы — это то, с чем сверяют линию: влажность массы, давление
в экструдере, температура обжига. Аудит изменяющих ручек показал по
этому файлу четыре дыры сразу:

  • «завести стартовый набор» (POST /api/technolog/params/seed) был
    открыт ЛЮБОМУ вошедшему — 24 нормы мог создать рабочий;
  • создание, правка и удаление нормы не писались в общий журнал: кто
    поменял допуск, приходилось искать глазами в другой таблице;
  • правка обнуляла то, чего не прислали: отправили один минимум —
    максимум и цель становились пустыми. Тот же изъян, из-за которого
    у станков стиралась служба.

Здесь ловится каждая из четырёх. Базы временные, боевые не трогаются.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sandbox import Sandbox, check, finish   # noqa: E402

sb = Sandbox()

tech = sb.user("technologist")
worker = sb.user("worker")
mech = sb.user("mechanic")


def journal(action):
    conn = sb.db()
    rows = conn.execute(
        "SELECT * FROM audit_log WHERE action = ? ORDER BY id DESC", (action,)).fetchall()
    conn.close()
    return rows


# ── Стартовый набор: не всякому вошедшему ───────────────────────────
r = worker.post("/api/technolog/params/seed")
check("рабочий не заводит нормы", r.status_code == 403, r.status_code)

r = mech.post("/api/technolog/params/seed")
check("механик не заводит нормы", r.status_code == 403, r.status_code)

# В копии боевой базы стартовый набор уже заведён, поэтому убираем одну
# норму — иначе «завести» нечего и проверять нечего.
conn = sb.db()
conn.execute("DELETE FROM technolog_params WHERE stage='Упаковка' AND param_name='Брак (норма)'")
conn.commit()
conn.close()

r = tech.post("/api/technolog/params/seed")
check("технолог заводит", r.status_code == 200 and r.json().get("success"), r.text[:150])
added = r.json().get("added", 0)
check("заводится только недостающее", added == 1, added)
check("и это записано в журнал", len(journal("technolog_params_seeded")) == 1,
      len(journal("technolog_params_seeded")))

r = tech.post("/api/technolog/params/seed")
check("повторное нажатие ничего не заводит", r.json().get("added") == 0, r.json())
check("и следа в журнале не оставляет",
      len(journal("technolog_params_seeded")) == 1,
      len(journal("technolog_params_seeded")))

# ── Создание ────────────────────────────────────────────────────────
r = worker.post("/api/technolog/params", json={"stage": "Обжиг", "param_name": "Проверка"})
check("рабочий не создаёт норму", r.status_code == 403, r.status_code)

r = tech.post("/api/technolog/params", json={
    "stage": "Обжиг", "param_name": "Разрежение в печи", "unit": "Па",
    "min_val": 10, "max_val": 30, "target_val": 20})
check("технолог создаёт норму", r.status_code == 200 and r.json().get("success"), r.text[:150])
param_id = r.json()["id"]
rows = journal("technolog_param_added")
check("создание записано в журнал", len(rows) == 1, len(rows))
check("и видно, что именно завели",
      "Разрежение в печи" in (rows[0]["details"] or ""), dict(rows[0]))

# ── Правка: частичная не стирает соседние границы ───────────────────
r = worker.put(f"/api/technolog/params/{param_id}", json={"min_val": 5})
check("рабочий не правит норму", r.status_code == 403, r.status_code)

r = tech.put(f"/api/technolog/params/{param_id}", json={"min_val": 12})
check("технолог правит", r.status_code == 200 and r.json().get("changed"), r.text[:150])

conn = sb.db()
row = conn.execute("SELECT * FROM technolog_params WHERE id = ?", (param_id,)).fetchone()
conn.close()
check("минимум изменился", row["min_val"] == 12, dict(row))
check("максимум НЕ обнулён частичной правкой", row["max_val"] == 30, dict(row))
check("цель НЕ обнулена частичной правкой", row["target_val"] == 20, dict(row))

rows = journal("technolog_param_updated")
check("правка попала в общий журнал", len(rows) == 1, [dict(x) for x in rows])
check("с «было → стало»",
      "10" in (rows[0]["before_json"] or "") and "12" in (rows[0]["after_json"] or ""),
      dict(rows[0]))

conn = sb.db()
hist = conn.execute("SELECT * FROM technolog_params_log WHERE param_id = ?", (param_id,)).fetchall()
conn.close()
check("своя история параметра тоже записана", len(hist) == 1, len(hist))

# Пустое «Сохранить» следа не оставляет.
r = tech.put(f"/api/technolog/params/{param_id}", json={"min_val": 12})
check("правка без изменений не пишется", r.json().get("changed") is False, r.json())
check("и историю не засоряет", len(journal("technolog_param_updated")) == 1)

conn = sb.db()
hist2 = conn.execute("SELECT COUNT(*) FROM technolog_params_log WHERE param_id = ?",
                     (param_id,)).fetchone()[0]
conn.close()
check("и в своей истории параметра тоже", hist2 == 1, hist2)

# ── Парная проверка: сценарий должен уметь покраснеть ──────────────
#
# Старая ручка брала значения через request.get(...): чего нет в
# запросе — то None, и оно уходило в UPDATE как настоящая пустота.
# Воспроизводим это, присылая пустые границы ЯВНО: так и должно
# стирать. Если бы не стирало — проверки выше ничего не значили бы.
r = tech.put(f"/api/technolog/params/{param_id}",
             json={"min_val": 12, "max_val": None, "target_val": None})
conn = sb.db()
wiped = conn.execute("SELECT * FROM technolog_params WHERE id = ?", (param_id,)).fetchone()
conn.close()
check("контрольная: явно присланная пустота действительно стирает границы",
      wiped["max_val"] is None and wiped["target_val"] is None, dict(wiped))

# Возвращаем как было — дальше сценарий смотрит на эти числа.
tech.put(f"/api/technolog/params/{param_id}", json={"max_val": 30, "target_val": 20})
conn = sb.db()
back = conn.execute("SELECT * FROM technolog_params WHERE id = ?", (param_id,)).fetchone()
conn.close()
check("и возвращаются тем же способом", back["max_val"] == 30, dict(back))

# ── Удаление ────────────────────────────────────────────────────────
r = mech.delete(f"/api/technolog/params/{param_id}")
check("механик не удаляет норму", r.status_code == 403, r.status_code)

r = tech.delete(f"/api/technolog/params/{param_id}")
check("технолог удаляет", r.status_code == 200 and r.json().get("success"), r.text[:150])

rows = journal("technolog_param_deleted")
check("удаление записано в журнал", len(rows) == 1, len(rows))
check("и в записи видно, что удалили и с какими границами",
      "Разрежение в печи" in (rows[0]["details"] or "")
      and "12" in (rows[0]["before_json"] or ""), dict(rows[0]))

conn = sb.db()
left = conn.execute("SELECT COUNT(*) FROM technolog_params_log WHERE param_id = ?",
                    (param_id,)).fetchone()[0]
conn.close()
check("история правок после удаления нормы не пропала", left == 3, left)

r = tech.delete(f"/api/technolog/params/{param_id}")
check("повторное удаление отвечает честно, а не «успешно»",
      r.json().get("success") is False, r.json())

# ── Право приходит с сервера, а не выписано в странице ──────────────
analyst = sb.user("analyst")
r = analyst.get("/api/technolog/params")
check("аналитик видит нормы", r.status_code == 200, r.status_code)
check("но править их ему не положено", r.json().get("can_edit") is False, r.json().get("can_edit"))

r = tech.get("/api/technolog/params")
check("технологу положено", r.json().get("can_edit") is True, r.json().get("can_edit"))

page = (Path(__file__).resolve().parent.parent
        / "frontend" / "templates" / "technolog.html").read_text(encoding="utf-8")
check("страница берёт право с сервера, а не сверяет роли своим списком",
      "canEditParams=pr.value.can_edit===true" in page
      and "['admin','director','chief_engineer','technologist'].includes" not in page)
check("и не зовёт «завести набор» у того, кому нельзя",
      "if(!allParams.length&&canEditParams)" in page)

finish("Нормы технолога: права и журнал")
