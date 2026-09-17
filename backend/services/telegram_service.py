"""
Срочные уведомления в Telegram.

Колокольчик на сайте видно, только когда сайт открыт. Механик у станка
про эскалацию узнавал, лишь зайдя на страницу. Telegram есть у всех,
установки не требует, работает на любом телефоне.

КАК ПОДКЛЮЧАЕТСЯ

1. Администратор создаёт бота у @BotFather и вписывает токен в .env:
   TELEGRAM_BOT_TOKEN=123456:ABC...
   (необязательно) ACAI_PUBLIC_URL=https://192.168.0.184:8443 — адрес
   сайта для ссылок в сообщениях.
2. Сотрудник на сайте: колокольчик → «Уведомления в Telegram» →
   «Открыть бота». Ссылка содержит одноразовый код на 15 минут; бот
   получает «/start КОД» и привязывает чат к учётке. Никаких номеров
   телефонов и ручного ввода id.
3. Отключить: кнопка на сайте или /stop в боте.

ЧТО ПРИХОДИТ (только срочное, иначе бота быстро заглушат)
- обращение передано специалисту → механикам или электрикам по
  дисциплине (не определена — обеим службам) и главному инженеру;
- ремонт завершён / черновик закрытия → тем, кто подтверждает;
- на вас назначили задачу → вам;
- личное сообщение или сообщение в группе, пока вас нет на сайте → вам;
- сбор показаний WebHMI остановился, бэкап не делался → администратору.

УСТРОЙСТВО
Отправка идёт из очереди в отдельном потоке: запрос сотрудника не
ждёт Telegram и не падает, если интернет пропал. Бот слушает
обновления длинным опросом (без вебхука — у сервера нет внешнего
адреса). Поток слушания и проверок работает только в основном
экземпляре сервера (порт 8000), иначе оба экземпляра забирали бы одни
и те же обновления.
"""

import os
import queue
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta

import requests

from backend.config import DB_NAME


API = "https://api.telegram.org/bot{token}/{method}"
CODE_TTL_MIN = 15

# Кто получает что
DISCIPLINE_ROLES = {
    "mechanical": ("chief_mechanic", "mechanic"),
    "electrical": ("chief_electrician", "electrician"),
}
ESCALATION_ALWAYS = ("chief_engineer",)
APPROVER_ROLES = ("chief_engineer", "director", "admin")
SYSTEM_ALERT_ROLES = ("admin",)

# Сообщение в переписке шлём, только если человека нет на сайте
MESSENGER_OFFLINE_MIN = 3

_queue: "queue.Queue" = queue.Queue(maxsize=1000)
_started = False
_bot_username = None


def token() -> str:
    return (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()


def enabled() -> bool:
    return bool(token())


def site_url(path: str = "") -> str:
    base = (os.environ.get("ACAI_PUBLIC_URL") or "http://192.168.0.184:8000").rstrip("/")
    return base + path


def get_connection():
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_telegram():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS telegram_links (
            user_id INTEGER PRIMARY KEY,
            chat_id INTEGER NOT NULL,
            tg_name TEXT,
            linked_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS telegram_codes (
            code TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            expires_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def _call(method: str, **params):
    response = requests.post(API.format(token=token(), method=method), json=params, timeout=35)
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("description") or f"Telegram {method}: ошибка")
    return data["result"]


def bot_username():
    global _bot_username
    if _bot_username or not enabled():
        return _bot_username
    try:
        _bot_username = _call("getMe")["username"]
    except Exception as error:
        print(f"[telegram] getMe: {error}")
    return _bot_username


# =========================================================
# ПРИВЯЗКА
# =========================================================

def status_for(user_id: int) -> dict:
    conn = get_connection()
    row = conn.execute("SELECT tg_name, linked_at FROM telegram_links WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return {
        "configured": enabled(),
        "bot": bot_username(),
        "linked": bool(row),
        "tg_name": row["tg_name"] if row else None,
        "linked_at": row["linked_at"] if row else None,
    }


def create_link(user_id: int) -> dict:
    if not enabled():
        raise ValueError("Telegram-бот не настроен. Обратитесь к администратору.")
    name = bot_username()
    if not name:
        raise ValueError("Бот не отвечает — проверьте токен и интернет на сервере.")

    code = secrets.token_urlsafe(12).replace("-", "").replace("_", "")[:16]
    expires = (datetime.now() + timedelta(minutes=CODE_TTL_MIN)).strftime("%Y-%m-%d %H:%M:%S")

    conn = get_connection()
    conn.execute("DELETE FROM telegram_codes WHERE user_id = ? OR expires_at < ?",
                 (user_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.execute("INSERT INTO telegram_codes (code, user_id, expires_at) VALUES (?, ?, ?)", (code, user_id, expires))
    conn.commit()
    conn.close()

    return {"url": f"https://t.me/{name}?start={code}", "bot": name, "code": code}


def unlink(user_id: int) -> None:
    conn = get_connection()
    row = conn.execute("SELECT chat_id FROM telegram_links WHERE user_id = ?", (user_id,)).fetchone()
    conn.execute("DELETE FROM telegram_links WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    if row:
        _enqueue(row["chat_id"], "Уведомления ACAI отключены. Подключить снова можно на сайте: колокольчик → «Уведомления в Telegram».")


def _handle_update(update: dict) -> None:
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    text = (message.get("text") or "").strip()
    chat_id = chat.get("id")

    if not chat_id or chat.get("type") != "private":
        return

    if text.startswith("/start"):
        code = text[len("/start"):].strip()
        if not code:
            _enqueue(chat_id, "Это бот уведомлений ACAI (Astana Ceramic).\n\nЧтобы подключиться, откройте сайт → колокольчик 🔔 → «Уведомления в Telegram» → «Открыть бота».")
            return

        conn = get_connection()
        row = conn.execute(
            """
            SELECT c.user_id, u.full_name, u.username
            FROM telegram_codes c JOIN users u ON u.id = c.user_id
            WHERE c.code = ? AND c.expires_at >= ? AND COALESCE(u.is_active, 1) = 1
            """,
            (code, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        ).fetchone()

        if not row:
            conn.close()
            _enqueue(chat_id, "Ссылка устарела или уже использована. Откройте на сайте «Уведомления в Telegram» ещё раз.")
            return

        tg_name = " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")])) or chat.get("username")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Один Telegram — одна учётка: на общем телефоне смены это важно,
        # иначе уведомления прошлого владельца продолжали бы приходить.
        conn.execute("DELETE FROM telegram_links WHERE chat_id = ?", (chat_id,))
        conn.execute(
            "INSERT OR REPLACE INTO telegram_links (user_id, chat_id, tg_name, linked_at) VALUES (?, ?, ?, ?)",
            (row["user_id"], chat_id, tg_name, now)
        )
        conn.execute("DELETE FROM telegram_codes WHERE code = ?", (code,))
        conn.commit()
        conn.close()

        _enqueue(chat_id, f"✅ Подключено: {row['full_name'] or row['username']}.\n\nСюда будут приходить срочные уведомления ACAI. Отключить — /stop.")
        return

    if text.startswith("/stop"):
        conn = get_connection()
        row = conn.execute("SELECT user_id FROM telegram_links WHERE chat_id = ?", (chat_id,)).fetchone()
        conn.close()
        if row:
            unlink(row["user_id"])
        else:
            _enqueue(chat_id, "Этот Telegram не подключён к ACAI.")
        return

    _enqueue(chat_id, "Я только присылаю уведомления ACAI. Отвечать и работать с обращениями — на сайте.\n\n" + site_url("/"))


# =========================================================
# ОТПРАВКА
# =========================================================

def _enqueue(chat_id, text) -> None:
    if not enabled():
        return
    try:
        _queue.put_nowait((chat_id, text[:4000]))
    except queue.Full:
        print("[telegram] очередь переполнена, сообщение пропущено")


def _chats_for_users(conn, user_ids) -> list:
    ids = [int(u) for u in set(user_ids) if u is not None]
    if not ids:
        return []
    marks = ",".join("?" for _ in ids)
    return [r["chat_id"] for r in conn.execute(
        f"""
        SELECT t.chat_id FROM telegram_links t JOIN users u ON u.id = t.user_id
        WHERE t.user_id IN ({marks}) AND COALESCE(u.is_active, 1) = 1
        """, ids
    )]


def _chats_for_roles(conn, roles, exclude_user_id=None) -> list:
    roles = list(roles)
    marks = ",".join("?" for _ in roles)
    rows = conn.execute(
        f"""
        SELECT t.chat_id, t.user_id FROM telegram_links t JOIN users u ON u.id = t.user_id
        WHERE u.role IN ({marks}) AND COALESCE(u.is_active, 1) = 1
        """, roles
    ).fetchall()
    return [r["chat_id"] for r in rows if r["user_id"] != exclude_user_id]


def send_to_users(user_ids, text: str) -> None:
    if not enabled():
        return
    conn = get_connection()
    chats = _chats_for_users(conn, user_ids)
    conn.close()
    for chat_id in chats:
        _enqueue(chat_id, text)


def send_to_roles(roles, text: str, exclude_user_id=None) -> None:
    if not enabled():
        return
    conn = get_connection()
    chats = set(_chats_for_roles(conn, roles, exclude_user_id))
    conn.close()
    for chat_id in chats:
        _enqueue(chat_id, text)


def _defer(seconds: float, func, *args) -> None:
    """Отложить: дать вызывающему коду дописать своё в базу."""
    if not enabled():
        return
    timer = threading.Timer(seconds, lambda: _safe(func, *args))
    timer.daemon = True
    timer.start()


def _safe(func, *args):
    try:
        func(*args)
    except Exception as error:
        print(f"[telegram] {getattr(func, '__name__', func)}: {error}")


# =========================================================
# СОБЫТИЯ
# =========================================================

def _case_row(case_id):
    conn = get_connection()
    row = conn.execute(
        """
        SELECT c.id, c.symptom, c.worker_question, c.machine, c.required_discipline,
               c.status, c.draft_closed_by, c.draft_resolution_comment, e.name AS equipment_name
        FROM cases c LEFT JOIN equipment e ON e.id = c.equipment_id
        WHERE c.id = ?
        """, (case_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def case_escalated(case_id: int) -> None:
    # Дисциплину ИИ дописывает сразу после смены статуса — ждём пару секунд.
    _defer(3, _case_escalated_now, case_id)


def _case_escalated_now(case_id: int) -> None:
    case = _case_row(case_id)
    if not case or case["status"] != "Требует специалиста":
        return
    machine = case["equipment_name"] or case["machine"] or "станок"
    problem = (case["symptom"] or case["worker_question"] or "").strip()
    discipline = case["required_discipline"]
    who = {"mechanical": "механик", "electrical": "электрик"}.get(discipline, "специалист")

    roles = DISCIPLINE_ROLES.get(discipline) or (DISCIPLINE_ROLES["mechanical"] + DISCIPLINE_ROLES["electrical"])
    text = (
        f"🔴 Нужен {who}: {machine}\n"
        f"{problem}\n\n"
        f"Обращение №{case['id']} — ИИ не справился, ждут специалиста.\n"
        f"{site_url('/chat')}"
    )
    send_to_roles(tuple(roles) + ESCALATION_ALWAYS, text)


def case_ready_for_approval(case_id: int, exclude_user_id=None) -> None:
    _defer(1, _case_ready_now, case_id, exclude_user_id)


def _case_ready_now(case_id: int, exclude_user_id=None) -> None:
    case = _case_row(case_id)
    if not case or case["status"] != "Черновик закрытия":
        return
    machine = case["equipment_name"] or case["machine"] or "станок"
    comment = (case["draft_resolution_comment"] or "").strip()
    text = (
        f"🟡 Ждёт подтверждения закрытия: {machine}\n"
        f"Ремонт: {case['draft_closed_by'] or '—'}"
        + (f"\n«{comment[:300]}»" if comment else "")
        + f"\n\nОбращение №{case['id']}\n{site_url('/chat')}"
    )
    send_to_roles(APPROVER_ROLES, text, exclude_user_id=exclude_user_id)


def task_assigned(task_id: int, user_id: int, assigned_by: int) -> None:
    if not enabled() or user_id == assigned_by:
        return
    conn = get_connection()
    task = conn.execute("SELECT title, priority, due_at FROM tasks WHERE id = ?", (task_id,)).fetchone()
    by = conn.execute("SELECT full_name, username FROM users WHERE id = ?", (assigned_by,)).fetchone()
    conn.close()
    if not task:
        return
    due = f"\nСрок: {task['due_at'][:16]}" if task["due_at"] else ""
    who = (by["full_name"] or by["username"]) if by else "—"
    send_to_users([user_id], f"📌 На вас назначена задача: {task['title']}\nНазначил: {who}{due}\n\n{site_url('/events')}")


def messenger_message(conversation_id: int, sender_id: int, preview: str) -> None:
    _defer(0.1, _messenger_now, conversation_id, sender_id, preview)


def _messenger_now(conversation_id: int, sender_id: int, preview: str) -> None:
    conn = get_connection()
    conv = conn.execute("SELECT kind, title FROM team_conversations WHERE id = ?", (conversation_id,)).fetchone()
    sender = conn.execute("SELECT full_name, username FROM users WHERE id = ?", (sender_id,)).fetchone()
    members = [r["user_id"] for r in conn.execute(
        "SELECT user_id FROM team_members WHERE conversation_id = ? AND user_id != ?", (conversation_id, sender_id)
    )]

    # Кто сейчас на сайте — тому Telegram не нужен, он увидит и так
    since = (datetime.now() - timedelta(minutes=MESSENGER_OFFLINE_MIN)).strftime("%Y-%m-%d %H:%M:%S")
    online = set()
    try:
        online = {r["user_id"] for r in conn.execute(
            "SELECT DISTINCT user_id FROM usage_daily WHERE path = '*' AND last_at >= ?", (since,)
        )}
    except sqlite3.OperationalError:
        pass
    conn.close()

    if not conv or not sender:
        return

    targets = [m for m in members if m not in online]
    if not targets:
        return

    name = sender["full_name"] or sender["username"]
    where = f"в группе «{conv['title']}»" if conv["kind"] == "group" else "вам"
    send_to_users(targets, f"💭 {name} пишет {where}:\n{preview[:500]}\n\n{site_url('/messenger')}")


# =========================================================
# ФОНОВЫЕ ПОТОКИ
# =========================================================

def _sender_loop():
    while True:
        chat_id, text = _queue.get()
        for attempt in range(3):
            try:
                _call("sendMessage", chat_id=chat_id, text=text, disable_web_page_preview=True)
                break
            except Exception as error:
                message = str(error)
                # человек заблокировал бота — отвязываем, чтобы не долбиться
                if "blocked" in message or "chat not found" in message or "deactivated" in message:
                    conn = get_connection()
                    conn.execute("DELETE FROM telegram_links WHERE chat_id = ?", (chat_id,))
                    conn.commit()
                    conn.close()
                    break
                time.sleep(3 * (attempt + 1))
        time.sleep(0.05)   # лимит Telegram — до 30 сообщений в секунду


def _poll_loop():
    offset = None
    while True:
        try:
            params = {"timeout": 25, "allowed_updates": ["message"]}
            if offset is not None:
                params["offset"] = offset
            for update in _call("getUpdates", **params):
                offset = update["update_id"] + 1
                _safe(_handle_update, update)
        except Exception as error:
            print(f"[telegram] getUpdates: {error}")
            time.sleep(15)


# Проверки состояния системы: одно сообщение на случай, не каждые 10 минут
_alerted: dict = {}
SENSOR_ALERT_MIN = 20


def _system_checks_loop():
    while True:
        time.sleep(600)
        _safe(_check_sensors)
        _safe(_check_backup)


def _check_sensors():
    from sqlalchemy import func
    from backend import models
    from backend.database import SessionLocal
    db = SessionLocal()
    try:
        last = db.query(func.max(models.SensorReading.recorded_at)).scalar()
    finally:
        db.close()
    if last is None:
        return
    minutes = int((datetime.now() - last).total_seconds() // 60)
    stale = minutes >= SENSOR_ALERT_MIN
    if stale and not _alerted.get("sensors"):
        _alerted["sensors"] = True
        send_to_roles(SYSTEM_ALERT_ROLES, f"📡 Показания датчиков не пишутся {minutes} мин.\nОткройте вкладку WebHMI на сервере и войдите в панель.")
    elif not stale and _alerted.get("sensors"):
        _alerted["sensors"] = False
        send_to_roles(SYSTEM_ALERT_ROLES, "📡 Показания датчиков снова пишутся.")


def _check_backup():
    from pathlib import Path
    from backend.config import BASE_DIR
    backups = sorted((Path(BASE_DIR) / "backups").glob("factory_*.db"), key=lambda f: f.stat().st_mtime)
    if not backups:
        return
    hours = (time.time() - backups[-1].stat().st_mtime) / 3600
    stale = hours >= 30
    if stale and not _alerted.get("backup"):
        _alerted["backup"] = True
        send_to_roles(SYSTEM_ALERT_ROLES, f"💾 Резервная копия не делалась {int(hours)} ч. Проверьте logs/backup.error.log.")
    elif not stale:
        _alerted["backup"] = False


def start() -> None:
    """Запускать один раз, только в основном экземпляре сервера."""
    global _started
    if _started or not enabled():
        return
    _started = True
    for target, name in ((_sender_loop, "tg-send"), (_poll_loop, "tg-poll"), (_system_checks_loop, "tg-checks")):
        threading.Thread(target=target, daemon=True, name=name).start()
    print(f"[telegram] бот запущен: @{bot_username()}")
