"""
Цепочка сменного отчёта: кто ведёт, кто проверяет, кто подтверждает.

Решение владельца 28.09.2026: отчёт ведут начальник смены и начальник
производства (оператор упаковки больше не заполняет), подтверждает
гл. инженер ИЛИ начальник производства.

Из этого следует правило, без которого связка ломается: раз отчёт
ведут те же люди, что стоят в цепочке, один человек мог бы завести,
сдать и сам же подтвердить — и в аналитику ушли бы цифры, которых
никто, кроме автора, не видел. Поэтому СВОЙ отчёт дальше по цепочке
не двигают: ни проверить, ни подтвердить.

И обратная сторона того же правила: подтвердить можно не только
проверенный отчёт, но и просто сданный. Иначе отчёт, который вёл
начальник смены, попадал бы в тупик — проверить его самому нельзя, а
других начальников смены в ночь может не быть.

Базы временные, боевые не трогаются.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sandbox import Sandbox, check, finish   # noqa: E402

sb = Sandbox()

worker = sb.user("worker", brigade="А")
master = sb.user("shift_supervisor", brigade="А")
master2 = sb.user("shift_supervisor", brigade="А")
prod = sb.user("production_chief")
chief = sb.user("chief_engineer")
mech = sb.user("mechanic")

conn = sb.db()
busy = {row[0] for row in conn.execute(
    "SELECT report_date FROM shift_reports WHERE shift='День' AND brigade='А'")}
conn.close()
free = [f"2026-11-{d:02d}" for d in range(1, 29) if f"2026-11-{d:02d}" not in busy]


def open_report(client, day, brigade="А"):
    return client.post("/api/shift-report/open",
                       json={"report_date": day, "shift": "День", "brigade": brigade})


def add_car(client, report_id, number):
    return client.post(f"/api/shift-report/{report_id}/cars",
                       json={"car_number": number, "pallets_good": 10, "pallets_defect": 1})


# ── Кто может завести черновик ──────────────────────────────────────
r = open_report(worker, free[0])
check("оператор упаковки отчёт больше не заводит", r.status_code == 403,
      f"{r.status_code} {r.text[:120]}")

r = open_report(mech, free[0])
check("механик — тем более", r.status_code == 403, r.status_code)

r = open_report(master, free[0])
check("начальник смены заводит", r.status_code == 200, r.text[:200])
first = r.json()["report"]["id"]

r = open_report(prod, free[1])
check("начальник производства тоже заводит", r.status_code == 200, r.text[:200])
second = r.json()["report"]["id"]

r = add_car(prod, second, "5")
check("и ведёт вагонетки", r.status_code == 200, r.text[:200])

r = add_car(worker, first, "1")
check("а оператор вагонетки не ведёт", r.status_code == 403, r.status_code)

# ── Свой отчёт не проверяют ─────────────────────────────────────────
add_car(master, first, "2")
r = master.post(f"/api/shift-report/{first}/submit")
check("начальник смены сдал свой отчёт", r.status_code == 200, r.text[:200])

r = master.post(f"/api/shift-report/{first}/check")
check("и сам его проверить не может", r.status_code == 400, r.status_code)
check("с объяснением, а не сухим отказом",
      "другой человек" in r.text, r.text[:200])

r = master.post(f"/api/shift-report/{first}/approve")
check("подтвердить свой отчёт ему не положено и по роли",
      r.status_code == 403, r.status_code)

# Права приходят вместе с отчётом — чтобы кнопок не было вовсе.
r = master.get(f"/api/shift-report/{first}")
check("в своём отчёте кнопки «проверено» нет",
      r.json()["report"]["you_can_check"] is False, r.json()["report"])

r = master2.get(f"/api/shift-report/{first}")
check("а у другого начальника смены есть",
      r.json()["report"]["you_can_check"] is True, r.json()["report"])

r = master2.post(f"/api/shift-report/{first}/check")
check("другой начальник смены проверяет", r.status_code == 200, r.text[:200])

# ── Кто подтверждает ────────────────────────────────────────────────
r = master2.post(f"/api/shift-report/{first}/approve")
check("начальник смены не подтверждает", r.status_code == 403, r.status_code)

r = prod.post(f"/api/shift-report/{first}/approve")
check("начальник производства подтверждает", r.status_code == 200, r.text[:200])
check("отчёт подтверждён",
      prod.get(f"/api/shift-report/{first}").json()["report"]["status"] == "approved")

# ── Сданный отчёт можно подтвердить без отдельной проверки ──────────
# Отчёт вёл начальник производства, значит проверить его самому нельзя,
# и ждать не от кого: берёт гл. инженер.
r = prod.post(f"/api/shift-report/{second}/submit")
check("начальник производства сдал свой отчёт", r.status_code == 200, r.text[:200])

r = prod.post(f"/api/shift-report/{second}/approve")
check("и сам же его не подтверждает", r.status_code == 400, r.status_code)

r = chief.get(f"/api/shift-report/{second}")
check("гл. инженер видит, что может подтвердить сданный",
      r.json()["report"]["you_can_approve"] is True, r.json()["report"])

r = chief.post(f"/api/shift-report/{second}/approve")
check("гл. инженер подтверждает сданный отчёт без лишнего шага",
      r.status_code == 200, r.text[:200])

# ── Две пары глаз в любом случае ────────────────────────────────────
conn = sb.db()
rows = conn.execute(
    "SELECT submitted_by, checked_by, approved_by FROM shift_reports WHERE id IN (?, ?)",
    (first, second)).fetchall()
conn.close()
for row in rows:
    who = [row["submitted_by"], row["approved_by"]]
    check("сдал и подтвердил — разные люди", who[0] != who[1], dict(row))

# ── Нормы времени остаются за гл. инженером ─────────────────────────
# Норма пересчитывает все отчёты сразу: вчерашняя уложившаяся смена
# назавтра может стать отстающей. Менять норматив, по которому
# оценивают твою же смену, начальнику производства не положено.
r = prod.put("/api/shift-report/norms", json={"car_minutes": 50, "layer_minutes": 15})
check("начальник производства нормы не меняет", r.status_code == 403, r.status_code)

r = master.put("/api/shift-report/norms", json={"car_minutes": 50, "layer_minutes": 15})
check("начальник смены — тем более", r.status_code == 403, r.status_code)

r = chief.put("/api/shift-report/norms", json={"car_minutes": 50, "layer_minutes": 15})
check("гл. инженер меняет", r.status_code == 200, r.text[:200])

r = prod.get("/api/shift-report/meta")
check("и в интерфейсе у начальника производства кнопки норм нет",
      r.json().get("can_set_norms") is False, r.json().get("can_set_norms"))
check("а вести отчёт он может", r.json().get("can_fill") is True, r.json())
check("и подтверждать тоже", r.json().get("can_approve") is True, r.json())

finish("Сменный отчёт: кто ведёт, кто проверяет, кто подтверждает")
