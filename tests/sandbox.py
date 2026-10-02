"""
Песочница для сквозных проверок: сайт целиком, но на копии базы.

Сквозной сценарий честно создаёт обращения, простои, записи журнала.
В живой базе это испортило бы статистику и «Использование», поэтому:

  - factory.db и monitoring.db копируются во временную папку
    (переменные ACAI_DB, ACAI_MONITORING_DB);
  - сайт запускается прямо в процессе проверки (TestClient), настоящий
    сервер на 8000/8443 не нужен и не трогается;
  - OpenAI выключен: ответы ИИ не должны зависеть от сети и стоить денег.
    Путь по коду ошибки PLC ИИ не требует;
  - фоновые потоки (запись датчиков, проверки для уведомлений) не
    стартуют, push никуда не уходит;
  - файлы (вложения, фото обходов, документы, бэкапы, база знаний) —
    во временной папке (ACAI_FILES_ROOT), живые файлы не трогаются;
  - сотрудники для проверок создаются в копии заново, у каждого свой
    пароль — от боевых учёток ничего не зависит.

Импортировать ДО любого импорта backend: переменные окружения читаются
при загрузке config.

    from sandbox import Sandbox
    sb = Sandbox()
    worker = sb.user("worker", equipment=[sb.equipment_id])
    worker.post("/diagnose", json={...})
"""

import atexit
import os
import secrets
import shutil
import sqlite3
import sys
import tempfile
import pathlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="acai_sandbox_"))
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))


def _copy_db(src: Path, dst: Path):
    if not src.exists():
        return
    # через backup API: копия согласованная, даже если сервер сейчас пишет
    source = sqlite3.connect(src)
    target = sqlite3.connect(dst)
    source.backup(target)
    source.close()
    target.close()


# Откуда брать копию. По умолчанию — база рядом с проектом. Для
# разбора боевых случаев можно указать свежую копию боевой базы:
#     ACAI_SANDBOX_SOURCE=/путь/к/папке python3 проверка.py
# Пишется всё равно во временную папку: боевой файл только читается.
_SOURCE = pathlib.Path(os.environ.get("ACAI_SANDBOX_SOURCE") or ROOT)

_copy_db(_SOURCE / "factory.db", _TMP / "factory.db")
_copy_db(_SOURCE / "monitoring.db", _TMP / "monitoring.db")

# Свои папки для файлов: загрузки, удаления и бэкапы в проверках не
# должны касаться живых вложений, фото обходов, документов и копий базы.
# База знаний здесь пустая — сквозные сценарии идут по кодам ошибок PLC.
_FILES = _TMP / "files"
for sub in ("docs", "uploads/messenger", "data/checklist_photos", "backups",
            "frontend/static/uploads", "knowledge_base"):
    (_FILES / sub).mkdir(parents=True, exist_ok=True)
os.environ["ACAI_FILES_ROOT"] = str(_FILES)

os.environ["ACAI_DB"] = str(_TMP / "factory.db")
os.environ["ACAI_MONITORING_DB"] = str(_TMP / "monitoring.db")
# На боевом сервере ENVIRONMENT=production, и куку входа сервер ставит
# с флагом secure — по http её браузер (и TestClient) не сохраняет.
# Проверки из-за этого на сервере не работали вовсе: вход проходил, а
# следующий запрос получал «Не авторизован». Песочница ходит по http к
# самой себе, поэтому здесь всегда development.
os.environ["ENVIRONMENT"] = "development"
os.environ["OPENAI_API_KEY"] = ""            # client = None
os.environ["ACAI_LIVE_PROXY"] = "http://127.0.0.1:9"   # фоновые потоки не стартуют
os.environ["ACAI_WEBHMI_COLLECTOR"] = "0"
# владелец системы в песочнице — проверочная учётка, а не настоящий alibek
os.environ["OWNERS"] = "t-owner"
os.chdir(ROOT)   # шаблоны и статика ищутся относительно корня


class Client:
    """Сотрудник, вошедший на сайт: запросы идут с его сессией."""

    def __init__(self, sandbox, row, password):
        from fastapi.testclient import TestClient
        self.sb = sandbox
        self.id = row["id"]
        self.username = row["username"]
        self.full_name = row["full_name"]
        self.role = row["role"]
        self.password = password
        self.http = TestClient(sandbox.app, follow_redirects=False)

    def login(self):
        r = self.http.post("/auth/login", json={"username": self.username, "password": self.password})
        return r

    def get(self, path, **kw):
        return self.http.get(path, **kw)

    def post(self, path, **kw):
        return self.http.post(path, **kw)

    def put(self, path, **kw):
        return self.http.put(path, **kw)

    def patch(self, path, **kw):
        return self.http.patch(path, **kw)

    def delete(self, path, **kw):
        return self.http.delete(path, **kw)


class Sandbox:

    def __init__(self):
        # сам сайт — только после подмены окружения
        import backend.services.push_service as push_service
        push_service.enabled = lambda: False   # уведомления не отправлять

        from backend.api.main import app
        from backend.config import DB_NAME, FILES_ROOT
        assert str(_TMP) in DB_NAME, "песочница должна работать на копии базы"
        assert str(_TMP) in str(FILES_ROOT), "песочница должна писать файлы во временную папку"
        self.files_root = FILES_ROOT

        self.app = app
        self.db_path = DB_NAME
        self._n = 0

        # станок для поломки — без открытых обращений: иначе новая жалоба
        # допишется в чужое настоящее обращение из копии базы
        eq = self.db().execute(
            """
            SELECT id, name FROM equipment e
            WHERE COALESCE(is_active, 1) = 1
              AND NOT EXISTS (SELECT 1 FROM cases c WHERE c.equipment_id = e.id AND c.status != 'Закрыто')
            ORDER BY id LIMIT 2
            """
        ).fetchall()
        self.equipment_id, self.equipment_name = eq[0]["id"], eq[0]["name"]
        self.other_equipment_id = eq[1]["id"]

        # Отсечка журнала. Копия боевой базы приходит не пустой: смены
        # на заводе открывают каждый день, нормы правят, станки заводят.
        # Проверка, которая считает строки «по всей таблице», зелёная
        # только на чистой базе разработчика — на боевой копии она
        # падает от чужой работы. Трижды за две недели ловили это
        # руками (сменный отчёт, регламенты, нормы технолога), поэтому
        # запоминаем номер последней строки ДО проверок, а смотрим
        # только на то, что появилось после.
        self.journal_base = self.db().execute(
            "SELECT COALESCE(MAX(id), 0) FROM audit_log"
        ).fetchone()[0]

    def db(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def journal(self, action=None, newest_first=True):
        """
        Записи журнала, появившиеся ПОСЛЕ старта песочницы.

        Это и есть «что сделала проверка»: чужие строки из копии боевой
        базы сюда не попадают. Отбирать по имени автора нельзя — часть
        записей подписана логином, часть полным именем человека.

            sb.journal("shift_report_opened")   # свои строки по действию
            sb.journal()                        # всё, что натворила проверка
        """
        where = "id > ?"
        args = [self.journal_base]

        if action is not None:
            where += " AND action = ?"
            args.append(action)

        order = "DESC" if newest_first else "ASC"

        conn = self.db()
        rows = conn.execute(
            f"SELECT * FROM audit_log WHERE {where} ORDER BY id {order}", args
        ).fetchall()
        conn.close()
        return rows

    def user(self, role, equipment=None, login=True, active=True, brigade=None, username=None):
        from backend.services.auth_service import create_user, assign_equipment, get_user_by_username

        self._n += 1
        username = username or f"t-{role.replace('_', '-')}-{self._n}"
        password = "Test" + secrets.token_hex(6) + "9x"
        create_user(username, password, f"Проверка {role} {self._n}", role)
        row = get_user_by_username(username)

        if equipment:
            assign_equipment(row["id"], list(equipment))
        if brigade:
            conn = self.db()
            conn.execute("UPDATE users SET brigade = ? WHERE id = ?", (brigade, row["id"]))
            conn.commit()
            conn.close()

        client = Client(self, row, password)
        if login:
            r = client.login()
            assert r.status_code == 200 and r.json().get("success"), f"вход {username}: {r.status_code} {r.text[:200]}"
        if not active:
            conn = self.db()
            conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (row["id"],))
            conn.commit()
            conn.close()
        return client

    def anonymous(self):
        from fastapi.testclient import TestClient
        return TestClient(self.app, follow_redirects=False)


# ── отчёт в стиле остальных tests/ ─────────────────────────

passed, failed = [], []


def check(name, condition, detail=""):
    if condition:
        passed.append(name)
        print(f"  OK   {name}")
    else:
        failed.append(f"{name}: {detail}")
        print(f"  СБОЙ {name}  {str(detail)[:300]}")


def finish(title):
    print(f"\n{title}: проверок {len(passed) + len(failed)}, сбоев {len(failed)}")
    for item in failed:
        print("  -", item[:400])
    sys.exit(1 if failed else 0)
