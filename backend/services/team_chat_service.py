"""
Общение между людьми: личная переписка и группы.

ЧЕМ ОТЛИЧАЕТСЯ ОТ «ОБРАЩЕНИЙ»

Обращения (/chat, conversation_service) — это разговор о поломке:
рабочий описывает проблему, отвечает ИИ, потом подключается
специалист, в конце обращение закрывают. У разговора есть станок,
статус и жизненный цикл.

Здесь ничего этого нет. Это просто переписка между людьми:
договориться о подмене, скинуть фото шильдика, собрать бригаду.
Поэтому таблицы отдельные (team_*) — смешивать их с обращениями
значило бы тащить в переписку статусы и станки, которым там не место.

КТО КОМУ МОЖЕТ ПИСАТЬ

Любой любому, группу собирает кто угодно. Завод небольшой — 48
человек, — и ограничения тут создали бы больше проблем, чем решили:
в аварийной ситуации электрику нужно написать технологу, не спрашивая
разрешения.

Отключённым сотрудникам (users.is_active = 0) писать нельзя и в
списке людей они не показываются: доступ к системе им закрыт, а
переписка осталась бы висеть без ответа. Старые сообщения при этом
никуда не деваются — история смены должна сохраниться.

КАК ДОХОДЯТ СООБЩЕНИЯ

Опросом, как и всё остальное в системе: открытая страница
спрашивает сервер раз в несколько секунд. WebSocket тут не нужен —
это переписка между полусотней человек, а не биржа, зато опрос
переживает разрывы заводского Wi-Fi без переподключений.

НЕПРОЧИТАННОЕ

У каждого участника в team_members лежит last_read_message_id —
номер последнего прочитанного им сообщения. Непрочитанные считаются
как «всё, что новее». Так счётчик не врёт при чтении с двух
устройств и не требует записи на каждое открытие.
"""

import mimetypes
import shutil
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from backend.config import BASE_DIR, DB_NAME

KIND_DM = "dm"
KIND_GROUP = "group"

MAX_MESSAGE_LENGTH = 4000
MAX_TITLE_LENGTH = 80

# 50 МБ. Столько весит минутный ролик с телефона — на заводском
# Wi-Fi это уже долго, но отправить шильдик или короткое видео
# работающего узла должно быть можно.
MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024

ATTACHMENTS_DIR = BASE_DIR / "uploads" / "messenger"

# Показываем прямо в переписке только то, что браузер умеет рисовать
# сам и что безопасно открывать. Всё остальное отдаётся файлом на
# скачивание: SVG и HTML внутри страницы — это чужой код в нашем
# домене, а PDF умеет выполнять скрипты.
INLINE_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
INLINE_VIDEO_TYPES = {"video/mp4", "video/webm", "video/quicktime"}

KIND_IMAGE = "image"
KIND_VIDEO = "video"
KIND_FILE = "file"

# Длинная сторона картинки для показа в переписке. Оригинал остаётся
# на диске и скачивается по кнопке — в ленте он не нужен, а по
# заводскому Wi-Fi двадцатимегабайтное фото грузится ощутимо.
PREVIEW_MAX_SIDE = 1280
PREVIEW_QUALITY = 82


def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# =========================================================
# СХЕМА
# =========================================================

def init_team_chat():

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS team_conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL DEFAULT 'dm',
            title TEXT,
            created_by INTEGER,
            created_at TEXT NOT NULL,
            -- Ключ личной переписки: "меньший_id:больший_id". Уникальный
            -- индекс по нему не даёт завести два диалога между одними и
            -- теми же людьми, если оба нажали «написать» одновременно.
            dm_key TEXT
        )
    """)

    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_team_dm_key
        ON team_conversations(dm_key) WHERE dm_key IS NOT NULL
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS team_members (
            conversation_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            joined_at TEXT NOT NULL,
            last_read_message_id INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (conversation_id, user_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS team_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL,
            -- Удалённое сообщение остаётся строкой: собеседник уже мог
            -- его прочитать, и бесследное исчезновение выглядит хуже,
            -- чем пометка «сообщение удалено».
            deleted_at TEXT,
            deleted_by INTEGER
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_team_messages_conv
        ON team_messages(conversation_id, id)
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_team_members_user
        ON team_members(user_id)
    """)

    # Одно вложение на сообщение — как в привычных мессенджерах:
    # отправил три фото, вышло три сообщения. Так проще и удалять, и
    # показывать, и не надо решать, что делать с подписью к пачке.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS team_attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL,
            -- image / video / file: по нему страница решает, показать
            -- картинку, проигрыватель или строку со скрепкой
            kind TEXT NOT NULL,
            original_name TEXT NOT NULL,
            mime TEXT,
            size_bytes INTEGER NOT NULL,
            -- пути относительно uploads/messenger, не абсолютные:
            -- иначе при переезде проекта всё отвалится
            stored_path TEXT NOT NULL,
            preview_path TEXT,
            width INTEGER,
            height INTEGER,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_team_attachments_message
        ON team_attachments(message_id)
    """)

    conn.commit()
    conn.close()

    ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)


# =========================================================
# ЛЮДИ
# =========================================================

def list_contacts(me_id: int) -> list[dict]:
    """
    Кому можно написать. Без себя, без отключённых и без скрытой
    технической учётки владельца.
    """

    conn = get_connection()

    rows = conn.execute(
        """
        SELECT id, username, full_name, role, brigade
        FROM users
        WHERE id != ?
          AND COALESCE(is_active, 1) = 1
          AND COALESCE(hidden, 0) = 0
        ORDER BY full_name
        """,
        (me_id,)
    ).fetchall()

    conn.close()

    return [dict(row) for row in rows]


def _is_member(conn, conversation_id: int, user_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM team_members WHERE conversation_id = ? AND user_id = ?",
        (conversation_id, user_id)
    ).fetchone()
    return row is not None


def _members_of(conn, conversation_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT u.id, u.username, u.full_name, u.role,
               COALESCE(u.is_active, 1) AS is_active
        FROM team_members m
        JOIN users u ON u.id = m.user_id
        WHERE m.conversation_id = ?
        ORDER BY u.full_name
        """,
        (conversation_id,)
    ).fetchall()
    return [dict(row) for row in rows]


def _conversation_title(conv: dict, members: list[dict], me_id: int) -> str:
    """
    У группы название своё. У личной переписки названия нет — показываем
    имя собеседника, иначе в списке будут одинаковые строки «Личная».
    """

    if conv["kind"] == KIND_GROUP:
        return conv["title"] or "Группа"

    other = [m for m in members if m["id"] != me_id]

    if other:
        return other[0]["full_name"] or other[0]["username"]

    # Переписка с самим собой не создаётся, но если участник ушёл —
    # диалог не должен остаться без подписи.
    return "Переписка"


# =========================================================
# СПИСОК ПЕРЕПИСОК
# =========================================================

def list_conversations(me_id: int) -> list[dict]:
    """
    Список для левой колонки: с кем, последнее сообщение, сколько
    непрочитанных. Сортировка по последнему сообщению — свежее сверху.
    """

    conn = get_connection()

    rows = conn.execute(
        """
        SELECT c.*, m.last_read_message_id
        FROM team_conversations c
        JOIN team_members m ON m.conversation_id = c.id
        WHERE m.user_id = ?
        """,
        (me_id,)
    ).fetchall()

    out = []

    for row in rows:
        conv = dict(row)
        members = _members_of(conn, conv["id"])

        last = conn.execute(
            """
            SELECT id, user_id, body, created_at, deleted_at
            FROM team_messages
            WHERE conversation_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (conv["id"],)
        ).fetchone()

        unread = conn.execute(
            """
            SELECT COUNT(*) FROM team_messages
            WHERE conversation_id = ? AND id > ? AND user_id != ?
            """,
            (conv["id"], conv["last_read_message_id"], me_id)
        ).fetchone()[0]

        last_msg = dict(last) if last else None

        if last_msg and last_msg["deleted_at"]:
            last_msg["body"] = "сообщение удалено"

        out.append({
            "id": conv["id"],
            "kind": conv["kind"],
            "title": _conversation_title(conv, members, me_id),
            "members": members,
            "members_count": len(members),
            "unread": unread,
            "last_message": last_msg,
            "last_at": last_msg["created_at"] if last_msg else conv["created_at"],
        })

    conn.close()

    out.sort(key=lambda c: c["last_at"], reverse=True)

    return out


def unread_total(me_id: int) -> int:
    """Для значка в меню — одним запросом, без сборки всего списка."""

    conn = get_connection()

    total = conn.execute(
        """
        SELECT COUNT(*)
        FROM team_messages msg
        JOIN team_members mem
          ON mem.conversation_id = msg.conversation_id
         AND mem.user_id = ?
        WHERE msg.id > mem.last_read_message_id
          AND msg.user_id != ?
        """,
        (me_id, me_id)
    ).fetchone()[0]

    conn.close()

    return total


# =========================================================
# СОЗДАНИЕ
# =========================================================

def _dm_key(a: int, b: int) -> str:
    low, high = sorted((a, b))
    return f"{low}:{high}"


def _check_can_write_to(conn, user_id: int) -> dict:
    row = conn.execute(
        """
        SELECT id, full_name, username, COALESCE(is_active, 1) AS is_active
        FROM users WHERE id = ?
        """,
        (user_id,)
    ).fetchone()

    if not row:
        raise ValueError("Такого сотрудника нет.")

    if not row["is_active"]:
        raise ValueError(f"{row['full_name'] or row['username']} — доступ закрыт, написать нельзя.")

    return dict(row)


def open_dm(me_id: int, other_id: int) -> int:
    """Открывает личную переписку или возвращает уже существующую."""

    if me_id == other_id:
        raise ValueError("Нельзя открыть переписку с самим собой.")

    conn = get_connection()

    try:
        _check_can_write_to(conn, other_id)

        key = _dm_key(me_id, other_id)

        existing = conn.execute(
            "SELECT id FROM team_conversations WHERE dm_key = ?", (key,)
        ).fetchone()

        if existing:
            return existing["id"]

        now = _now()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO team_conversations (kind, title, created_by, created_at, dm_key)
            VALUES (?, NULL, ?, ?, ?)
            """,
            (KIND_DM, me_id, now, key)
        )
        conversation_id = cur.lastrowid

        for uid in (me_id, other_id):
            cur.execute(
                "INSERT INTO team_members (conversation_id, user_id, joined_at) VALUES (?, ?, ?)",
                (conversation_id, uid, now)
            )

        conn.commit()
        return conversation_id

    finally:
        conn.close()


def create_group(me_id: int, title: str, member_ids: list[int]) -> int:

    title = (title or "").strip()

    if not title:
        raise ValueError("У группы должно быть название.")

    if len(title) > MAX_TITLE_LENGTH:
        raise ValueError(f"Название длиннее {MAX_TITLE_LENGTH} символов.")

    unique = {int(uid) for uid in member_ids if int(uid) != me_id}

    if not unique:
        raise ValueError("Добавьте хотя бы одного человека.")

    conn = get_connection()

    try:
        for uid in unique:
            _check_can_write_to(conn, uid)

        now = _now()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO team_conversations (kind, title, created_by, created_at, dm_key)
            VALUES (?, ?, ?, ?, NULL)
            """,
            (KIND_GROUP, title, me_id, now)
        )
        conversation_id = cur.lastrowid

        for uid in {me_id} | unique:
            cur.execute(
                "INSERT INTO team_members (conversation_id, user_id, joined_at) VALUES (?, ?, ?)",
                (conversation_id, uid, now)
            )

        conn.commit()
        return conversation_id

    finally:
        conn.close()


# =========================================================
# УЧАСТНИКИ ГРУППЫ
# =========================================================

def _require_group_member(conn, conversation_id: int, me_id: int) -> dict:
    conv = conn.execute(
        "SELECT * FROM team_conversations WHERE id = ?", (conversation_id,)
    ).fetchone()

    if not conv:
        raise ValueError("Переписка не найдена.")

    if not _is_member(conn, conversation_id, me_id):
        raise PermissionError("Вы не участник этой переписки.")

    if conv["kind"] != KIND_GROUP:
        raise ValueError("Состав участников меняется только в группе.")

    return dict(conv)


def add_members(conversation_id: int, me_id: int, user_ids: list[int]) -> list[dict]:

    conn = get_connection()

    try:
        _require_group_member(conn, conversation_id, me_id)

        now = _now()
        cur = conn.cursor()

        for uid in {int(u) for u in user_ids}:
            _check_can_write_to(conn, uid)
            cur.execute(
                """
                INSERT OR IGNORE INTO team_members
                    (conversation_id, user_id, joined_at, last_read_message_id)
                VALUES (?, ?, ?, 0)
                """,
                (conversation_id, uid, now)
            )

        conn.commit()
        return _members_of(conn, conversation_id)

    finally:
        conn.close()


def remove_member(conversation_id: int, me_id: int, user_id: int) -> list[dict]:

    conn = get_connection()

    try:
        _require_group_member(conn, conversation_id, me_id)

        conn.execute(
            "DELETE FROM team_members WHERE conversation_id = ? AND user_id = ?",
            (conversation_id, user_id)
        )
        conn.commit()

        return _members_of(conn, conversation_id)

    finally:
        conn.close()


def rename_group(conversation_id: int, me_id: int, title: str) -> str:

    title = (title or "").strip()

    if not title:
        raise ValueError("У группы должно быть название.")

    if len(title) > MAX_TITLE_LENGTH:
        raise ValueError(f"Название длиннее {MAX_TITLE_LENGTH} символов.")

    conn = get_connection()

    try:
        _require_group_member(conn, conversation_id, me_id)
        conn.execute(
            "UPDATE team_conversations SET title = ? WHERE id = ?",
            (title, conversation_id)
        )
        conn.commit()
        return title

    finally:
        conn.close()


def leave(conversation_id: int, me_id: int) -> None:
    """Выйти можно только из группы: личную переписку не покидают."""

    conn = get_connection()

    try:
        _require_group_member(conn, conversation_id, me_id)
        conn.execute(
            "DELETE FROM team_members WHERE conversation_id = ? AND user_id = ?",
            (conversation_id, me_id)
        )
        conn.commit()

    finally:
        conn.close()


# =========================================================
# СООБЩЕНИЯ
# =========================================================

def _attachments_for(conn, message_ids: list[int]) -> dict:
    """Вложения одним запросом на всю пачку, а не по одному на сообщение."""

    if not message_ids:
        return {}

    marks = ",".join("?" for _ in message_ids)

    rows = conn.execute(
        f"""
        SELECT id, message_id, kind, original_name, mime, size_bytes,
               width, height, preview_path
        FROM team_attachments
        WHERE message_id IN ({marks})
        """,
        message_ids
    ).fetchall()

    out = {}

    for row in rows:
        item = dict(row)
        item["has_preview"] = bool(item.pop("preview_path"))
        item["url"] = f"/api/messenger/attachments/{item['id']}"
        item["preview_url"] = f"/api/messenger/attachments/{item['id']}?preview=1"
        out[item["message_id"]] = item

    return out


def _shape_messages(conn, rows, me_id: int) -> list[dict]:

    messages = []

    for row in rows:
        item = dict(row)
        item["mine"] = item["user_id"] == me_id
        if item["deleted_at"]:
            item["body"] = "сообщение удалено"
        messages.append(item)

    # У удалённого сообщения вложение не показываем: человек нажал
    # «удалить» именно чтобы фото пропало из переписки.
    attachments = _attachments_for(
        conn, [m["id"] for m in messages if not m["deleted_at"]]
    )

    for item in messages:
        item["attachment"] = attachments.get(item["id"])

    return messages


def get_messages(conversation_id: int, me_id: int,
                 after_id: int = 0, before_id: int | None = None,
                 limit: int = 50) -> dict:
    """
    Два режима чтения одной переписки:

        after_id  — что появилось нового. Этим живёт опрос: он тянет
                    только свежие сообщения, а не всю ленту каждые
                    несколько секунд.

        before_id — что было раньше. Этим догружается история, когда
                    человек листает вверх. Переписка хранится целиком
                    и никогда не обрезается — просто показывается
                    порциями, иначе открытие годовой ленты на телефоне
                    заняло бы минуту.

    has_more говорит странице, есть ли ещё что грузить выше: без него
    она пыталась бы подгружать в пустоту на каждой прокрутке.
    """

    conn = get_connection()

    try:
        conv = conn.execute(
            "SELECT * FROM team_conversations WHERE id = ?", (conversation_id,)
        ).fetchone()

        if not conv:
            raise ValueError("Переписка не найдена.")

        if not _is_member(conn, conversation_id, me_id):
            raise PermissionError("Вы не участник этой переписки.")

        limit = max(1, min(int(limit or 50), 200))

        if before_id:
            # Берём последние ДО указанного и разворачиваем: так с краю
            # оказываются ближайшие к уже показанным, а не самые древние.
            rows = conn.execute(
                """
                SELECT m.id, m.user_id, m.body, m.created_at, m.deleted_at,
                       u.full_name, u.username, u.role
                FROM team_messages m
                JOIN users u ON u.id = m.user_id
                WHERE m.conversation_id = ? AND m.id < ?
                ORDER BY m.id DESC
                LIMIT ?
                """,
                (conversation_id, before_id, limit)
            ).fetchall()
            rows = list(reversed(rows))

        elif after_id:
            rows = conn.execute(
                """
                SELECT m.id, m.user_id, m.body, m.created_at, m.deleted_at,
                       u.full_name, u.username, u.role
                FROM team_messages m
                JOIN users u ON u.id = m.user_id
                WHERE m.conversation_id = ? AND m.id > ?
                ORDER BY m.id
                LIMIT ?
                """,
                (conversation_id, after_id, limit)
            ).fetchall()

        else:
            # Первое открытие: показываем хвост переписки, как в любом
            # мессенджере — человек хочет видеть последнее сообщение.
            rows = conn.execute(
                """
                SELECT m.id, m.user_id, m.body, m.created_at, m.deleted_at,
                       u.full_name, u.username, u.role
                FROM team_messages m
                JOIN users u ON u.id = m.user_id
                WHERE m.conversation_id = ?
                ORDER BY m.id DESC
                LIMIT ?
                """,
                (conversation_id, limit)
            ).fetchall()
            rows = list(reversed(rows))

        messages = _shape_messages(conn, rows, me_id)

        oldest = messages[0]["id"] if messages else None

        has_more = False
        if oldest is not None:
            has_more = conn.execute(
                "SELECT 1 FROM team_messages WHERE conversation_id = ? AND id < ? LIMIT 1",
                (conversation_id, oldest)
            ).fetchone() is not None

        members = _members_of(conn, conversation_id)

        return {
            "conversation": {
                "id": conv["id"],
                "kind": conv["kind"],
                "title": _conversation_title(dict(conv), members, me_id),
                "members": members,
                "members_count": len(members),
            },
            "messages": messages,
            "has_more": has_more,
        }

    finally:
        conn.close()


def send_message(conversation_id: int, me_id: int, body: str) -> dict:

    body = (body or "").strip()

    if not body:
        raise ValueError("Пустое сообщение.")

    if len(body) > MAX_MESSAGE_LENGTH:
        raise ValueError(f"Сообщение длиннее {MAX_MESSAGE_LENGTH} символов.")

    conn = get_connection()

    try:
        if not _is_member(conn, conversation_id, me_id):
            raise PermissionError("Вы не участник этой переписки.")

        now = _now()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO team_messages (conversation_id, user_id, body, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (conversation_id, me_id, body, now)
        )
        message_id = cur.lastrowid

        # Своё сообщение сразу считается прочитанным — иначе счётчик
        # непрочитанного загорится у самого отправителя.
        cur.execute(
            "UPDATE team_members SET last_read_message_id = ? WHERE conversation_id = ? AND user_id = ?",
            (message_id, conversation_id, me_id)
        )

        conn.commit()

        row = conn.execute(
            """
            SELECT m.id, m.user_id, m.body, m.created_at, m.deleted_at,
                   u.full_name, u.username, u.role
            FROM team_messages m JOIN users u ON u.id = m.user_id
            WHERE m.id = ?
            """,
            (message_id,)
        ).fetchone()

        item = dict(row)
        item["mine"] = True
        return item

    finally:
        conn.close()


def delete_message(message_id: int, me_id: int) -> None:
    """Удалить можно только своё сообщение."""

    conn = get_connection()

    try:
        row = conn.execute(
            "SELECT user_id, deleted_at FROM team_messages WHERE id = ?", (message_id,)
        ).fetchone()

        if not row:
            raise ValueError("Сообщение не найдено.")

        if row["user_id"] != me_id:
            raise PermissionError("Удалить можно только своё сообщение.")

        if row["deleted_at"]:
            return

        conn.execute(
            "UPDATE team_messages SET deleted_at = ?, deleted_by = ? WHERE id = ?",
            (_now(), me_id, message_id)
        )
        conn.commit()

    finally:
        conn.close()


def mark_read(conversation_id: int, me_id: int, message_id: int | None = None) -> int:
    """
    Отмечает прочитанным до message_id (или до последнего). Назад не
    отматывает: если открыть старое сообщение, счётчик не должен
    вырасти обратно.
    """

    conn = get_connection()

    try:
        if not _is_member(conn, conversation_id, me_id):
            raise PermissionError("Вы не участник этой переписки.")

        if message_id is None:
            row = conn.execute(
                "SELECT COALESCE(MAX(id), 0) AS last FROM team_messages WHERE conversation_id = ?",
                (conversation_id,)
            ).fetchone()
            message_id = row["last"]

        conn.execute(
            """
            UPDATE team_members
            SET last_read_message_id = ?
            WHERE conversation_id = ? AND user_id = ? AND last_read_message_id < ?
            """,
            (message_id, conversation_id, me_id, message_id)
        )
        conn.commit()

        return message_id

    finally:
        conn.close()


# =========================================================
# ВЛОЖЕНИЯ
# =========================================================

def _classify(mime: str | None, name: str) -> str:
    """
    Чем показывать: картинкой, проигрывателем или строкой файла.

    MIME с телефона приходит не всегда, поэтому если его нет —
    угадываем по расширению.
    """

    mime = (mime or "").lower().split(";")[0].strip()

    if not mime:
        mime = mimetypes.guess_type(name)[0] or ""

    if mime in INLINE_IMAGE_TYPES:
        return KIND_IMAGE

    if mime in INLINE_VIDEO_TYPES:
        return KIND_VIDEO

    return KIND_FILE


def _safe_name(name: str) -> str:
    """
    Имя от пользователя показываем, но НЕ используем как путь: в нём
    может приехать «../../factory.db». На диск кладём случайное имя.
    """

    name = (name or "").replace("\\", "/").split("/")[-1].strip()
    return name[:120] or "файл"


def _make_preview(stored: Path, kind: str) -> tuple[Path | None, int | None, int | None]:
    """
    Уменьшенная копия картинки для показа в ленте. Заодно снимает EXIF:
    в нём с телефона приезжают GPS-координаты съёмки и модель аппарата,
    а переписку могут переслать дальше.

    Без Pillow просто показываем оригинал — это хуже по трафику, но
    работает.
    """

    if kind != KIND_IMAGE:
        return None, None, None

    try:
        from PIL import Image
    except ImportError:
        return None, None, None

    try:
        with Image.open(stored) as img:
            img.load()
            width, height = img.width, img.height

            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            img.thumbnail((PREVIEW_MAX_SIDE, PREVIEW_MAX_SIDE), Image.LANCZOS)

            preview = stored.with_name(stored.stem + "_preview.jpg")
            # save без exif= — метаданные не переносятся
            img.save(preview, format="JPEG", quality=PREVIEW_QUALITY, optimize=True)

            return preview, width, height

    except Exception:
        # Битая или необычная картинка — не повод терять сообщение.
        return None, None, None


def save_attachment(conversation_id: int, me_id: int, temp_path: Path,
                    original_name: str, mime: str | None,
                    caption: str = "") -> dict:
    """
    Кладёт уже принятый файл на место и создаёт сообщение с вложением.

    Файл приходит временным: роут пишет его на диск потоком, чтобы
    полсотни мегабайт не оказались в памяти целиком.
    """

    temp_path = Path(temp_path)

    size = temp_path.stat().st_size

    if size == 0:
        temp_path.unlink(missing_ok=True)
        raise ValueError("Файл пустой.")

    if size > MAX_ATTACHMENT_BYTES:
        temp_path.unlink(missing_ok=True)
        raise ValueError(f"Файл больше {MAX_ATTACHMENT_BYTES // (1024 * 1024)} МБ.")

    caption = (caption or "").strip()[:MAX_MESSAGE_LENGTH]
    original_name = _safe_name(original_name)

    conn = get_connection()

    try:
        if not _is_member(conn, conversation_id, me_id):
            temp_path.unlink(missing_ok=True)
            raise PermissionError("Вы не участник этой переписки.")

        kind = _classify(mime, original_name)

        # Раскладываем по месяцам: за год переписки в одной папке
        # набралось бы столько файлов, что ls перестанет отвечать.
        month = datetime.now().strftime("%Y-%m")
        folder = ATTACHMENTS_DIR / month
        folder.mkdir(parents=True, exist_ok=True)

        suffix = Path(original_name).suffix.lower()[:12]
        stored = folder / f"{uuid.uuid4().hex}{suffix}"

        shutil.move(str(temp_path), str(stored))

        preview, width, height = _make_preview(stored, kind)

        now = _now()
        cur = conn.cursor()

        # Подпись к файлу — обычный текст сообщения. Пустая подпись
        # тоже нормально: чаще фото отправляют молча.
        cur.execute(
            """
            INSERT INTO team_messages (conversation_id, user_id, body, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (conversation_id, me_id, caption, now)
        )
        message_id = cur.lastrowid

        cur.execute(
            """
            INSERT INTO team_attachments
                (message_id, kind, original_name, mime, size_bytes,
                 stored_path, preview_path, width, height, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id, kind, original_name,
                (mime or "").split(";")[0].strip() or None,
                size,
                str(stored.relative_to(ATTACHMENTS_DIR)),
                str(preview.relative_to(ATTACHMENTS_DIR)) if preview else None,
                width, height, now,
            )
        )

        cur.execute(
            "UPDATE team_members SET last_read_message_id = ? WHERE conversation_id = ? AND user_id = ?",
            (message_id, conversation_id, me_id)
        )

        conn.commit()

        row = conn.execute(
            """
            SELECT m.id, m.user_id, m.body, m.created_at, m.deleted_at,
                   u.full_name, u.username, u.role
            FROM team_messages m JOIN users u ON u.id = m.user_id
            WHERE m.id = ?
            """,
            (message_id,)
        ).fetchone()

        message = _shape_messages(conn, [row], me_id)[0]
        return message

    finally:
        temp_path.unlink(missing_ok=True)
        conn.close()


def get_attachment(attachment_id: int, me_id: int, preview: bool = False) -> dict:
    """
    Отдаёт путь к файлу, проверив, что человек состоит в переписке.
    Без этой проверки ссылку на фото можно было бы переслать кому
    угодно, и она открылась бы.
    """

    conn = get_connection()

    try:
        row = conn.execute(
            """
            SELECT a.*, m.conversation_id, m.deleted_at
            FROM team_attachments a
            JOIN team_messages m ON m.id = a.message_id
            WHERE a.id = ?
            """,
            (attachment_id,)
        ).fetchone()

        if not row:
            raise ValueError("Файл не найден.")

        if not _is_member(conn, row["conversation_id"], me_id):
            raise PermissionError("Это вложение из чужой переписки.")

        if row["deleted_at"]:
            raise ValueError("Сообщение удалено.")

        relative = row["preview_path"] if (preview and row["preview_path"]) else row["stored_path"]
        path = ATTACHMENTS_DIR / relative

        if not path.exists():
            raise ValueError("Файл не найден на диске.")

        is_preview = preview and bool(row["preview_path"])

        return {
            "path": path,
            "mime": "image/jpeg" if is_preview else (row["mime"] or "application/octet-stream"),
            "original_name": row["original_name"],
            "kind": row["kind"],
            "is_preview": is_preview,
        }

    finally:
        conn.close()
