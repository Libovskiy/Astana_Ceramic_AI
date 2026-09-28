"""
Идёт ли сбор показаний — и если нет, то где именно оборвалось.

Раньше на весь этот вопрос была одна цифра: сколько минут назад
приходили данные. Из неё нельзя понять главного — что чинить. Между
панелью и базой две разные точки отказа:

  • РАСШИРЕНИЕ НЕ НА СВЯЗИ — на сервер вообще не приходит запросов.
    Компьютер выключили, Chrome закрыли, вкладку с панелью закрыли,
    интернет пропал. Чинит тот, у кого стоит этот компьютер.

  • ПАНЕЛЬ НЕ ОТВЕЧАЕТ — запросы идут, а данных в них нет: панель
    вернула ошибку или разлогинила. Чинит тот, кто отвечает за WebHMI.

Чтобы их различать, расширение шлёт «сердцебиение» даже когда прочитать
панель не удалось — с текстом ошибки. Если запросы идут, а данных нет,
виновата панель; если и запросов нет — расширение.

Почему это вообще важно. За 17 дней до 24.09 в истории 37 перерывов
внутри рабочего дня, самый длинный — 83 минуты. Всё это время экраны
показывали последние известные значения как живые, и никто не знал,
что цифры стоят. Врать нельзя: нет данных — так и надо писать.

Перерывы пишутся в журнал (таблица sensor_outages): с какого по какое,
сколько минут, по чьей вине. История видна в «Аналитике».

Порог тишины, порог уведомления и адресаты — настройки, не код.
"""

import sqlite3
from datetime import datetime, timedelta

from backend.config import DB_NAME, DB_PATH
from backend.services import app_settings_service as settings_store

SCHEMA = """
CREATE TABLE IF NOT EXISTS sensor_outages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    minutes INTEGER,
    kind TEXT NOT NULL,              -- collector | panel
    last_error TEXT,
    push_sent_at TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_sensor_outages_started ON sensor_outages(started_at);
"""

# ── Настройки ───────────────────────────────────────────────────────
# Ключи в app_settings. Значения по умолчанию — те, о которых
# договорились с владельцем 28.09.2026.
SILENCE_MINUTES = "sensors_silence_minutes"      # когда считать тишиной
PUSH_AFTER_MINUTES = "sensors_push_after_minutes"  # когда слать уведомление
ALERT_ROLES = "sensors_alert_roles"              # кому слать, по должности
ALERT_USERS = "sensors_alert_users"              # кому слать, поимённо

# Служебные, их правит не человек, а сам сбор.
COLLECTOR_SEEN = "sensors_collector_seen_at"
COLLECTOR_ERROR = "sensors_collector_error"
# Когда последний раз показания пришли со старым ключом: значит,
# где-то ещё работает расширение версии 5.
LEGACY_KEY_SEEN = "sensors_legacy_key_seen_at"

DEFAULTS = {
    SILENCE_MINUTES: 10,
    PUSH_AFTER_MINUTES: 30,
    # Главный инженер — по должности. Кто отвечает за сам компьютер со
    # сбором, владелец назовёт отдельно: это конкретный человек, а не
    # роль, поэтому для него есть список поимённо.
    ALERT_ROLES: "chief_engineer",
    ALERT_USERS: "",
}

# Ночью не звоним: сбор держится на вкладке браузера на заводском
# компьютере, и его выключение ночью — не авария, а чья-то кнопка.
# Если тишина доживёт до утра, уйдёт одна строка в 08:00.
NIGHT_FROM = 20
NIGHT_TO = 8

KIND_LABEL = {
    "collector": "расширение не на связи",
    "panel": "панель не отвечает",
}


def _conn():
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _as_int(value, fallback):
    try:
        number = int(str(value).strip())
        return number if number > 0 else fallback
    except (TypeError, ValueError):
        return fallback


def settings() -> dict:
    """Пороги и адресаты. Пустой список ролей и людей = не слать никому."""
    roles = settings_store.get(ALERT_ROLES, DEFAULTS[ALERT_ROLES]) or ""
    users = settings_store.get(ALERT_USERS, DEFAULTS[ALERT_USERS]) or ""

    return {
        "silence_minutes": _as_int(settings_store.get(SILENCE_MINUTES),
                                   DEFAULTS[SILENCE_MINUTES]),
        "push_after_minutes": _as_int(settings_store.get(PUSH_AFTER_MINUTES),
                                      DEFAULTS[PUSH_AFTER_MINUTES]),
        "alert_roles": [r.strip() for r in roles.split(",") if r.strip()],
        "alert_users": [u.strip() for u in users.split(",") if u.strip()],
        "night_from": NIGHT_FROM,
        "night_to": NIGHT_TO,
    }


def save_settings(silence_minutes=None, push_after_minutes=None,
                  alert_roles=None, alert_users=None, who: str = None) -> dict:
    """Сохранить настройки. Возвращает «было → стало» для журнала."""
    changes = {}

    if silence_minutes is not None:
        value = _as_int(silence_minutes, 0)
        if not value:
            raise ValueError("Порог тишины — целое число минут больше нуля.")
        changes["silence_minutes"] = settings_store.set_value(
            SILENCE_MINUTES, value, who)

    if push_after_minutes is not None:
        value = _as_int(push_after_minutes, 0)
        if not value:
            raise ValueError("Порог уведомления — целое число минут больше нуля.")
        changes["push_after_minutes"] = settings_store.set_value(
            PUSH_AFTER_MINUTES, value, who)

    if alert_roles is not None:
        value = ",".join(r.strip() for r in alert_roles if r and r.strip())
        changes["alert_roles"] = settings_store.set_value(ALERT_ROLES, value, who)

    if alert_users is not None:
        value = ",".join(u.strip() for u in alert_users if u and u.strip())
        changes["alert_users"] = settings_store.set_value(ALERT_USERS, value, who)

    return changes


# ── Что знает сервер о сборе ────────────────────────────────────────

def note_collector(error: str | None = None, now: datetime = None) -> None:
    """
    Расширение отметилось. Зовётся на каждый запрос /api/sensors/live,
    в том числе когда панель не прочиталась — тогда с текстом ошибки.

    В базу пишем не чаще раза в минуту: запрос приходит каждую секунду,
    и писать в базу шестьдесят раз в минуту ради одной отметки времени
    незачем. Зато отметка переживает перезапуск сервера — иначе после
    рестарта «расширение не на связи» горело бы на ровном месте.
    """
    now = now or datetime.now()
    error = (error or "").strip()

    previous = settings_store.get(COLLECTOR_SEEN)
    # Текст ошибки сравниваем: пока он тот же, писать нечего. Иначе при
    # долгом молчании панели расширение писало бы в базу каждую секунду
    # — за сутки это 86 тысяч записей ради одной и той же строки.
    if previous and error == (settings_store.get(COLLECTOR_ERROR) or "").strip():
        try:
            if (now - datetime.fromisoformat(previous)).total_seconds() < 60:
                return
        except ValueError:
            pass

    settings_store.set_value(COLLECTOR_SEEN, now.isoformat(timespec="seconds"), "сбор")
    settings_store.set_value(COLLECTOR_ERROR, error or None, "сбор")


def note_legacy_key(now: datetime = None) -> None:
    """
    Показания пришли со старым ключом — где-то осталась версия 5.

    Пишем не чаще раза в минуту, как и остальные отметки сбора. Нужна
    она для одного: увидеть, что старый ключ больше никем не
    используется, и убрать его из .env по факту, а не по памяти.
    """
    now = now or datetime.now()
    previous = settings_store.get(LEGACY_KEY_SEEN)
    if previous:
        try:
            if (now - datetime.fromisoformat(previous)).total_seconds() < 60:
                return
        except ValueError:
            pass
    settings_store.set_value(LEGACY_KEY_SEEN, now.isoformat(timespec="seconds"), "сбор")


def legacy_key_seen_at() -> str | None:
    """Когда последний раз приходили данные со старым ключом."""
    return settings_store.get(LEGACY_KEY_SEEN) or None


def _last_reading_at() -> datetime | None:
    """Когда в истории появилось последнее показание."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        row = conn.execute("SELECT MAX(recorded_at) FROM sensor_readings").fetchone()
        conn.close()
    except Exception:
        return None

    if not row or not row[0]:
        return None
    try:
        return datetime.fromisoformat(str(row[0]))
    except ValueError:
        return None


def _minutes(since: datetime, now: datetime) -> int:
    return max(0, int((now - since).total_seconds() // 60))


def state(now: datetime = None) -> dict:
    """
    Состояние сбора одним ответом. Ключ `state`:

        ok        — данные идут;
        panel     — запросы идут, данных нет (панель молчит или ошибка);
        collector — запросов нет вовсе (расширение не на связи);
        never     — показаний не было никогда.
    """
    now = now or datetime.now()
    conf = settings()
    threshold = conf["silence_minutes"]

    last_data = _last_reading_at()
    seen_raw = settings_store.get(COLLECTOR_SEEN)
    error = settings_store.get(COLLECTOR_ERROR) or ""

    try:
        collector_seen = datetime.fromisoformat(seen_raw) if seen_raw else None
    except ValueError:
        collector_seen = None

    if last_data is None:
        return {
            "state": "never", "ok": False,
            "text": "Показаний с датчиков не было ни разу",
            "since": None, "minutes": None, "threshold": threshold,
            "last_data_at": None,
            "collector_seen_at": collector_seen.isoformat() if collector_seen else None,
            "error": error,
        }

    data_age = _minutes(last_data, now)

    if data_age < threshold:
        return {
            "state": "ok", "ok": True,
            "text": "Данные с датчиков идут",
            "since": None, "minutes": data_age, "threshold": threshold,
            "last_data_at": last_data.isoformat(timespec="seconds"),
            "collector_seen_at": collector_seen.isoformat() if collector_seen else None,
            "error": "",
        }

    collector_age = _minutes(collector_seen, now) if collector_seen else None
    alive = collector_age is not None and collector_age < threshold

    kind = "panel" if alive else "collector"
    where = ("панель не отвечает" if alive else "расширение не на связи")
    detail = f" ({error})" if alive and error else ""

    return {
        "state": kind, "ok": False,
        "text": (f"Данные с датчиков не поступают с "
                 f"{last_data.strftime('%H:%M')}: {where}{detail}"),
        "since": last_data.isoformat(timespec="seconds"),
        "minutes": data_age,
        "threshold": threshold,
        "last_data_at": last_data.isoformat(timespec="seconds"),
        "collector_seen_at": collector_seen.isoformat() if collector_seen else None,
        "error": error if alive else "",
    }


# ── Журнал перерывов ────────────────────────────────────────────────

def open_outage(conn=None):
    """Незакрытый перерыв, если он есть."""
    own = conn is None
    conn = conn or _conn()
    try:
        return conn.execute(
            "SELECT * FROM sensor_outages WHERE ended_at IS NULL "
            "ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        if own:
            conn.close()


def outages(limit: int = 50, days: int = 30) -> list:
    """История перерывов для «Аналитики» — свежие первыми."""
    since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT * FROM sensor_outages WHERE started_at >= ? "
            "ORDER BY started_at DESC LIMIT ?", (since, limit)).fetchall()
    finally:
        conn.close()

    result = []
    for row in rows:
        item = dict(row)
        item["kind_label"] = KIND_LABEL.get(item["kind"], item["kind"])
        result.append(item)
    return result


def summary(days: int = 30) -> dict:
    """Сколько перерывов и сколько всего минут за период."""
    since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS count, COALESCE(SUM(minutes), 0) AS minutes "
            "FROM sensor_outages WHERE started_at >= ? AND ended_at IS NOT NULL",
            (since,)).fetchone()
    finally:
        conn.close()
    return {"days": days, "count": row["count"], "minutes": row["minutes"]}


def _is_night(moment: datetime) -> bool:
    return moment.hour >= NIGHT_FROM or moment.hour < NIGHT_TO


def tick(now: datetime = None, send=None) -> dict:
    """
    Один шаг наблюдения: открыть перерыв, закрыть его, решить про push.

    Зовётся из того же цикла, что пишет показания (раз в 10 секунд), и
    из проверок — с подставленным `now` и `send`.
    """
    now = now or datetime.now()
    current = state(now)
    conf = settings()
    conn = _conn()
    action = None

    try:
        row = open_outage(conn)

        if current["ok"] or current["state"] == "never":
            if row:
                # Перерыв кончился. Конец — время последних данных ДО
                # возобновления не годится: берём начало новых данных,
                # то есть момент, когда всё снова поехало.
                ended = current.get("last_data_at") or now.isoformat(timespec="seconds")
                started = datetime.fromisoformat(row["started_at"])
                minutes = max(1, int((datetime.fromisoformat(ended) - started).total_seconds() // 60))
                conn.execute(
                    "UPDATE sensor_outages SET ended_at = ?, minutes = ? WHERE id = ?",
                    (ended, minutes, row["id"]))
                conn.commit()
                action = "closed"
        else:
            if not row:
                conn.execute(
                    "INSERT INTO sensor_outages (started_at, kind, last_error) VALUES (?,?,?)",
                    (current["since"], current["state"], current.get("error") or None))
                conn.commit()
                action = "opened"
                row = open_outage(conn)
            elif row["kind"] != current["state"] or (current.get("error") or None) != row["last_error"]:
                # По дороге могло смениться: расширение молчало, потом
                # заговорило, но панель не отвечает. Это тот же перерыв,
                # просто причина другая.
                conn.execute(
                    "UPDATE sensor_outages SET kind = ?, last_error = ? WHERE id = ?",
                    (current["state"], current.get("error") or None, row["id"]))
                conn.commit()
                action = action or "updated"

            # ── Уведомление ─────────────────────────────────────────
            # Утренняя строка вместо ночного звонка выходит сама собой:
            # ночью уведомление не уходит, отметки «отправлено» нет, и
            # первый же шаг после 08:00 отправит его — один раз, с
            # честным «тишина с 21:40, уже 10 часов».
            if row and not row["push_sent_at"] and current["minutes"] >= conf["push_after_minutes"]:
                if not _is_night(now):
                    if _notify(current, conf, now, send):
                        conn.execute(
                            "UPDATE sensor_outages SET push_sent_at = ? WHERE id = ?",
                            (now.isoformat(timespec="seconds"), row["id"]))
                        conn.commit()
                        action = "notified"
    finally:
        conn.close()

    current["action"] = action
    return current


def _notify(current: dict, conf: dict, now: datetime, send=None) -> bool:
    """
    Одно сообщение на один перерыв. Повторов нет: человек уже знает, а
    уведомление, которое повторяется, перестают читать.
    """
    roles, users = conf["alert_roles"], conf["alert_users"]
    if not roles and not users:
        return False

    since = current.get("since") or ""
    at = since[11:16] if len(since) >= 16 else "?"
    hours = current["minutes"] // 60
    how_long = f"{hours} ч {current['minutes'] % 60} мин" if hours else f"{current['minutes']} мин"

    title = "Данные с датчиков не поступают"
    body = (f"С {at} — {how_long}. "
            + ("Панель не отвечает" if current["state"] == "panel"
               else "Расширение не на связи")
            + (f": {current['error']}" if current.get("error") else "."))

    if send is not None:
        send(roles=roles, users=users, title=title, body=body)
        return True

    try:
        from backend.services import push_service

        if not push_service.enabled():
            return False

        if roles:
            push_service.send_to_roles(roles, title, body, url="/analytics?tab=sensors",
                                       tag="sensors-silence")
        if users:
            ids = _user_ids(users)
            if ids:
                push_service.send_to_users(ids, title, body,
                                           url="/analytics?tab=sensors",
                                           tag="sensors-silence")
        return True
    except Exception as error:
        print(f"[датчики] уведомление не ушло: {error}")
        return False


def _user_ids(usernames: list) -> list:
    if not usernames:
        return []
    conn = _conn()
    try:
        marks = ",".join("?" * len(usernames))
        rows = conn.execute(
            f"SELECT id FROM users WHERE username IN ({marks}) "
            f"AND COALESCE(is_active, 1) = 1", usernames).fetchall()
    finally:
        conn.close()
    return [r["id"] for r in rows]
