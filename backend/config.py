"""
Все пути и настройки в одном месте — как в основном ACAI (backend/config.py).
Если этот модуль подключается к уже существующему проекту ACAI, можно
скопировать содержимое сюда же в существующий config.py (одним блоком) —
имена переменных подобраны так, чтобы не конфликтовать со стандартными.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# =========================================
# ЧТЕНИЕ .env
# =========================================
# launchd передаёт процессу только PATH, поэтому ключи из окружения
# оболочки до сервера не доходят. Читаем .env из корня проекта сами —
# без python-dotenv, чтобы не тянуть зависимость.
# Уже заданные переменные окружения имеют приоритет: так на сервере
# можно переопределить значение, не трогая файл.
def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:
        # проблема с .env не должна ронять запуск сервера
        pass


_load_dotenv(BASE_DIR / ".env")


# Отдельная БД для мониторинга. Если хочешь писать в ту же factory.db,
# что и основной ACAI — просто замени путь на путь к factory.db.
DB_PATH = os.environ.get("ACAI_MONITORING_DB", str(BASE_DIR / "monitoring.db"))
DATABASE_URL = f"sqlite:///{DB_PATH}"

# Секрет для JWT. В проде — вынести в переменную окружения обязательно.
SECRET_KEY = os.environ.get("ACAI_SECRET_KEY", "change-me-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 12  # 12 часов — рабочая смена с запасом

# Роли пользователей системы
ROLE_DIRECTOR = "director"      # видит всё, может увольнять/назначать
ROLE_ADMIN = "admin"            # технический доступ, настройка
ROLE_TECHNICIAN = "technician"  # обслуживает оборудование, закрывает инциденты
ROLE_WORKER = "worker"          # заводит инциденты по своей зоне

ALL_ROLES = [ROLE_DIRECTOR, ROLE_ADMIN, ROLE_TECHNICIAN, ROLE_WORKER]

# Статусы оборудования
EQUIPMENT_STATUSES = ["working", "needs_repair", "stopped", "maintenance"]

# Статусы инцидентов
INCIDENT_STATUSES = ["open", "in_progress", "resolved"]
INCIDENT_SEVERITIES = ["low", "medium", "high", "critical"]

# =========================================
# ПЕРЕМЕННЫЕ ОСНОВНОГО ACAI (добавлены)
# =========================================
import os as _os

DB_NAME = str(BASE_DIR / "factory.db")

ENVIRONMENT = _os.getenv("ENVIRONMENT", "development")

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in _os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://192.168.1.74").split(",")
    if origin.strip()
]

MAX_AI_STEPS = int(_os.getenv("MAX_AI_STEPS", "3"))

# =========================================
# ПУТИ К ДОКУМЕНТАЦИИ И ФАЙЛАМ ACAI
# =========================================
DOCS_PATH          = BASE_DIR / "docs"
DOCS_MACHINES_PATH = DOCS_PATH / "Machines"
SYMPTOMS_DIR       = BASE_DIR / "backend" / "core" / "symptoms"
CHROMA_DB_PATH     = BASE_DIR / "knowledge_base" / "chroma_db"
# Модель поиска по документации и коллекция, в которой он ищет.
# Прежняя all-MiniLM-L6-v2 обучена на английском, а документация русская:
# она путала «залипание влажным сырьём» и «налипание массы на вал».
# Меняются через .env, старую коллекцию это не трогает — откат возможен.
EMBED_MODEL_NAME = _os.getenv("ACAI_EMBED_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
CHROMA_COLLECTION_NAME = _os.getenv("ACAI_COLLECTION", "factory_manuals_ml")
KNOWLEDGE_BASE_PATH = BASE_DIR / "knowledge_base"

# =========================================
# OPENAI
# =========================================
import os as _os2
OPENAI_API_KEY = _os2.getenv("OPENAI_API_KEY")

# =========================================
# ЗАЩИТА / ВЛАДЕЛЬЦЫ
# =========================================
OWNERS = [
    name.strip()
    for name in _os2.getenv("OWNERS", "alibek").split(",")
    if name.strip()
]

def is_owner(user) -> bool:
    if not user:
        return False
    return user.get("username") in OWNERS

# =========================================
# AI / СЕССИИ
# =========================================
ACTIVE_CASE_WINDOW_HOURS = int(_os2.getenv("ACTIVE_CASE_WINDOW_HOURS", "12"))

# =========================================
# MACHINE DOCS MAP
# =========================================
MACHINE_DOCS_MAP = {
    # Собрано map_machine_docs.py по номерам моделей.
    # В базе «Дезинтегратор PL 601», в папке «2.ДЕЗИНТИГРАТОР PL601-08» —
    # слова расходятся, номер совпадает. Правьте руками, если что-то не так.
    "вальцы супертонкого помола optima 800": ["OPTIMA 800 H", "8.ПИТАТЕЛЬ ЛЕНТОЧНЫЙ  PL05-2 над OPTIMA 800 H  ПАСПОРТ", "ПАСПОРТ ШКАФ OPTIMА 800 H"],
    "вальцы усм 40": ["Вальцы УСМ 40"],
    "вентилятор нагнетания qb-44": ["Центробежный вентилятор QB-44 (дымосос печи)", "Вентилятор нагнетания QB-44"],
    "вентилятор нагнетания qb-54": ["Центробежный вентилятор QB-54 (охлаждение печи)", "Вентилятор нагнетания QB-54"],
    "вентиляторы рециркуляции зона 3 gat-63 (16 шт)": ["Вентиляторы рециркуляции зона 3 GAT-63 (16 шт)"],
    "вентиляторы рециркуляции зоны 1-2 gat-80 (32 шт)": ["Вентиляторы рециркуляции зоны 1-2 GAT-80 (32 шт)"],
    "вытяжные вентиляторы gat-125 (2 шт)": ["Вытяжные вентиляторы GAT-125 (2 шт)"],
    "генератор тепла 1500 csd + теплообменник gb/1500": ["26.Трансформатор тока Т-0,66 1500.5А Паспорт"],
    "дезинтегратор pl 601": ["ЭЛЕКТРООБОРУДОВАНИЕ ДИЗЕНТЕГРАТОРНЫЕ PL601-08 РЭ", "2.ДЕЗИНТИГРАТОР PL601-08"],
    "дробилка dte 117": ["Дробилка DTE 117", "Дробилка DTE 117", "1.ДРОБИЛКА DTE 117"],
    "осевой вентилятор gat-80 (герметизация ямы)": ["Вентиляторы рециркуляции зоны 1-2 GAT-80 (32 шт)"],
    "система быстрого охлаждения gerim 200/2/14": ["Система быстрого охлаждения GERIM 200:2:14", "20.ТОЛ-10-I-2 У2 200.5А Паспорт"],
    "смеситель лопастной смк 126": ["Смеситель лопастной СМК 126"],
    "центробежный вентилятор qb-40 (контравек)": ["Центробежный вентилятор QB-40 (контравек)"],
    "центробежный вентилятор qb-44 (дымосос печи)": ["Центробежный вентилятор QB-44 (дымосос печи)", "Вентилятор нагнетания QB-44"],
    "центробежный вентилятор qb-54 (охлаждение печи)": ["Центробежный вентилятор QB-54 (охлаждение печи)", "Вентилятор нагнетания QB-54"],
    "экструдер шнековый magna 575": ["МАГНЫ 575 РЭ"],
}

def resolve_machine_key(machine):
    if not machine:
        return None
    value = str(machine).strip().lower()
    if value in MACHINE_DOCS_MAP:
        m = MACHINE_DOCS_MAP[value]
        return m[0] if isinstance(m, list) else m
    for keyword, mapped in MACHINE_DOCS_MAP.items():
        if keyword in value:
            return mapped[0] if isinstance(mapped, list) else mapped
    return None
MONITORING_SECRET_KEY = SECRET_KEY
