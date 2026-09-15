"""
Создание пользователей ACAI.

Роли: admin, director, chief_engineer, engineer, shift_supervisor,
worker, technologist, lab_technician, chief_mechanic, mechanic,
chief_electrician, electrician, analyst.

Если роль worker — сразу спрашивает, какие станки закрепить за рабочим
(вводится списком ID через запятую, список станков показывается перед
вопросом).

Запуск: python create_user.py
Разместить в корне проекта.
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))


import getpass

from backend.services.auth_service import (
    init_auth_tables,
    create_user,
    assign_equipment,
    validate_password_strength,
    VALID_ROLES
)
from backend.services.equipment_service import (
    init_equipment,
    get_all_equipment
)


def main():

    init_auth_tables()
    init_equipment()

    print("Создание нового пользователя ACAI")
    print(f"Доступные роли: {', '.join(VALID_ROLES)}")
    print()

    username = input("Логин: ").strip()
    full_name = input("Имя и фамилия: ").strip()
    role = input("Роль: ").strip()

    if role not in VALID_ROLES:
        print(f"\nОшибка: роль должна быть одной из: {', '.join(VALID_ROLES)}")
        return

    print(
        "\nПароль должен быть не короче 10 символов, содержать "
        "заглавную букву, строчную букву и цифру."
    )

    while True:

        password = getpass.getpass("Пароль: ")

        try:
            validate_password_strength(password)
            break
        except ValueError as error:
            print(f"Не подходит: {error} Попробуйте ещё раз.")

    password_confirm = getpass.getpass("Повторите пароль: ")

    if password != password_confirm:
        print("\nОшибка: пароли не совпадают.")
        return

    try:

        user_id = create_user(username, password, full_name, role)

        print(f"\nПользователь '{username}' ({role}) успешно создан.")

    except ValueError as error:

        print(f"\nОшибка: {error}")
        return

    except Exception as error:

        print(f"\nНе удалось создать пользователя: {error}")
        return

    # -----------------------------------------
    # Для worker — сразу назначаем станки
    # -----------------------------------------

    if role == "worker":

        equipment = get_all_equipment()

        if not equipment:
            print("\nВ базе пока нет оборудования — станки можно будет назначить позже.")
            return

        print("\nДоступное оборудование:")

        for item in equipment:
            print(f"  {item['id']}: {item['name']} ({item['type']}, {item['location']})")

        raw_ids = input(
            "\nВведите ID станков через запятую для этого рабочего "
            "(например: 1,2), или Enter чтобы пропустить: "
        ).strip()

        if raw_ids:

            try:

                ids = [
                    int(piece.strip())
                    for piece in raw_ids.split(",")
                    if piece.strip()
                ]

                assign_equipment(user_id, ids)

                print(f"Рабочему назначены станки: {ids}")

            except ValueError:

                print("Не удалось распознать список ID — назначение пропущено, сделайте это позже вручную.")


if __name__ == "__main__":
    main()
