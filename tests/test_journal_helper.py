"""
Строки журнала считаем свои, а не все подряд.

Одна и та же ошибка ловилась руками трижды за две недели — в сменном
отчёте, в регламентах и в нормах технолога. Выглядела она всегда
одинаково: проверка считает строки «по всей таблице», на чистой базе
разработчика их ровно столько, сколько она сама записала, а на копии
боевой базы к ним прибавляется работа завода, и проверка падает не
от поломки, а от того, что люди работали.

Поэтому теперь есть sb.journal(). Здесь проверяется он сам и то, что
мимо него больше не ходят:

  «не считает чужое» — строки, которые были в базе до старта
  проверки, в выдачу не попадают;

  парная «считает своё» — то, что проверка сделала сама, попадает
  сразу же. Без этой пары первая проверка зелёная и на пустой
  выдаче: отбор, который не отдаёт ничего, чужого тоже не отдаёт.

Боевые данные не трогаются: песочница работает на копии.

Запуск (из корня проекта): python tests/test_journal_helper.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from sandbox import Sandbox, check, finish

sb = Sandbox()

# ── Чужие строки остаются за бортом ─────────────────────────────────
conn = sb.db()
before = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
# Действие, которое в копии уже есть: берём самое частое из тех, что
# записаны ДО старта проверки.
row = conn.execute(
    "SELECT action, COUNT(*) n FROM audit_log WHERE id <= ? GROUP BY action "
    "ORDER BY n DESC LIMIT 1", (sb.journal_base,)
).fetchone()
conn.close()

check("в копии боевой базы журнал не пуст", before > 0, before)

if row:
    check(
        f"чужие строки «{row['action']}» ({row['n']} шт) не попадают в выдачу",
        len(sb.journal(row["action"])) == 0,
        [dict(x) for x in sb.journal(row["action"])][:2],
    )
    check("и в общей выдаче их тоже нет", len(sb.journal()) == 0, len(sb.journal()))

# ── Парная: своё видно сразу ────────────────────────────────────────
master = sb.user("shift_supervisor", brigade="А")

conn = sb.db()
busy = {r[0] for r in conn.execute(
    "SELECT report_date FROM shift_reports WHERE shift='День' AND brigade='А'")}
conn.close()
free = [f"2026-12-{d:02d}" for d in range(1, 29) if f"2026-12-{d:02d}" not in busy]

r = master.post("/api/shift-report/open",
                json={"report_date": free[0], "shift": "День", "brigade": "А"})
check("смена открылась", r.status_code == 200, r.text[:120])

mine = sb.journal("shift_report_opened")
check("своя строка в выдаче есть", len(mine) == 1, len(mine))
check("и это именно она", free[0] in (mine[0]["details"] or ""), dict(mine[0]) if mine else {})

check("отбор по действию не тащит соседние", len(sb.journal()) >= 1
      and all(x["action"] == "shift_report_opened" for x in mine))


# ── Мимо помощника больше не ходят ──────────────────────────────────
# Та самая ошибка в исходном виде: «SELECT ... FROM audit_log WHERE
# action = ?» без отсечки. Если такое снова появится, пусть падает
# здесь, а не через две недели на боевой копии.
offenders = []
for path in sorted((ROOT / "tests").glob("test_*.py")):
    if path.name == "test_journal_helper.py":
        continue
    text = path.read_text(encoding="utf-8")
    if "CREATE TABLE audit_log" in text:
        continue          # тест строит свою базу с нуля — ему можно
    for match in re.finditer(r"FROM audit_log\s+WHERE\s+action", text):
        line_no = text[:match.start()].count("\n") + 1
        line = text.splitlines()[line_no - 1].strip()
        if "id >" in line or "id>" in line:
            continue
        offenders.append(f"{path.name}:{line_no}  {line[:80]}")

check(
    "никто не считает журнал по всей таблице",
    not offenders,
    offenders + ["— берите sb.journal(action), он отдаёт только строки этой проверки"],
)

finish("Журнал: считаем своё")
