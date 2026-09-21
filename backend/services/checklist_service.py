"""
Как часто делают обход смены — и когда он просрочен.

СРОК ЗАДАЛ ВЛАДЕЛЕЦ (21.09.2026): «обход смены надо делать 1 раз в
неделю». До этого срока не было нигде: страницы просто показывали,
были обходы за выбранный период или нет. На вкладке «Сегодня» это
читалось как «обход не сделали» — хотя по недельному сроку сегодня
его и не должно быть. Страница не имеет права называть нарушением то,
что нарушением не является: после пары таких упрёков перестают верить
и настоящим.

Срок живёт здесь, в одном месте. Все страницы — «Обход смены»,
«Аналитика», «Отчёты», колокольчик — спрашивают у этого модуля, а не
считают дни у себя: иначе один и тот же обход в трёх местах окажется
то просроченным, то нет.
"""

import sqlite3
from datetime import datetime, timedelta

from backend.config import DB_NAME

# Раз в неделю. Менять здесь — остальное подстроится.
EVERY_DAYS = 7

# За сколько дней до срока начинаем напоминать. Обход занимает время и
# требует обойти цех: сказать «пора» в последний день — значит почти
# наверняка получить просрочку.
REMIND_BEFORE_DAYS = 2


def get_connection():
    conn = sqlite3.connect(DB_NAME, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _parse(stamp):
    text = str(stamp or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:len(fmt) + 2].strip(), fmt)
        except ValueError:
            continue
    return None


def last_round() -> dict | None:
    """Последний сданный обход. Черновики не считаются — их не сдавали."""
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT id, username, full_name, shift, started_at, finished_at,
                   total_count, ok_count, warn_count, bad_count
            FROM checklist_rounds
            ORDER BY started_at DESC LIMIT 1
            """
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def status() -> dict:
    """
    Пора ли делать обход.

    Состояния честные и разные:
      never    — обходов не было ни одного (сейчас в базе именно так);
      ok       — сделан, срок не подошёл;
      soon     — срок на днях;
      overdue  — просрочен, и сказано на сколько.
    """
    row = last_round()
    today = datetime.now().date()

    if not row:
        return {
            "every_days": EVERY_DAYS,
            "state": "never",
            "last_round": None,
            "days_since": None,
            "due_date": None,
            "overdue_days": None,
            "text": f"Обход делают раз в {EVERY_DAYS} дней. Ни одного обхода ещё не было.",
            "short": "обходов ещё не было",
        }

    started = _parse(row.get("started_at"))
    if not started:
        return {
            "every_days": EVERY_DAYS, "state": "never", "last_round": row,
            "days_since": None, "due_date": None, "overdue_days": None,
            "text": "У последнего обхода не разобрать дату — срок посчитать не из чего.",
            "short": "дата последнего обхода непонятна",
        }

    days_since = (today - started.date()).days
    due = started.date() + timedelta(days=EVERY_DAYS)
    left = (due - today).days
    when = f"{started.day:02d}.{started.month:02d}"

    if left < 0:
        state = "overdue"
        text = (f"Обход просрочен на {-left} дн.: последний был {when}, "
                f"делать надо раз в {EVERY_DAYS} дней.")
    elif left <= REMIND_BEFORE_DAYS:
        state = "soon"
        text = (f"Обход пора делать: последний был {when}, "
                f"срок — {due.day:02d}.{due.month:02d}.")
    else:
        state = "ok"
        text = (f"Обход сделан {when}. Следующий — до {due.day:02d}.{due.month:02d} "
                f"(раз в {EVERY_DAYS} дней).")

    return {
        "every_days": EVERY_DAYS,
        "state": state,
        "last_round": row,
        "days_since": days_since,
        "due_date": due.isoformat(),
        "days_left": left,
        "overdue_days": -left if left < 0 else 0,
        "text": text,
        "short": f"последний {when}",
    }
