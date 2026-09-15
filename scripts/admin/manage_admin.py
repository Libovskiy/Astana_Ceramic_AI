"""
Управление учётными записями из терминала — то, чего намеренно
нет в веб-интерфейсе.

Здесь три вещи, которые нельзя отдавать в браузер:

1. СБРОС ПАРОЛЯ.
   Показать существующий пароль невозможно: в базе лежит только
   хэш PBKDF2, обратно он не разворачивается. Это не ограничение
   ACAI — так устроено везде, где пароли хранят правильно. Если бы
   пароли лежали открытым текстом, любой, кто получит копию
   factory.db (а она есть в каждом бэкапе и на флешке, которой вы
   их носите), получил бы доступ ко всем учёткам разом, включая
   директора.
   Поэтому: забыл пароль — выдаём новый.

2. СКРЫТАЯ УЧЁТКА.
   Помеченная скрытой не показывается в "Настройки → Пользователи"
   никому, включая администраторов. Её нельзя удалить или сменить
   ей роль через веб. Работает при этом как обычная.

3. Всё это требует доступа к серверу. Если человек уже сидит за
   этим макбуком с паролем от него — он и так может всё.

Запуск:
    python manage_admin.py list
    python manage_admin.py reset ЛОГИН
    python manage_admin.py hide ЛОГИН
    python manage_admin.py show ЛОГИН
    python manage_admin.py create ЛОГИН РОЛЬ "Имя Фамилия"
    python manage_admin.py rename СТАРЫЙ_ЛОГИН НОВЫЙ_ЛОГИН
    python manage_admin.py name ЛОГИН "Иванов Пётр Сергеевич"
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))


import sys
import sqlite3
import secrets

from backend.config import DB_NAME
from backend.services.auth_service import (
    init_auth_tables,
    create_user,
    set_password,
    set_hidden,
    rename_user,
    VALID_ROLES
)


def connect():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_column():
    """Колонка hidden — добавляется при первом запуске."""

    conn = connect()
    cursor = conn.cursor()

    columns = {row[1] for row in cursor.execute("PRAGMA table_info(users)").fetchall()}

    if "hidden" not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN hidden INTEGER DEFAULT 0")
        conn.commit()
        print("Колонка users.hidden добавлена.")

    conn.close()


def find(username):
    conn = connect()
    row = conn.execute(
        "SELECT id, username, full_name, role, COALESCE(hidden,0) AS hidden FROM users WHERE username = ?",
        (username,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def generate_password():
    return "Acai" + secrets.token_hex(3) + str(secrets.randbelow(90) + 10)


def cmd_list():

    conn = connect()

    rows = conn.execute(
        """
        SELECT id, username, full_name, role, brigade, COALESCE(hidden,0) AS hidden
        FROM users ORDER BY id
        """
    ).fetchall()

    conn.close()

    print(f"\n{'id':<5}{'логин':<16}{'роль':<18}{'смена':<8}{'имя'}")
    print("-" * 78)

    for row in rows:
        mark = "  [СКРЫТ]" if row["hidden"] else ""
        print(
            f"{row['id']:<5}{row['username']:<16}{row['role']:<18}"
            f"{row['brigade'] or '—':<8}{(row['full_name'] or '')[:30]}{mark}"
        )

    print(f"\nВсего: {len(rows)}")
    print("Пароли не показываются — в базе их нет, только хэши.\n")


def cmd_reset(username):

    user = find(username)

    if not user:
        print(f"Пользователь '{username}' не найден.")
        return

    password = generate_password()

    try:
        set_password(user["id"], password)
    except ValueError as error:
        print(f"Ошибка: {error}")
        return

    print(f"\nПароль для '{username}' изменён.")
    print(f"\n    {password}\n")
    print("Передайте сотруднику. Больше этот пароль нигде не появится —")
    print("если потеряете, сбросите ещё раз.")
    print("Все открытые сессии этого пользователя закрыты.\n")


def cmd_hide(username, hidden):

    user = find(username)

    if not user:
        print(f"Пользователь '{username}' не найден.")
        return

    set_hidden(user["id"], hidden)

    if hidden:
        print(f"'{username}' скрыт: его больше нет в списке пользователей,")
        print("его нельзя удалить или сменить роль через веб. Вход работает.")
    else:
        print(f"'{username}' снова виден в списке.")


def cmd_create(username, role, full_name):

    if role not in VALID_ROLES:
        print(f"Роль должна быть одной из: {', '.join(VALID_ROLES)}")
        return

    if find(username):
        print(f"Пользователь '{username}' уже существует.")
        return

    password = generate_password()

    try:
        create_user(username, password, full_name, role)
    except ValueError as error:
        print(f"Ошибка: {error}")
        return

    print(f"\nСоздан '{username}' ({role}).")
    print(f"\n    {password}\n")
    print("Чтобы скрыть из списка: python manage_admin.py hide " + username + "\n")



def cmd_rename(username, new_username):

    user = find(username)

    if not user:
        print(f"Пользователь '{username}' не найден.")
        return

    try:
        rename_user(user["id"], new_username=new_username)
    except ValueError as error:
        print(f"Ошибка: {error}")
        return

    print(f"Логин изменён: {username} -> {new_username}")
    print("Пароль прежний. Сессии закрыты — войти нужно заново.")
    print("История обращений сохранена: там записано имя человека,")
    print("а не ссылка на учётку.")


def cmd_name(username, full_name):

    user = find(username)

    if not user:
        print(f"Пользователь '{username}' не найден.")
        return

    try:
        rename_user(user["id"], new_full_name=full_name)
    except ValueError as error:
        print(f"Ошибка: {error}")
        return

    print(f"Имя изменено: '{user['full_name'] or '—'}' -> '{full_name}'")
    print("Оно будет видно в переписке и журнале действий.")


def main():

    init_auth_tables()
    ensure_column()

    args = sys.argv[1:]

    if not args:
        print(__doc__)
        return

    command = args[0]

    if command == "list":
        cmd_list()

    elif command == "reset" and len(args) >= 2:
        cmd_reset(args[1])

    elif command == "hide" and len(args) >= 2:
        cmd_hide(args[1], True)

    elif command == "show" and len(args) >= 2:
        cmd_hide(args[1], False)

    elif command == "create" and len(args) >= 4:
        cmd_create(args[1], args[2], " ".join(args[3:]))

    elif command == "rename" and len(args) >= 3:
        cmd_rename(args[1], args[2])

    elif command == "name" and len(args) >= 3:
        cmd_name(args[1], " ".join(args[2:]))

    else:
        print(__doc__)


if __name__ == "__main__":
    main()
