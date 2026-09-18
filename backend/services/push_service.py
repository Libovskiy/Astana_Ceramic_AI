"""
Уведомления на телефон — push самого сайта, без Telegram и приложений.

Колокольчик видно, только когда сайт открыт. Механик про эскалацию
узнавал, лишь зайдя на страницу. Push приходит как у WhatsApp: со
звуком и вибрацией, на погашенный экран, даже когда вкладка закрыта —
достаточно один раз разрешить уведомления на сайте.

КАК ЭТО УСТРОЕНО
- Браузер телефона подписывается (static/push.js → /sw.js, service
  worker) и отдаёт адрес подписки; храним его в push_subscriptions.
  У одного человека может быть несколько устройств.
- Сервер шифрует уведомление ключами VAPID (certs/vapid_*) и отдаёт в
  службу доставки браузера (у Chrome — Google, у Safari — Apple). Поэтому
  интернет нужен и серверу, и телефону (мобильный или Wi-Fi).
- Работает ТОЛЬКО на https с доверенным сертификатом: service worker
  не регистрируется на странице с предупреждением о сертификате.
  Отсюда заводской корневой сертификат certs/ca.crt, который один раз
  ставится на телефон (страница /cert). Адрес — https://192.168.0.184:8443.
- iPhone: только iOS 16.4+ и только если сайт добавлен «На экран
  Домой» (ограничение Apple).

ЧТО ПРИХОДИТ (только срочное и личное — иначе уведомления отключат)
- обращение передано специалисту → механикам или электрикам по
  дисциплине (не определена — обеим службам) и главному инженеру;
- специалист взял обращение / ответил в нём → рабочему, кто его завёл;
- ремонт завершён / черновик закрытия → тем, кто подтверждает;
- на вас назначили задачу → вам;
- сообщение в переписке, пока вас нет на сайте → вам;
- сбор показаний WebHMI остановился, бэкап не делался → администратору.

Отправка идёт из очереди в фоновом потоке каждого экземпляра сервера:
запрос сотрудника не ждёт службу доставки и не падает без интернета.
"""

import json
import queue
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from backend.config import BASE_DIR, DB_NAME


CERTS = Path(BASE_DIR) / "certs"
VAPID_PRIVATE = CERTS / "vapid_private.pem"
VAPID_PUBLIC = CERTS / "vapid_public.txt"
VAPID_CONTACT = "mailto:admin@astana-ceramic.local"

DISCIPLINE_ROLES = {
    "mechanical": ("chief_mechanic", "mechanic"),
    "electrical": ("chief_electrician", "electrician"),
}
ESCALATION_ALWAYS = ("chief_engineer",)
APPROVER_ROLES = ("chief_engineer", "director", "admin")
SYSTEM_ALERT_ROLES = ("admin",)

# Сообщение в переписке шлём, только если человека нет на сайте
OFFLINE_MIN = 3

_queue: "queue.Queue" = queue.Queue(maxsize=2000)
_sender_started = False
_checks_started = False


def enabled() -> bool:
    return VAPID_PRIVATE.exists() and VAPID_PUBLIC.exists()


def public_key() -> str:
    return VAPID_PUBLIC.read_text().strip() if VAPID_PUBLIC.exists() else ""


def get_connection():
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_push():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            endpoint TEXT NOT NULL UNIQUE,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            user_agent TEXT,
            created_at TEXT NOT NULL,
            last_ok_at TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_push_user ON push_subscriptions(user_id)")
    # Telegram-бот заменён push-уведомлениями: его таблицы больше не нужны
    conn.execute("DROP TABLE IF EXISTS telegram_links")
    conn.execute("DROP TABLE IF EXISTS telegram_codes")
    conn.commit()
    conn.close()


# =========================================================
# ПОДПИСКИ
# =========================================================

def subscribe(user_id: int, subscription: dict, user_agent: str = "") -> None:
    endpoint = (subscription or {}).get("endpoint") or ""
    keys = (subscription or {}).get("keys") or {}
    if not endpoint.startswith("https://") or not keys.get("p256dh") or not keys.get("auth"):
        raise ValueError("Браузер прислал неполную подписку.")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    # Один телефон — одна учётка: на общем телефоне смены уведомления
    # прошлого владельца не должны приходить новому.
    conn.execute(
        """
        INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, user_agent, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(endpoint) DO UPDATE SET
            user_id = excluded.user_id, p256dh = excluded.p256dh, auth = excluded.auth,
            user_agent = excluded.user_agent, created_at = excluded.created_at
        """,
        (user_id, endpoint, keys["p256dh"], keys["auth"], (user_agent or "")[:300], now)
    )
    conn.commit()
    conn.close()


def unsubscribe(user_id: int, endpoint: str | None) -> None:
    conn = get_connection()
    if endpoint:
        conn.execute("DELETE FROM push_subscriptions WHERE user_id = ? AND endpoint = ?", (user_id, endpoint))
    else:
        conn.execute("DELETE FROM push_subscriptions WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def status_for(user_id: int, endpoint: str | None = None) -> dict:
    conn = get_connection()
    devices = conn.execute("SELECT COUNT(*) FROM push_subscriptions WHERE user_id = ?", (user_id,)).fetchone()[0]
    this_device = False
    if endpoint:
        this_device = conn.execute(
            "SELECT 1 FROM push_subscriptions WHERE user_id = ? AND endpoint = ?", (user_id, endpoint)
        ).fetchone() is not None
    conn.close()
    return {"configured": enabled(), "public_key": public_key(), "devices": devices, "this_device": this_device}


def overview() -> list:
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT u.full_name, u.username, u.role, COUNT(*) AS devices, MAX(p.created_at) AS since
        FROM push_subscriptions p JOIN users u ON u.id = p.user_id
        WHERE COALESCE(u.is_active, 1) = 1
        GROUP BY p.user_id ORDER BY since DESC
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# =========================================================
# ОТПРАВКА
# =========================================================

def _payload(title: str, body: str, url: str = "/", tag: str | None = None, urgent: bool = False) -> str:
    return json.dumps({
        "title": title, "body": body[:400], "url": url,
        "tag": tag, "urgent": urgent,
    }, ensure_ascii=False)


def send_to_users(user_ids, title, body, url="/", tag=None, urgent=False) -> None:
    ids = [int(u) for u in set(user_ids or []) if u is not None]
    if not ids or not enabled():
        return
    _ensure_sender()
    try:
        _queue.put_nowait((ids, _payload(title, body, url, tag, urgent)))
    except queue.Full:
        print("[push] очередь переполнена, уведомление пропущено")


def _users_with_roles(roles, exclude_user_id=None) -> list:
    roles = list(roles)
    marks = ",".join("?" for _ in roles)
    conn = get_connection()
    rows = conn.execute(
        f"SELECT id FROM users WHERE role IN ({marks}) AND COALESCE(is_active, 1) = 1", roles
    ).fetchall()
    conn.close()
    return [r["id"] for r in rows if r["id"] != exclude_user_id]


def send_to_roles(roles, title, body, url="/", tag=None, urgent=False, exclude_user_id=None) -> None:
    send_to_users(_users_with_roles(roles, exclude_user_id), title, body, url, tag, urgent)


def _deliver(user_ids, payload) -> None:
    from pywebpush import webpush, WebPushException
    from backend.services.observation_service import record_delivery

    try:
        meta = json.loads(payload)
    except ValueError:
        meta = {}

    marks = ",".join("?" for _ in user_ids)
    conn = get_connection()
    subs = conn.execute(
        f"SELECT id, user_id, endpoint, p256dh, auth FROM push_subscriptions WHERE user_id IN ({marks})", user_ids
    ).fetchall()
    conn.close()

    for sub in subs:
        try:
            webpush(
                subscription_info={"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
                data=payload,
                vapid_private_key=str(VAPID_PRIVATE),
                vapid_claims={"sub": VAPID_CONTACT},
                ttl=6 * 3600,
                headers={"Urgency": "high"},
                timeout=15,
            )
            conn = get_connection()
            conn.execute("UPDATE push_subscriptions SET last_ok_at = ? WHERE id = ?",
                         (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), sub["id"]))
            conn.commit()
            conn.close()
            record_delivery(sub["user_id"], meta.get("tag"), meta.get("title"), True)
        except WebPushException as error:
            status = getattr(getattr(error, "response", None), "status_code", None)
            record_delivery(sub["user_id"], meta.get("tag"), meta.get("title"), False, str(status))
            # 404/410 — подписки больше нет (удалили сайт, сбросили браузер)
            if status in (404, 410):
                conn = get_connection()
                conn.execute("DELETE FROM push_subscriptions WHERE id = ?", (sub["id"],))
                conn.commit()
                conn.close()
            else:
                print(f"[push] не доставлено ({status}): {error}")
        except Exception as error:
            print(f"[push] ошибка отправки: {error}")


def _sender_loop():
    while True:
        user_ids, payload = _queue.get()
        try:
            _deliver(user_ids, payload)
        except Exception as error:
            print(f"[push] {error}")


def _ensure_sender():
    global _sender_started
    if _sender_started:
        return
    _sender_started = True
    threading.Thread(target=_sender_loop, daemon=True, name="push-send").start()


def _defer(seconds, func, *args):
    if not enabled():
        return
    def run():
        try:
            func(*args)
        except Exception as error:
            print(f"[push] {getattr(func, '__name__', func)}: {error}")
    timer = threading.Timer(seconds, run)
    timer.daemon = True
    timer.start()


# =========================================================
# СОБЫТИЯ
# =========================================================

def _case_row(case_id):
    conn = get_connection()
    row = conn.execute(
        """
        SELECT c.id, c.symptom, c.worker_question, c.machine, c.required_discipline, c.status,
               c.assigned_to, c.draft_closed_by, c.draft_resolution_comment, e.name AS equipment_name
        FROM cases c LEFT JOIN equipment e ON e.id = c.equipment_id
        WHERE c.id = ?
        """, (case_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _machine(case):
    return case["equipment_name"] or case["machine"] or "Станок"


def _case_author_ids(case_id) -> list:
    """Кто завёл обращение: по первому сообщению рабочего (в cases нет user_id)."""
    conn = get_connection()
    row = conn.execute(
        "SELECT author FROM chat_history WHERE case_id = ? AND role = 'worker' ORDER BY id LIMIT 1", (case_id,)
    ).fetchone()
    ids = []
    if row and row["author"]:
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM users WHERE (full_name = ? OR username = ?) AND COALESCE(is_active, 1) = 1",
            (row["author"], row["author"])
        )]
    conn.close()
    return ids


def case_escalated(case_id: int) -> None:
    # Дисциплину ИИ дописывает сразу после смены статуса — ждём пару секунд
    _defer(3, _case_escalated_now, case_id)


def _case_escalated_now(case_id: int) -> None:
    case = _case_row(case_id)
    if not case or case["status"] != "Требует специалиста":
        return
    discipline = case["required_discipline"]
    who = {"mechanical": "механик", "electrical": "электрик"}.get(discipline, "специалист")
    roles = DISCIPLINE_ROLES.get(discipline) or (DISCIPLINE_ROLES["mechanical"] + DISCIPLINE_ROLES["electrical"])
    problem = (case["symptom"] or case["worker_question"] or "").strip()
    send_to_roles(
        tuple(roles) + ESCALATION_ALWAYS,
        f"🔴 Нужен {who}: {_machine(case)}",
        f"{problem}\nОбращение №{case['id']} — ждут специалиста.",
        url=f"/chat?case={case_id}", tag=f"case-{case_id}", urgent=True,
    )


def case_taken(case_id: int, by_name: str) -> None:
    _defer(0.5, _case_taken_now, case_id, by_name)


def _case_taken_now(case_id: int, by_name: str) -> None:
    case = _case_row(case_id)
    if not case:
        return
    send_to_users(
        _case_author_ids(case_id),
        f"🔧 {by_name} взял ваше обращение",
        f"{_machine(case)} — №{case_id}. Специалист идёт.",
        url=f"/chat?case={case_id}", tag=f"case-{case_id}",
    )


def case_specialist_reply(case_id: int, by_name: str, text: str) -> None:
    _defer(0.5, lambda: send_to_users(
        _case_author_ids(case_id),
        f"💬 {by_name} ответил по обращению №{case_id}",
        text[:300], url=f"/chat?case={case_id}", tag=f"case-{case_id}",
    ))


def case_ready_for_approval(case_id: int) -> None:
    _defer(1, _case_ready_now, case_id)


def _case_ready_now(case_id: int) -> None:
    case = _case_row(case_id)
    if not case or case["status"] != "Черновик закрытия":
        return
    comment = (case["draft_resolution_comment"] or "").strip()
    send_to_roles(
        APPROVER_ROLES,
        f"🟡 Подтвердите закрытие: {_machine(case)}",
        f"Ремонт: {case['draft_closed_by'] or '—'}" + (f" — «{comment[:200]}»" if comment else "") + f"\nОбращение №{case_id}",
        url=f"/chat?case={case_id}", tag=f"case-{case_id}",
    )


def notify_part_writeoff(writeoff_id: int) -> None:
    """
    Ответственному за склад: по ремонту, похоже, взяли деталь.

    Механика — главному механику, электрика — главному энергетику
    (chief_electrician). Слесаря и электрика не трогаем: они списанием
    не занимаются, лишнее уведомление им только мешает.
    """
    _defer(1, _part_writeoff_now, writeoff_id)


def _part_writeoff_now(writeoff_id: int) -> None:
    from backend.services.part_usage_service import RESPONSIBLE

    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM part_writeoffs WHERE id = ? AND status = 'pending'", (writeoff_id,)
    ).fetchone()
    conn.close()
    if not row:
        return

    import json
    try:
        names = [item["name"] for item in json.loads(row["suggested"] or "[]")][:3]
    except ValueError:
        names = []

    roles = RESPONSIBLE.get(row["discipline"], ())
    if not roles:
        return

    send_to_roles(
        roles,
        f"📦 Списать со склада? {row['equipment_name'] or '—'}",
        (f"Похоже, взяли: {', '.join(names)}" if names else "Проверьте, что уходило со склада")
        + f"\nРемонт по обращению №{row['case_id']}",
        url="/parts", tag=f"writeoff-{writeoff_id}",
    )


def task_assigned(task_id: int, user_id: int, assigned_by: int) -> None:
    if not enabled() or user_id == assigned_by:
        return
    conn = get_connection()
    task = conn.execute("SELECT title, due_at FROM tasks WHERE id = ?", (task_id,)).fetchone()
    by = conn.execute("SELECT full_name, username FROM users WHERE id = ?", (assigned_by,)).fetchone()
    conn.close()
    if not task:
        return
    due = f"\nСрок: {task['due_at'][:16].replace('T', ' ')}" if task["due_at"] else ""
    send_to_users([user_id], f"📌 Вам задача: {task['title']}",
                  f"Назначил: {(by['full_name'] or by['username']) if by else '—'}{due}",
                  url="/events", tag=f"task-{task_id}")


def messenger_message(conversation_id: int, sender_id: int, preview: str) -> None:
    _defer(0.1, _messenger_now, conversation_id, sender_id, preview)


def _messenger_now(conversation_id: int, sender_id: int, preview: str) -> None:
    conn = get_connection()
    conv = conn.execute("SELECT kind, title FROM team_conversations WHERE id = ?", (conversation_id,)).fetchone()
    sender = conn.execute("SELECT full_name, username FROM users WHERE id = ?", (sender_id,)).fetchone()
    members = [r["user_id"] for r in conn.execute(
        "SELECT user_id FROM team_members WHERE conversation_id = ? AND user_id != ?", (conversation_id, sender_id)
    )]
    # Кто сейчас на сайте — тот увидит и так, лишний звонок не нужен
    since = (datetime.now() - timedelta(minutes=OFFLINE_MIN)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        online = {r["user_id"] for r in conn.execute(
            "SELECT DISTINCT user_id FROM usage_daily WHERE path = '*' AND last_at >= ?", (since,)
        )}
    except sqlite3.OperationalError:
        online = set()
    conn.close()

    if not conv or not sender:
        return
    targets = [m for m in members if m not in online]
    name = sender["full_name"] or sender["username"]
    title = f"💭 {name}" if conv["kind"] != "group" else f"💭 {conv['title']}: {name}"
    send_to_users(targets, title, preview[:300], url="/messenger", tag=f"conv-{conversation_id}")


# =========================================================
# ПРОВЕРКИ СОСТОЯНИЯ (только основной экземпляр)
# =========================================================

_alerted: dict = {}
SENSOR_ALERT_MIN = 20


def _checks_loop():
    while True:
        time.sleep(600)
        for check in (_check_sensors, _check_backup):
            try:
                check()
            except Exception as error:
                print(f"[push] проверка {check.__name__}: {error}")


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
        send_to_roles(SYSTEM_ALERT_ROLES, f"📡 Датчики не пишутся {minutes} мин",
                      "Откройте вкладку WebHMI на сервере и войдите в панель.", url="/settings", tag="sensors")
    elif not stale and _alerted.get("sensors"):
        _alerted["sensors"] = False
        send_to_roles(SYSTEM_ALERT_ROLES, "📡 Датчики снова пишутся", "Сбор показаний восстановлен.", url="/settings", tag="sensors")


def _check_backup():
    from backend.config import BACKUPS_DIR
    backups = sorted(Path(BACKUPS_DIR).glob("factory_*.db"), key=lambda f: f.stat().st_mtime)
    if not backups:
        return
    hours = (time.time() - backups[-1].stat().st_mtime) / 3600
    if hours >= 30 and not _alerted.get("backup"):
        _alerted["backup"] = True
        send_to_roles(SYSTEM_ALERT_ROLES, f"💾 Бэкап не делался {int(hours)} ч",
                      "Проверьте logs/backup.error.log.", url="/settings", tag="backup")
    elif hours < 30:
        _alerted["backup"] = False


def start_checks() -> None:
    global _checks_started
    if _checks_started or not enabled():
        return
    _checks_started = True
    threading.Thread(target=_checks_loop, daemon=True, name="push-checks").start()
