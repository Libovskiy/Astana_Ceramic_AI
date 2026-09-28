"""
Тишина датчиков: два разных состояния, журнал перерывов, правила push.

Зачем. Раньше на весь вопрос «идёт ли сбор» была одна цифра — сколько
минут назад приходили данные. По ней нельзя понять, что чинить:
выключенный компьютер со сбором и разлогиненная панель выглядели
одинаково. А на страницах последние известные значения показывались
как живые: за 17 дней до 24.09 в истории 37 перерывов внутри рабочего
дня, самый длинный 83 минуты, и всё это время цифры на экране стояли.

Что здесь ловится:

  • «расширение не на связи» (запросов нет) и «панель не отвечает»
    (запросы идут, данных нет) — это разные состояния с разными
    виноватыми;
  • перерыв заводится один раз и закрывается сам, когда данные
    вернулись, с честной длительностью;
  • уведомление уходит ОДНО на перерыв и только после своего порога;
  • ночью не уходит вовсе, а утром уходит одной строкой;
  • адресаты берутся из настроек: пустой список — не слать никому;
  • пороги — настройка, а не число в коде.

Время везде подставляется, часов ждать не надо. Базы временные.
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

fd, factory = tempfile.mkstemp(suffix=".db"); os.close(fd)
fd, monitoring = tempfile.mkstemp(suffix=".db"); os.close(fd)

os.environ["ACAI_DB"] = factory
os.environ["ACAI_MONITORING_DB"] = monitoring

from backend.services import app_settings_service as settings_store  # noqa: E402
from backend.services import sensor_health_service as health  # noqa: E402

settings_store.DB_NAME = factory
health.DB_NAME = factory
health.DB_PATH = monitoring

conn = sqlite3.connect(factory)
conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, "
             "full_name TEXT, role TEXT, is_active INTEGER DEFAULT 1)")
conn.execute("INSERT INTO users (id, username, role) VALUES (1,'chief-engineer','chief_engineer')")
conn.execute("INSERT INTO users (id, username, role) VALUES (2,'petrov','shift_supervisor')")
conn.commit(); conn.close()

mon = sqlite3.connect(monitoring)
mon.execute("CREATE TABLE sensor_readings (id INTEGER PRIMARY KEY, "
            "sensor_name TEXT, value TEXT, recorded_at TEXT)")
mon.commit(); mon.close()

checks = 0
sent: list = []


def check(condition, message, extra=None):
    global checks
    checks += 1
    if not condition:
        raise AssertionError(message + (f" — {extra}" if extra is not None else ""))


def catcher(roles, users, title, body):
    sent.append({"roles": list(roles), "users": list(users),
                 "title": title, "body": body})


def reading(at: datetime):
    mon = sqlite3.connect(monitoring)
    mon.execute("INSERT INTO sensor_readings (sensor_name, value, recorded_at) "
                "VALUES ('конвейер_1_гц', '50', ?)", (at.strftime("%Y-%m-%d %H:%M:%S"),))
    mon.commit(); mon.close()


DAY = datetime(2026, 9, 28, 10, 0, 0)     # понедельник, рабочее время
NIGHT = datetime(2026, 9, 28, 22, 30, 0)
MORNING = datetime(2026, 9, 29, 8, 10, 0)

# ── Пороги по умолчанию ─────────────────────────────────────────────
conf = health.settings()
check(conf["silence_minutes"] == 10, "порог тишины по умолчанию 10 минут", conf)
check(conf["push_after_minutes"] == 30, "уведомление после 30 минут", conf)
check(conf["alert_roles"] == ["chief_engineer"],
      "по умолчанию пишем главному инженеру", conf)

# ── Данных не было никогда ──────────────────────────────────────────
check(health.state(DAY)["state"] == "never",
      "пустая история — «не было ни разу»", health.state(DAY))

# ── Данные идут ─────────────────────────────────────────────────────
reading(DAY - timedelta(minutes=1))
health.note_collector(now=DAY - timedelta(seconds=30))
current = health.state(DAY)
check(current["state"] == "ok" and current["ok"], "свежие данные — сбор идёт", current)

# ── Панель не отвечает: запросы идут, данных нет ────────────────────
later = DAY + timedelta(minutes=20)
health.note_collector(error="панель ответила 401 — войдите в WebHMI", now=later)
current = health.state(later)
check(current["state"] == "panel", "запросы идут, данных нет — виновата панель", current)
check("401" in current["error"], "текст ошибки панели виден", current)
check("не поступают с" in current["text"], "человеку сказано, с какого времени", current["text"])
check(current["minutes"] == 21, "и сколько прошло минут", current["minutes"])

result = health.tick(later, send=catcher)
check(result["action"] == "opened", "перерыв заведён", result)
check(not sent, "до 30 минут не уведомляем", sent)

row = health.open_outage()
check(row["kind"] == "panel", "в журнале записана причина", dict(row))

# ── Расширение пропало: запросов нет вовсе ──────────────────────────
gone = DAY + timedelta(minutes=45)
current = health.state(gone)
check(current["state"] == "collector",
      "запросов нет — виновато расширение, а не панель", current)

health.tick(gone, send=catcher)
row = health.open_outage()
check(row["kind"] == "collector", "причина в том же перерыве обновилась", dict(row))
check(len(sent) == 1, "после 30 минут ушло уведомление", sent)
check(sent[0]["roles"] == ["chief_engineer"], "адресат — из настроек", sent[0])
check("не поступают" in sent[0]["title"].lower() or "датчик" in sent[0]["title"].lower(),
      "в заголовке сказано про датчики", sent[0]["title"])

# ── Повтора нет ─────────────────────────────────────────────────────
health.tick(DAY + timedelta(minutes=90), send=catcher)
health.tick(DAY + timedelta(minutes=180), send=catcher)
check(len(sent) == 1, "одно сообщение на перерыв, повторов нет", sent)

# ── Данные вернулись — перерыв закрылся сам ─────────────────────────
back = DAY + timedelta(minutes=200)
reading(back)
health.note_collector(now=back)
result = health.tick(back + timedelta(seconds=30), send=catcher)
check(result["action"] == "closed", "перерыв закрыт", result)

done = health.outages()[0]
check(done["ended_at"] is not None, "у перерыва есть конец", done)
# Тишина считается от последних данных ДО перерыва (09:59) до первых
# ПОСЛЕ него (13:20) — ровно столько, сколько экран показывал старое.
check(done["minutes"] == 201, "длительность посчитана честно", done["minutes"])
check(done["kind_label"] == "расширение не на связи",
      "причина записана по-русски", done)

total = health.summary()
check(total["count"] == 1 and total["minutes"] == 201, "сводка за месяц", total)

# ── Ночью не звоним ─────────────────────────────────────────────────
sent.clear()
reading(NIGHT - timedelta(minutes=50))
health.note_collector(now=NIGHT - timedelta(minutes=50))
health.tick(NIGHT, send=catcher)
check(health.open_outage() is not None, "ночью перерыв заводится", "нет записи")
check(not sent, "но ночью не уведомляем — компьютер выключают, это не авария", sent)

# ── Утром — одна строка ─────────────────────────────────────────────
health.tick(MORNING, send=catcher)
check(len(sent) == 1, "утром ушла одна строка", sent)
check("ч" in sent[0]["body"], "и в ней честная длительность в часах", sent[0]["body"])

health.tick(MORNING + timedelta(minutes=30), send=catcher)
check(len(sent) == 1, "и утром повтора тоже нет", sent)

# ── Адресаты и пороги — настройка ───────────────────────────────────
health.save_settings(silence_minutes=25, push_after_minutes=60,
                     alert_roles=["chief_engineer", "director"],
                     alert_users=["petrov"], who="гл. инженер")
conf = health.settings()
check(conf["silence_minutes"] == 25, "порог тишины меняется", conf)
check(conf["push_after_minutes"] == 60, "порог уведомления меняется", conf)
check(conf["alert_users"] == ["petrov"], "адресат поимённо сохраняется", conf)
check(health._user_ids(["petrov"]) == [2], "и находится по логину")

try:
    health.save_settings(silence_minutes=0, who="гл. инженер")
    check(False, "ноль минут принимать нельзя")
except ValueError:
    check(True, "ноль минут не принимается")

# Пустые списки — «не слать никому», и это законное состояние.
health.save_settings(alert_roles=[], alert_users=[], who="гл. инженер")
sent.clear()
reading(MORNING + timedelta(hours=2))
health.note_collector(now=MORNING + timedelta(hours=2))
health.tick(MORNING + timedelta(hours=2, minutes=1), send=catcher)   # закрыть прошлый
health.tick(MORNING + timedelta(hours=5), send=catcher)              # новая тишина
check(not sent, "адресатов нет — уведомление никуда не уходит", sent)

# Порог из настроек соблюдается: 25 минут вместо десяти.
quiet = MORNING + timedelta(hours=2, minutes=20)
check(health.state(quiet)["state"] == "ok",
      "20 минут при пороге 25 — это ещё не тишина", health.state(quiet))

os.unlink(factory)
os.unlink(monitoring)
print(f"OK — проверок: {checks}")
