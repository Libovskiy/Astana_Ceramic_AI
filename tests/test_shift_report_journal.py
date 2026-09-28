"""
Сменный отчёт: частичная правка не стирает выпуск, а путь отчёта виден.

Зачем. По этому отчёту считают выпуск смены — сколько поддонов годных,
сколько в брак. Аудит нашёл здесь две беды сразу.

Первая: правка вагонетки обнуляла то, чего не прислали. Модель запроса
подставляла значения по умолчанию («» и 0), и они уходили в UPDATE как
настоящие. Прислали одно время слоя — поддоны обнулились. Это третье
место с одним и тем же изъяном: до него так же стиралась служба станка
и границы норм технолога.

Вторая: весь путь отчёта — открыт, сдан, проверен, подтверждён,
возвращён, изменены нормы — не писался в журнал вовсе. Кто подтвердил
выпуск завода, установить было нельзя.

Журнал при этом разный по подробности, и это нарочно:
  • путь отчёта — одной строкой;
  • нормы и удаление вагонетки — «было → стало»;
  • правка вагонетки — только после возврата с проверки: пока идёт
    смена, правки в черновике это ввод данных, а не изменение записи,
    которую кто-то уже видел. Иначе журнал из 281 записи забился бы за
    неделю десятками вагонеток в смену.

Базы временные, боевые не трогаются.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sandbox import Sandbox, check, finish   # noqa: E402

sb = Sandbox()

worker = sb.user("worker", brigade="А")
master = sb.user("shift_supervisor", brigade="А")
chief = sb.user("chief_engineer")


def journal(action):
    conn = sb.db()
    rows = conn.execute("SELECT * FROM audit_log WHERE action=? ORDER BY id DESC",
                        (action,)).fetchall()
    conn.close()
    return rows


def car_row(car_id):
    conn = sb.db()
    row = conn.execute("SELECT * FROM shift_report_cars WHERE id=?", (car_id,)).fetchone()
    conn.close()
    return dict(row)


# ── Открытие ────────────────────────────────────────────────────────
# Дата берётся такая, которой в копии базы заведомо нет: иначе отчёт
# уже открыт кем-то на заводе, и «открытие» не случится.
conn = sb.db()
busy = {row[0] for row in conn.execute(
    "SELECT report_date FROM shift_reports WHERE shift='День' AND brigade='А'")}
conn.close()
free = [f"2026-12-{d:02d}" for d in range(1, 29) if f"2026-12-{d:02d}" not in busy]
DAY, NEXT_DAY = free[0], free[1]

r = worker.post("/api/shift-report/open",
                json={"report_date": DAY, "shift": "День", "brigade": "А"})
check("смена открывается", r.status_code == 200 and r.json().get("success"), r.text[:200])
report_id = r.json()["report"]["id"]
check("открытие записано одной строкой", len(journal("shift_report_opened")) == 1,
      len(journal("shift_report_opened")))

r = worker.post("/api/shift-report/open",
                json={"report_date": DAY, "shift": "День", "brigade": "А"})
check("повторный заход на ту же смену журнал не засоряет",
      len(journal("shift_report_opened")) == 1, len(journal("shift_report_opened")))

# ── Вагонетка: частичная правка не стирает выпуск ───────────────────
r = worker.post(f"/api/shift-report/{report_id}/cars", json={
    "car_number": "12", "brick_type": "М150",
    "layer1_at": "08:10", "layer2_at": "08:40", "layer3_at": "09:05",
    "finished_at": "09:30", "pallets_good": 18, "pallets_defect": 2,
    "defect_reason": "скол", "defect_note": "угол"})
check("вагонетка заведена", r.status_code == 200 and r.json().get("success"), r.text[:200])
car_id = r.json()["car"]["id"]

# Прислали ОДНО поле — остальные должны остаться как были.
r = worker.put(f"/api/shift-report/cars/{car_id}", json={"layer3_at": "09:15"})
check("частичная правка принята", r.status_code == 200, r.text[:200])

row = car_row(car_id)
check("исправленное поле изменилось", row["layer3_at"] == "09:15", row)
check("годные поддоны НЕ обнулены", row["pallets_good"] == 18, row)
check("брак НЕ обнулён", row["pallets_defect"] == 2, row)
check("номер вагонетки на месте", str(row["car_number"]) == "12", row)
check("марка кирпича на месте", row["brick_type"] == "М150", row)
check("первое время слоя на месте", row["layer1_at"] == "08:10", row)
check("причина брака на месте", row["defect_reason"] == "скол", row)

# Присланная пустая строка по-прежнему очищает: это осознанное действие.
r = worker.put(f"/api/shift-report/cars/{car_id}", json={"defect_note": ""})
check("явно присланная пустота очищает поле", car_row(car_id)["defect_note"] == "",
      car_row(car_id))
check("и соседние поля при этом целы", car_row(car_id)["pallets_good"] == 18,
      car_row(car_id))

# ── Парная проверка: а сценарий вообще чувствителен? ────────────────
#
# Зелёная проверка выше стоит ровно столько, сколько стоит её
# способность покраснеть. В первый раз она прошла обманом: номер
# вагонетки был обязательным, частичный запрос отлетал с 422, и
# «поддоны не обнулились» выполнялось само собой — при полностью
# сломанном коде.
#
# Поэтому здесь воспроизводится СТАРОЕ поведение: старая ручка звала
# службу с полным словарём, где за непереданные поля стояли значения
# по умолчанию («» и 0). Если так сделать, выпуск действительно
# стирается — значит проверки выше не выполняются вхолостую.
from backend.services import shift_report_service as svc   # noqa: E402

as_old_code_did = {"car_number": "12", "brick_type": "", "layer1_at": "",
                   "layer2_at": "", "layer3_at": "09:15", "finished_at": "",
                   "pallets_good": 0, "pallets_defect": 0,
                   "defect_reason": "", "defect_note": ""}
svc.update_car(car_id, as_old_code_did)
wiped = car_row(car_id)
check("контрольная: по-старому выпуск действительно стирался",
      wiped["pallets_good"] == 0 and wiped["layer1_at"] == "", wiped)

# Возвращаем как было — дальше по сценарию нужны настоящие числа.
svc.update_car(car_id, {"pallets_good": 18, "pallets_defect": 2,
                        "layer1_at": "08:10", "layer2_at": "08:40",
                        "brick_type": "М150", "defect_reason": "скол"})
check("и восстановление работает тем же способом",
      car_row(car_id)["pallets_good"] == 18, car_row(car_id))

check("правка черновика в журнал не пишется",
      len(journal("shift_report_car_updated")) == 0,
      len(journal("shift_report_car_updated")))

# ── Путь отчёта ─────────────────────────────────────────────────────
r = worker.post(f"/api/shift-report/{report_id}/submit")
check("отчёт сдан", r.status_code == 200, r.text[:200])
rows = journal("shift_report_submitted")
check("сдача записана", len(rows) == 1, len(rows))
check("и в строке видно выпуск смены",
      "18" in (rows[0]["details"] or ""), dict(rows[0]))

r = master.post(f"/api/shift-report/{report_id}/return", json={"comment": "Проверь вагонетку 12"})
check("мастер вернул отчёт", r.status_code == 200, r.text[:200])
rows = journal("shift_report_returned")
check("возврат записан с причиной", len(rows) == 1 and "вагонетку 12" in rows[0]["details"],
      [dict(x) for x in rows])

# После возврата правка — это уже изменение записи, которую видели.
r = worker.put(f"/api/shift-report/cars/{car_id}", json={"pallets_good": 17})
check("правка после возврата принята", r.status_code == 200, r.text[:200])
rows = journal("shift_report_car_updated")
check("и записана в журнал", len(rows) == 1, len(rows))
check("с «было → стало»",
      "18" in (rows[0]["before_json"] or "") and "17" in (rows[0]["after_json"] or ""),
      dict(rows[0]))

worker.post(f"/api/shift-report/{report_id}/submit")
r = master.post(f"/api/shift-report/{report_id}/check")
check("мастер проверил", r.status_code == 200, r.text[:200])
check("проверка записана", len(journal("shift_report_checked")) == 1)

r = chief.post(f"/api/shift-report/{report_id}/approve")
check("главный инженер подтвердил", r.status_code == 200, r.text[:200])
rows = journal("shift_report_approved")
check("подтверждение записано", len(rows) == 1, len(rows))
check("и видно, кто подтвердил",
      (rows[0]["username"] or "").startswith("Проверка chief_engineer")
      or rows[0]["role"] == "chief_engineer", dict(rows[0]))

# ── Удаление вагонетки: «было → стало» ──────────────────────────────
r = worker.post("/api/shift-report/open",
                json={"report_date": NEXT_DAY, "shift": "День", "brigade": "А"})
second = r.json()["report"]["id"]
r = worker.post(f"/api/shift-report/{second}/cars",
                json={"car_number": "7", "pallets_good": 20, "pallets_defect": 1})
gone_id = r.json()["car"]["id"]

r = worker.delete(f"/api/shift-report/cars/{gone_id}")
check("вагонетка убрана", r.status_code == 200, r.text[:200])
rows = journal("shift_report_car_deleted")
check("удаление записано", len(rows) == 1, len(rows))
check("и видно, сколько поддонов исчезло",
      "20" in (rows[0]["details"] or "") and "20" in (rows[0]["before_json"] or ""),
      dict(rows[0]))

# ── Нормы: «было → стало» ───────────────────────────────────────────
r = worker.put("/api/shift-report/norms", json={"car_minutes": 40, "layer_minutes": 12})
check("рабочий нормы не меняет", r.status_code == 403, r.status_code)

conn = sb.db()
conn.close()
r = chief.put("/api/shift-report/norms", json={"car_minutes": 44, "layer_minutes": 13})
check("главный инженер меняет нормы", r.status_code == 200, r.text[:200])
rows = journal("shift_report_norms_changed")
check("смена норм записана", len(rows) == 1, len(rows))
check("с «было → стало»",
      "44" in (rows[0]["after_json"] or "") and "44" in (rows[0]["details"] or ""),
      dict(rows[0]))

r = chief.put("/api/shift-report/norms", json={"car_minutes": 44, "layer_minutes": 13})
check("те же нормы повторно — записи нет",
      len(journal("shift_report_norms_changed")) == 1,
      len(journal("shift_report_norms_changed")))

finish("Сменный отчёт: выпуск не стирается, путь виден")
