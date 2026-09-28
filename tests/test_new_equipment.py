"""
Завели новый станок — что с ним по всей системе.

Проверка родилась из сквозного прогона по копии боевой базы. Нашлось
три вещи, и все три — не про новый станок, а про любой:

  • станка без работ в графике ТО не было видно НИГДЕ. Страница
    строилась только по работам, и «ничего не просрочено» читалось как
    «всё в порядке». Новый станок молча оставался без обслуживания;

  • правка карточки на странице «Оборудование» не передавала службу, а
    сервер записывал всё, что пришло, — каждое «Сохранить» МОЛЧА
    СТИРАЛО службу станка. На боевой базе так осталось пять станков с
    пустой службой (Дробилка DTE 117, Дезинтегратор PL 601, Смеситель
    СМК 126, Экструдер MAGNA 575, Генератор тепла 1500), и их не видел
    ни механик, ни энергетик: обе страницы отбирают по этому полю;

  • та же форма писала в поле «этап» НАЗВАНИЕ ЦЕХА (stage: location),
    и у восьми станков этап оказался словами: «Массаподготовка» вместо
    «mass». В «Структуре» на этапе «Массоподготовка» показывалось 2
    станка из 7.

Плюс закрыты две ручки графика ТО: заведение и удаление работы ничего
не писали в журнал, а удалять мог кто угодно из главных, кроме
энергетика — свою часть графика он вести не мог.

Работает на копии базы (sandbox), боевая не трогается.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sandbox import Sandbox, check, finish

sb = Sandbox()
eng = sb.user("chief_engineer")
mech = sb.user("mechanic")

NAME = "Проверочный станок (тест нового оборудования)"

# ── Заведение ───────────────────────────────────────────────────────
r = eng.post("/api/structure/equipment", json={
    "name": NAME, "type": "Дробилка", "stage": "forming",
    "discipline": "mechanical", "location": "Формовка",
})
check("станок заводится", r.status_code == 200 and r.json().get("success"), r.text[:200])
eid = r.json()["id"]

data = eng.get("/api/structure/equipment").json()
check("виден в структуре", any(e["name"] == NAME for e in data.get("equipment", [])))

data = eng.get("/api/equipment").json()
check("виден в общем списке", NAME in json.dumps(data, ensure_ascii=False))

for path in (f"/api/equipment/{eid}", f"/api/equipment/{eid}/journal",
             f"/api/equipment/{eid}/passport", f"/api/equipment/{eid}/documents"):
    check(f"открывается {path.replace(str(eid), '{id}')}",
          eng.get(path).status_code == 200)

# ── График ТО: станок без работ должен быть виден ────────────────────
data = eng.get("/api/maintenance/schedule?year=2026").json()
ids = [e["id"] for e in data.get("no_schedule", [])]
check("станок без работ попал в «Без графика ТО»", eid in ids,
      f"в списке {len(ids)} станков, нашего нет")

works = [w for w in data.get("schedule", []) if w.get("equipment_id") == eid]
check("работ у него правда нет", not works, works)

# Завели работу — станок должен уйти из списка «без графика».
r = eng.post("/api/maintenance/schedule", json={
    "equipment_id": eid, "work_name": "Смазка подшипников",
    "months": "3,6,9,12", "year": 2026, "responsible": "Гл. механик",
})
check("работа в график добавляется", r.status_code == 200, r.text[:200])
work_id = r.json()["id"]

data = eng.get("/api/maintenance/schedule?year=2026").json()
check("станок с работами из списка «без графика» ушёл",
      eid not in [e["id"] for e in data.get("no_schedule", [])])

# ── Журнал на изменения графика ─────────────────────────────────────
row = sb.db().execute(
    "SELECT action, details FROM audit_log WHERE target = ? ORDER BY id DESC LIMIT 1",
    (f"maintenance_schedule:{work_id}",)).fetchone()
check("заведение работы записано в журнал",
      row is not None and row["action"] == "maintenance_work_added",
      dict(row) if row else "записи нет")
check("в записи видно, что за работа",
      row is not None and "Смазка подшипников" in (row["details"] or ""),
      dict(row) if row else "")

# Механик (не главный) график не правит: работа исчезнет вместе с
# просрочкой по ней, а это то же по последствиям, что снять отметку.
r = mech.delete(f"/api/maintenance/schedule/{work_id}")
check("механик работу из графика не удаляет", r.status_code == 403, r.status_code)

r = eng.delete(f"/api/maintenance/schedule/{work_id}")
check("главный инженер удаляет", r.status_code == 200, r.text[:200])

row = sb.db().execute(
    "SELECT action, details, before_json FROM audit_log WHERE target = ? ORDER BY id DESC LIMIT 1",
    (f"maintenance_schedule:{work_id}",)).fetchone()
check("удаление работы записано в журнал",
      row is not None and row["action"] == "maintenance_work_deleted",
      dict(row) if row else "записи нет")
check("в записи осталось название работы и станок",
      row is not None and "Смазка подшипников" in (row["details"] or "")
      and NAME in (row["details"] or ""),
      dict(row)["details"] if row else "")

# ── Служба не стирается молча ───────────────────────────────────────
# Страница «Оборудование» раньше присылала только название, тип и цех.
# Повторяем ровно такой запрос: служба должна остаться на месте.
r = eng.put(f"/api/settings/equipment/{eid}",
            json={"name": NAME, "type": "Дробилка", "location": "Формовка"})
check("правка без службы проходит", r.status_code == 200, r.text[:200])

row = sb.db().execute("SELECT stage, discipline FROM equipment WHERE id = ?", (eid,)).fetchone()
check("служба НЕ стёрлась", row["discipline"] == "mechanical", dict(row))
check("этап тоже на месте", row["stage"] == "forming", dict(row))

# А явное «— не указана —» (пустая строка) службу снимает: человек так решил.
r = eng.put(f"/api/settings/equipment/{eid}",
            json={"name": NAME, "type": "Дробилка", "location": "Формовка",
                  "stage": "forming", "discipline": ""})
row = sb.db().execute("SELECT discipline FROM equipment WHERE id = ?", (eid,)).fetchone()
check("явное «не указана» службу снимает", row["discipline"] is None, dict(row))

# ── Станок без службы виден обеим службам ───────────────────────────
# Отбор делает страница: equipment.js, функция inDiscipline. Пустая
# служба — незаполненное поле, а не «чужой станок»: прятать его с обеих
# страниц значит потерять станок совсем.
js = (Path(__file__).resolve().parent.parent / "frontend/static/equipment.js").read_text(encoding="utf-8")
check("отбор по службе вынесен в одну функцию", "function inDiscipline(" in js)
check("пустая служба не прячет станок", "|| !value" in js,
      "правило отбора снова отбрасывает станки с пустой службой")
check("в строке станка есть пометка «служба не указана»",
      "служба не указана" in js)

finish("Новый станок: заведение и связи")
