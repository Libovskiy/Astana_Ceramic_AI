"""
Аутентификация, роли и привязка рабочих к конкретному оборудованию.

РОЛИ:
- admin             — вы, техническая роль: управление пользователями + видит
                       всё, что видит director. Обходит все проверки ролей.
- director          — директор, видит всё (без управления пользователями).
- chief_engineer     — главный инженер: подтверждает/правит черновики закрытия
                       обращений, которые составил shift_supervisor. Один на
                       весь завод (решение принято осознанно).
- engineer          — инженер: доступ к диагностике/оборудованию, без права
                       финального подтверждения обращений.
- shift_supervisor  — начальник смены: создаёт ЧЕРНОВИК закрытия обращения
                       ("проводник" между цехом и офисом), финал не за ним.
- worker            — рабочий: видит и диагностирует ТОЛЬКО те станки, что
                       ему назначены (таблица worker_equipment), а не всю
                       линию целиком.
- technologist      — технолог: расчёт состава смеси (глина/песок), журнал.
- lab_technician    — лаборант: тот же модуль состава смеси, что и технолог.
- chief_mechanic    — главный механик: видит дашборд, диагностика,
                       "Обслуживание выполнено", журнал действий.
- mechanic          — слесарь: диагностика + "Обслуживание выполнено".
- chief_electrician — главный электрик: те же права, что у гл. механика
                       (фильтрации именно электрического оборудования
                       пока нет — общий доступ).
- electrician       — электрик: диагностика + "Обслуживание выполнено".
- analyst           — аналитик. Дашборд/отчёты на чтение.

Пароли — PBKDF2-HMAC-SHA256 с солью на пользователя, без внешних
зависимостей. Сессии — httpOnly cookie, токен в таблице sessions,
живёт 12 часов.
"""

import sqlite3
import hashlib
import secrets
import re
from datetime import datetime, timedelta

from backend.config import DB_NAME, OWNERS


SESSION_LIFETIME_HOURS = 12

VALID_ROLES = (
    "admin",
    "director",
    "chief_engineer",
    "engineer",
    "shift_supervisor",
    "worker",
    "technologist",
    "lab_technician",
    "chief_mechanic",
    "mechanic",
    "chief_electrician",
    "electrician",
    "analyst",
)

PBKDF2_ITERATIONS = 200_000


def get_connection():

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row

    return conn


# =========================================================
# INIT TABLES
# =========================================================

def init_auth_tables():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            full_name TEXT,
            role TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
    """)

    # -----------------------------------------
    # Какое конкретное оборудование назначено рабочему.
    # Актуально только для role='worker'.
    # -----------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS worker_equipment (
            user_id INTEGER NOT NULL,
            equipment_id INTEGER NOT NULL,
            PRIMARY KEY (user_id, equipment_id)
        )
    """)

    # -----------------------------------------
    # is_active — отключён ли доступ (уволился, ушёл в отпуск,
    # перевёлся). Это НЕ то же самое, что hidden: hidden лишь убирает
    # учётку из списка (нужно для технической учётки владельца, она
    # обязана работать), а is_active = 0 запрещает вход.
    #
    # Отключение вместо удаления: фамилия остаётся в закрытых
    # обращениях, отчётах и задачах — иначе история смен теряет автора.
    # -----------------------------------------

    columns = {row["name"] for row in cursor.execute("PRAGMA table_info(users)")}

    if "is_active" not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN is_active INTEGER DEFAULT 1")
        cursor.execute("UPDATE users SET is_active = 1 WHERE is_active IS NULL")

    conn.commit()
    conn.close()


# =========================================================
# PASSWORD HASHING
# =========================================================

def _hash_password(password: str, salt: str) -> str:

    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ITERATIONS
    ).hex()


# =========================================================
# CREATE USER
# =========================================================

def validate_password_strength(password: str) -> None:
    """
    Бросает ValueError с понятным описанием, если пароль слабый.
    Требования: не короче 10 символов, есть заглавная буква,
    строчная буква и цифра. Спецсимвол не требуем — для
    сотрудников завода это часто становится барьером, а от
    основных рисков (перебор, угадывание) достаточно и этого.
    """

    if len(password) < 10:
        raise ValueError("Пароль должен быть не короче 10 символов.")

    if not re.search(r"[A-ZА-Я]", password):
        raise ValueError("Пароль должен содержать хотя бы одну заглавную букву.")

    if not re.search(r"[a-zа-я]", password):
        raise ValueError("Пароль должен содержать хотя бы одну строчную букву.")

    if not re.search(r"\d", password):
        raise ValueError("Пароль должен содержать хотя бы одну цифру.")


def create_user(username: str, password: str, full_name: str, role: str) -> int:

    if role not in VALID_ROLES:
        raise ValueError(
            f"Недопустимая роль '{role}'. Допустимые: {', '.join(VALID_ROLES)}"
        )

    validate_password_strength(password)

    salt = secrets.token_hex(16)
    password_hash = _hash_password(password, salt)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO users (
            username, password_hash, password_salt,
            full_name, role, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            username,
            password_hash,
            salt,
            full_name,
            role,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
    )

    user_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return user_id


# =========================================================
# AUTHENTICATE
# =========================================================

class AccessDisabled(Exception):
    """Пароль верный, но доступ учётке закрыт (is_active = 0)."""


def authenticate(username: str, password: str):
    """
    Возвращает пользователя или None, если логина нет либо пароль неверный.

    Если пароль верный, но доступ отключён — поднимает AccessDisabled.
    Человеку важно видеть разницу: иначе уволенный или отстранённый
    будет считать, что опечатался, и звонить в IT вместо начальника.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM users WHERE username = ?",
        (username,)
    )

    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    expected_hash = _hash_password(password, row["password_salt"])

    if not secrets.compare_digest(expected_hash, row["password_hash"]):
        return None

    user = dict(row)

    if not user.get("is_active", 1):
        raise AccessDisabled()

    return user


# =========================================================
# SESSIONS
# =========================================================

def create_session(user_id: int) -> str:

    token = secrets.token_hex(32)

    now = datetime.now()
    expires_at = now + timedelta(hours=SESSION_LIFETIME_HOURS)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO sessions (token, user_id, created_at, expires_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            token,
            user_id,
            now.strftime("%Y-%m-%d %H:%M:%S"),
            expires_at.strftime("%Y-%m-%d %H:%M:%S")
        )
    )

    conn.commit()
    conn.close()

    return token


def get_user_by_session(token: str | None):

    if not token:
        return None

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            users.id,
            users.username,
            users.full_name,
            users.role,
            users.brigade,
            COALESCE(users.is_active, 1) AS is_active,
            sessions.expires_at AS session_expires_at
        FROM sessions
        JOIN users ON users.id = sessions.user_id
        WHERE sessions.token = ?
        """,
        (token,)
    )

    row = cursor.fetchone()

    if not row:
        conn.close()
        return None

    # Доступ отключили, пока человек уже был в системе: обрываем вход
    # здесь же, не дожидаясь, пока истечёт срок сессии.
    if not row["is_active"]:

        cursor.execute(
            "DELETE FROM sessions WHERE token = ?",
            (token,)
        )

        conn.commit()
        conn.close()

        return None

    expires_at = datetime.strptime(
        row["session_expires_at"],
        "%Y-%m-%d %H:%M:%S"
    )

    if datetime.now() > expires_at:

        cursor.execute(
            "DELETE FROM sessions WHERE token = ?",
            (token,)
        )

        conn.commit()
        conn.close()

        return None

    conn.close()

    return dict(row)


def delete_session(token: str | None):

    if not token:
        return

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM sessions WHERE token = ?",
        (token,)
    )

    conn.commit()
    conn.close()


def revoke_all_sessions(user_id: int) -> int:
    """
    Удаляет ВСЕ активные сессии пользователя — на всех устройствах,
    не только текущую. Нужно для:
    1. Самостоятельного "выйти везде" (например, забыли выйти
       на чужом компьютере).
    2. Принудительного разлогина администратором (уволили
       сотрудника, подозрение на компрометацию аккаунта и т.д.) —
       в этом случае даже с ещё не истёкшей сессией человек будет
       вынужден заново войти при следующем запросе.

    Возвращает количество удалённых сессий.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM sessions WHERE user_id = ?",
        (user_id,)
    )

    deleted_count = cursor.rowcount

    conn.commit()
    conn.close()

    return deleted_count


def get_user_by_username(username: str):
    """
    Нужен для админского "отозвать сессии конкретного сотрудника
    по логину" — без этого пришлось бы искать user_id вручную в БД.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, username, full_name, role FROM users WHERE username = ?",
        (username,)
    )

    row = cursor.fetchone()
    conn.close()

    return dict(row) if row else None


# =========================================================
# WORKER <-> EQUIPMENT ASSIGNMENT
# =========================================================

def assign_equipment(user_id: int, equipment_ids: list[int]):
    """
    Полностью заменяет список станков, назначенных рабочему,
    на переданный. Пустой список — снять все назначения.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM worker_equipment WHERE user_id = ?",
        (user_id,)
    )

    for equipment_id in equipment_ids:

        cursor.execute(
            """
            INSERT OR IGNORE INTO worker_equipment (user_id, equipment_id)
            VALUES (?, ?)
            """,
            (user_id, equipment_id)
        )

    conn.commit()
    conn.close()


def get_assigned_equipment_ids(user_id: int) -> list[int]:

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT equipment_id FROM worker_equipment WHERE user_id = ?",
        (user_id,)
    )

    rows = cursor.fetchall()
    conn.close()

    return [row["equipment_id"] for row in rows]


def get_all_users():
    """
    Для страницы "Настройки → Пользователи" — список без хэшей
    паролей (secrets никогда не должны уходить на фронтенд).

    СКРЫТЫЕ УЧЁТКИ (users.hidden = 1) не показываются НИКОМУ,
    включая других администраторов. Нужно для технической учётной
    записи владельца системы: она есть, работает, но в списке
    пользователей её не видно и удалить через веб её нельзя.

    Скрыть учётку можно только из терминала: python manage_admin.py
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, username, full_name, role, brigade, created_at,
               COALESCE(is_active, 1) AS is_active
        FROM users
        WHERE COALESCE(hidden, 0) = 0
        ORDER BY id
        """
    )

    rows = cursor.fetchall()

    conn.close()

    return [dict(row) for row in rows]


def update_user_role(user_id, new_role):

    if new_role not in VALID_ROLES:
        raise ValueError(f"Недопустимая роль '{new_role}'. Допустимые: {', '.join(VALID_ROLES)}")

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, COALESCE(hidden, 0) AS hidden FROM users WHERE id = ?", (user_id,))

    row = cursor.fetchone()

    if not row:
        conn.close()
        raise ValueError("Пользователь не найден.")

    # Скрытую учётку через веб не трогаем: иначе администратор,
    # случайно узнав её id, сменит ей роль и заблокирует владельца.
    if row["hidden"]:
        conn.close()
        raise ValueError("Пользователь не найден.")

    cursor.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))

    conn.commit()
    conn.close()


def delete_user(user_id):
    """Удаляет пользователя полностью — вместе с его сессиями и
    назначенным оборудованием (иначе останутся висящие записи,
    ссылающиеся на несуществующего пользователя)."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, COALESCE(hidden, 0) AS hidden FROM users WHERE id = ?", (user_id,))

    row = cursor.fetchone()

    if not row or row["hidden"]:
        conn.close()
        raise ValueError("Пользователь не найден.")

    cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM worker_equipment WHERE user_id = ?", (user_id,))

    # Назначения задач тоже ссылаются на user_id: без этой уборки
    # задача остаётся назначенной на несуществующего человека и
    # пропадает из чужих списков, хотя формально ещё открыта.
    cursor.execute("DELETE FROM task_assignees WHERE user_id = ?", (user_id,))

    cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))

    conn.commit()
    conn.close()

def set_password(user_id: int, new_password: str) -> None:
    """
    Смена пароля. Пароль НЕ сохраняется в открытом виде — считается
    новый хэш с новой солью, старый перестаёт работать сразу.

    Показать существующий пароль невозможно ни администратору, ни
    владельцу системы: в базе его нет. Это не ограничение ACAI, так
    устроено везде, где пароли хранят правильно. Забыл — сбрасываем
    и выдаём новый.
    """

    validate_password_strength(new_password)

    salt = secrets.token_hex(16)
    password_hash = _hash_password(new_password, salt)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM users WHERE id = ?", (user_id,))

    if not cursor.fetchone():
        conn.close()
        raise ValueError("Пользователь не найден.")

    cursor.execute(
        "UPDATE users SET password_hash = ?, password_salt = ? WHERE id = ?",
        (password_hash, salt, user_id)
    )

    # Все старые сессии закрываем: если пароль меняют из-за того,
    # что он утёк, чужой открытый вход должен оборваться.
    cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    conn.commit()
    conn.close()


def set_hidden(user_id: int, hidden: bool) -> None:
    """
    Скрыть учётку из списка пользователей (или показать обратно).

    ВНИМАНИЕ: это только видимость в списке — скрытая учётка работает
    и входит как обычно (так и надо для технической учётки владельца).
    Чтобы закрыть доступ, нужен set_active(user_id, False).
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE users SET hidden = ? WHERE id = ?",
        (1 if hidden else 0, user_id)
    )

    conn.commit()
    conn.close()


def set_active(user_id: int, active: bool) -> dict:
    """
    Закрыть или вернуть доступ. Это замена удалению: уволенный войти
    не может, но его фамилия остаётся в закрытых обращениях, сменных
    отчётах и задачах — история смены не теряет автора.

    При отключении все открытые сессии закрываются сразу: человек,
    который сидит в системе с телефона, вылетает на следующем действии.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, username, full_name, COALESCE(hidden, 0) AS hidden FROM users WHERE id = ?",
        (user_id,)
    )

    row = cursor.fetchone()

    if not row:
        conn.close()
        raise ValueError("Пользователь не найден.")

    # Учётку владельца отключать нельзя: через неё входят, когда всё
    # остальное сломано, и только она распоряжается бэкапами.
    # Скрытая учётка (hidden) — тот же случай: она техническая.
    if not active and (row["hidden"] or row["username"] in OWNERS):
        conn.close()
        raise ValueError("Эту учётку отключить нельзя.")

    cursor.execute(
        "UPDATE users SET is_active = ? WHERE id = ?",
        (1 if active else 0, user_id)
    )

    if not active:
        cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    conn.commit()
    conn.close()

    return {"id": row["id"], "username": row["username"],
            "full_name": row["full_name"], "is_active": active}


def rename_user(user_id: int, new_username: str = None, new_full_name: str = None) -> None:
    """
    Сменить логин и/или имя.

    Логин менять безопасно: обращения, переписка и журнал действий
    хранят ИМЯ человека текстом на момент действия, а не ссылку на
    учётку. То есть запись "Иванов подтвердил закрытие" останется
    как есть, даже если логин потом сменится.

    Сессии при смене логина закрываются: человек войдёт заново уже
    под новым.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM users WHERE id = ?", (user_id,))

    if not cursor.fetchone():
        conn.close()
        raise ValueError("Пользователь не найден.")

    if new_username:

        new_username = new_username.strip()

        if not new_username:
            conn.close()
            raise ValueError("Логин не может быть пустым.")

        cursor.execute(
            "SELECT id FROM users WHERE username = ? AND id != ?",
            (new_username, user_id)
        )

        if cursor.fetchone():
            conn.close()
            raise ValueError(f"Логин '{new_username}' уже занят.")

        cursor.execute(
            "UPDATE users SET username = ? WHERE id = ?",
            (new_username, user_id)
        )

        cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    if new_full_name is not None:

        cursor.execute(
            "UPDATE users SET full_name = ? WHERE id = ?",
            (new_full_name.strip(), user_id)
        )

    conn.commit()
    conn.close()
