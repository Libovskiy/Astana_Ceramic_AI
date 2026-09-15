import datetime as dt
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from backend.config import MONITORING_SECRET_KEY as SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from backend.database import get_db
from backend import models

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# Работаем с bcrypt напрямую, без passlib: passlib 1.7.4 несовместим
# с bcrypt>=4.1 (пытается прочитать удалённый атрибут __about__).
_BCRYPT_MAX_BYTES = 72  # ограничение самого алгоритма bcrypt


def hash_password(password: str) -> str:
    pw_bytes = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(pw_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    pw_bytes = plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.checkpw(pw_bytes, hashed.encode("utf-8"))


def create_access_token(user: models.User) -> str:
    """
    Токен несёт версию (token_version) на момент выдачи. Если у
    пользователя её потом увеличат (увольнение/деактивация/смена
    пароля) — этот токен перестаёт проходить проверку немедленно,
    даже если срок жизни (exp) ещё не истёк.
    """
    expire = dt.datetime.utcnow() + dt.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": user.username,
        "role": user.role,
        "tv": user.token_version,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> models.User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Не удалось подтвердить учётные данные",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: Optional[str] = payload.get("sub")
        token_version = payload.get("tv")
        if username is None or token_version is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None or not user.is_active:
        raise credentials_exception
    # Токен выпущен до увольнения/деактивации/смены пароля — не годится,
    # даже если формально ещё не истёк по времени.
    if user.token_version != token_version:
        raise credentials_exception
    return user


def revoke_all_sessions(db: Session, user: models.User) -> None:
    """Увеличивает token_version — все ранее выданные токены этого пользователя сразу умирают."""
    user.token_version = (user.token_version or 0) + 1
    db.commit()


def require_roles(*roles):
    """Dependency-фабрика: require_roles("director", "admin") — только эти роли пройдут."""

    def checker(user: models.User = Depends(get_current_user)) -> models.User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для этого действия",
            )
        return user

    return checker
