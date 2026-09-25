"""
История правок: в журнал попадает то, что изменилось, и ничего лишнего.

Зачем этот тест. Правка станка писала одну строку «Изменено
оборудование» и название — по ней нельзя было понять, сменили цех,
службу или просто переименовали. Разница «было → стало» в базе
поддерживалась давно (before_json/after_json), но её почти никто не
заполнял: на боевом из 271 записи поле «было» есть у пятнадцати.

Что здесь ловится:

  • нажатое «Сохранить» без изменений не оставляет записи вовсе —
    иначе журнал засоряется и в нём перестают искать;
  • в запись попадают ТОЛЬКО изменившиеся поля, а не вся строка;
  • пароль не попадает в журнал ни в каком виде;
  • «0» и 0, пустая строка и None не считаются изменением: из базы они
    приходят вперемешку, и журнал полнился бы строками «Скрыт: нет → нет»;
  • имена полей человеческие и зависят от вида записи: «Статус» у
    станка и у документа значат разное.

Временная база, factory.db не трогается.
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services import audit_service as audit

checks = 0


def check(condition, message, extra=None):
    global checks
    checks += 1
    if not condition:
        raise AssertionError(message + (f" — {extra}" if extra is not None else ""))


fd, path = tempfile.mkstemp(suffix=".db")
os.close(fd)
conn = sqlite3.connect(path)
conn.execute("""
CREATE TABLE audit_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, role TEXT, action TEXT,
  target TEXT, details TEXT, created_at TEXT, entity_type TEXT, entity_id INTEGER,
  before_json TEXT, after_json TEXT, reason TEXT)
""")
conn.commit()
conn.close()

import backend.config as config
config.DB_NAME = path
audit.DB_NAME = path

USER = {"username": "chief-engineer", "role": "chief_engineer"}


def entries():
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM audit_log ORDER BY id")]
    conn.close()
    return rows


# ── Ничего не поменялось — записи нет ───────────────────────────────
same = {"name": "Дробилка DTE 117", "location": "Массаподготовка", "discipline": "both"}
changes = audit.log_edit("equipment", 5, same, dict(same), USER)
check(changes == [], "сохранение без правок не считается изменением", changes)
check(len(entries()) == 0, "и записи в журнале не оставляет", entries())

# ── Поменялось одно поле из трёх ────────────────────────────────────
after = dict(same, discipline="electrical")
changes = audit.log_edit("equipment", 5, same, after, USER, name=same["name"])
check(len(changes) == 1, "изменилось одно поле", changes)
check(changes[0]["label"] == "Служба", "имя поля человеческое", changes[0])
check(changes[0]["before"] == "both" and changes[0]["after"] == "electrical",
      "видно, что было и что стало", changes[0])

rows = entries()
check(len(rows) == 1, "запись ровно одна", len(rows))
check(rows[0]["entity_type"] == "equipment" and rows[0]["entity_id"] == 5,
      "запись привязана к станку", rows[0]["target"])

import json
check(json.loads(rows[0]["before_json"]) == {"discipline": "both"},
      "в журнал попало только изменившееся поле, а не вся строка", rows[0]["before_json"])
check("name" not in json.loads(rows[0]["after_json"]),
      "неизменившееся поле в запись не попадает")

# ── Пароль в журнал не попадает ─────────────────────────────────────
audit.log_edit("user", 7,
               {"full_name": "Иванов", "password_hash": "старый", "token": "abc"},
               {"full_name": "Иванов И.", "password_hash": "новый", "token": "xyz"},
               USER)
row = entries()[-1]
raw = (row["before_json"] or "") + (row["after_json"] or "")
check("старый" not in raw and "новый" not in raw, "хеш пароля в журнал не пишется", raw)
check("abc" not in raw and "xyz" not in raw, "токен в журнал не пишется", raw)
check("Иванов" in raw, "а имя пишется", raw)

# ── Ложные изменения из базы ────────────────────────────────────────
check(audit.changed_fields({"hidden": 0}, {"hidden": "0"}) == [],
      "0 и «0» — одно и то же")
check(audit.changed_fields({"note": None}, {"note": ""}) == [],
      "пустое осталось пустым — не изменение")
check(audit.changed_fields({"health": 80}, {"health": 90}) != [],
      "настоящее изменение числа видно")

# ── Имя поля зависит от вида записи ─────────────────────────────────
check(audit.field_label("status", "equipment") == "Состояние станка",
      "у станка «статус» — это его состояние")
check(audit.field_label("status", "document") == "Проверка документа",
      "у документа «статус» — стадия проверки")
check(audit.field_label("location") == "Цех", "общее имя поля берётся из словаря")
check(audit.field_label("никому_не_известное_поле") == "никому_не_известное_поле",
      "неизвестное поле показывается как есть, а не прячется")

# ── История по записи ───────────────────────────────────────────────
history = audit.get_audit_log_by_target(entity_type="equipment", entity_id=5)
check(len(history) == 1, "история станка находится по его id", len(history))
check(audit.get_audit_log_by_target(entity_type="equipment", entity_id=999) == [],
      "у станка без правок история пустая")

os.unlink(path)
print(f"OK — проверок: {checks}")
