"""
Простой rate limiting в памяти процесса — без внешних зависимостей
(без slowapi/redis). Подходит для одного uvicorn-процесса, что типично
для внутреннего заводского приложения на локальном сервере.

Если позже перейдёте на несколько воркеров/серверов за балансировщиком —
у каждого будет своя копия счётчиков, и лимит перестанет быть точным.
В этом случае нужно вынести счётчики в Redis. Для старта — не нужно.
"""

import time
import threading
from collections import defaultdict


_lock = threading.Lock()
_requests_by_key = defaultdict(list)

# Не более MAX_REQUESTS запросов за WINDOW_SECONDS на один ключ
# (ключ — обычно "имя_роута:user_id").
MAX_REQUESTS = 10
WINDOW_SECONDS = 60


def check_rate_limit(key: str) -> bool:
    """
    True — запрос разрешён (и сразу засчитан).
    False — лимит на этот ключ исчерпан, запрос нужно отклонить.
    """

    now = time.time()

    with _lock:

        timestamps = _requests_by_key[key]

        # чистим метки времени старше окна
        cutoff = now - WINDOW_SECONDS
        timestamps[:] = [t for t in timestamps if t > cutoff]

        if len(timestamps) >= MAX_REQUESTS:
            return False

        timestamps.append(now)

        return True
