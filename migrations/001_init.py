"""
Первая миграция: создаёт все таблицы и (если её ещё нет) учётку директора.

Правило из ACAI, которое действует и здесь: миграция запускается
ДО обновления/перезапуска кода на сервере, иначе новый код обратится
к таблице, которой ещё нет.

Запуск:
    python -m migrations.001_init
"""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import Base, engine, SessionLocal
from backend import models
from backend.auth import hash_password
from backend.config import ROLE_DIRECTOR


def run():
    print("Создаю таблицы...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        existing_director = (
            db.query(models.User).filter(models.User.role == ROLE_DIRECTOR).first()
        )
        if existing_director:
            print(f"Директор уже есть: {existing_director.username}. Пропускаю.")
            return

        print("Учётки директора нет — создадим первую.")
        username = input("Логин директора: ").strip()
        full_name = input("Полное имя: ").strip()
        password = getpass.getpass("Пароль: ")

        user = models.User(
            username=username,
            full_name=full_name,
            hashed_password=hash_password(password),
            role=ROLE_DIRECTOR,
        )
        db.add(user)
        db.commit()
        print(f"Готово: {username} создан с ролью {ROLE_DIRECTOR}.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
