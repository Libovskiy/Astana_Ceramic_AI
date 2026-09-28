"""
Учение по восстановлению: настоящая ночная копия разворачивается целиком.

Бэкап, из которого ни разу не восстанавливались, — это надежда, а не
бэкап. Здесь по шагам то, что придётся делать в плохой день:

  1. Берём ПОСЛЕДНЮЮ НАСТОЯЩУЮ ночную копию из backups/ (только читаем,
     кладём её копию в песочницу).
  2. «Плохой день»: после копии в базе появились данные, которые надо
     откатить (новый сотрудник, обращение).
  3. Владелец восстанавливает копию через сайт.
  4. Проверяем: база совпадает с копией по каждой таблице; то, что
     появилось после копии, пропало; перед восстановлением сама собой
     сделалась страховочная копия, и в ней эти данные есть — откат можно
     откатить; сайт работает без перезапуска; всех разлогинило (сессии
     тоже из копии) — после входа всё открывается.
  5. Архивы фото и вложений из той же ночи распаковываются.

Всё в песочнице (tests/sandbox.py): живая база и живые файлы не меняются.
Запуск из корня проекта: python tests/test_restore.py
"""

import shutil
import sqlite3
import tarfile
import tempfile
from pathlib import Path

from sandbox import Sandbox, check, finish, ROOT

# Берём последнюю НОЧНУЮ копию, и непременно полную — ту, рядом с
# которой лежит история датчиков.
#
# Здесь были две ошибки сразу. Во-первых, копии сортировались по имени,
# а ручные называются словами: «factory_before_reimport_...» по алфавиту
# оказывается позже, чем «factory_20260928_...». Учение полгода
# разворачивало копию недельной давности, думая, что берёт свежую.
# Во-вторых, ручная копия бывает без пары monitoring.db, и тогда учение
# падало не по делу.
#
# Ночная копия называется строго датой: factory_ГГГГММДД_ЧЧММСС.db —
# по ней и отбираем, а время берём из имени, а не из файловой системы:
# файл могли скопировать позже, чем он сделан.
import re

NIGHTLY = re.compile(r"^factory_(\d{8}_\d{6})\.db$")


def _stamp(path):
    return path.stem.replace("factory_", "")


def _pair(path):
    return (ROOT / "backups" / f"monitoring_{_stamp(path)}.db").exists()


all_copies = list((ROOT / "backups").glob("factory_*.db"))
nightly = sorted((p for p in all_copies if NIGHTLY.match(p.name) and _pair(p)),
                 key=lambda p: NIGHTLY.match(p.name).group(1))

if not nightly:
    # Ночных нет — разворачиваем хотя бы последнюю полную ручную, но
    # говорим об этом прямо: это другое учение.
    manual = sorted((p for p in all_copies if _pair(p)), key=lambda p: p.stat().st_mtime)
    if not manual:
        print("  Полных копий нет — учение провести не на чем.")
        check("есть копия базы с историей датчиков рядом", False,
              f"копий базы {len(all_copies)}, но ни к одной нет monitoring_*.db")
        finish("Восстановление из бэкапа")
    print("  Ночной копии нет — учение идёт на ручной.")
    nightly = manual

source = nightly[-1]
print(f"\nКопия: {source.name}")

sb = Sandbox()
FILES = Path(sb.files_root)
backup_name = source.name
shutil.copy2(source, FILES / "backups" / backup_name)


def table_counts(path):
    conn = sqlite3.connect(path)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    counts = {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    conn.close()
    return counts


integrity = sqlite3.connect(FILES / "backups" / backup_name).execute("PRAGMA integrity_check").fetchone()[0]
check("ночная копия целая", integrity == "ok", integrity)
expected = table_counts(FILES / "backups" / backup_name)
check("в копии есть сотрудники и оборудование", expected.get("users", 0) > 0 and expected.get("equipment", 0) > 0,
      (expected.get("users"), expected.get("equipment")))


print("\n«Плохой день»: данные, которых нет в копии")
owner = sb.user("admin", username="t-owner")
intruder = sb.user("mechanic", username="t-after-backup")
worker = sb.user("worker", equipment=[sb.equipment_id])
r = worker.post("/diagnose", json={"equipment_id": sb.equipment_id, "question": "ошибка A1"})
case_after = r.json().get("case_id")
check("после копии появились сотрудники и обращение", case_after is not None)


print("\nВосстановление")
r = owner.post("/api/backups/restore", json={"filename": backup_name})
result = r.json() if r.status_code == 200 else {}
check("владелец восстановил копию через сайт", r.status_code == 200 and result.get("success"), r.text[:200])

actual = table_counts(sb.db_path)
diff = {t: (expected.get(t), actual.get(t)) for t in set(expected) | set(actual)
        if expected.get(t) != actual.get(t) and t in expected and t != "audit_log"}
check("база совпадает с копией по всем таблицам", not diff, diff)
last_action = sb.db().execute("SELECT action FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()[0]
check("в журнале — копия плюс одна запись о самом восстановлении",
      actual.get("audit_log") == expected.get("audit_log", 0) + 1 and last_action == "backup_restored",
      (expected.get("audit_log"), actual.get("audit_log"), last_action))
check("сотрудник, заведённый после копии, пропал",
      sb.db().execute("SELECT COUNT(*) FROM users WHERE username = 't-after-backup'").fetchone()[0] == 0)
check("обращение, созданное после копии, пропало",
      sb.db().execute("SELECT COUNT(*) FROM cases WHERE id = ?", (case_after,)).fetchone()[0] == 0)

pre = FILES / "backups" / (result.get("pre_restore_backup") or "-")
check("перед восстановлением сама сделалась страховочная копия", pre.exists(), pre.name)
if pre.exists():
    kept = sqlite3.connect(pre).execute("SELECT COUNT(*) FROM users WHERE username = 't-after-backup'").fetchone()[0]
    check("в страховочной копии данные «плохого дня» есть — откат можно откатить", kept == 1)


print("\nСайт после восстановления, без перезапуска")
check("открытые сессии больше не действуют (все входят заново)", owner.get("/auth/me").status_code == 401)

# сотрудник, который был в копии, входит заново
from backend.services.auth_service import set_password
existing = sb.db().execute(
    "SELECT id, username FROM users WHERE role = 'chief_engineer' AND COALESCE(is_active, 1) = 1 LIMIT 1"
).fetchone()
set_password(existing["id"], "Restore-check-2026")   # пароль — только в песочнице
anon = sb.anonymous()
r = anon.post("/auth/login", json={"username": existing["username"], "password": "Restore-check-2026"})
check("сотрудник из копии входит", r.status_code == 200 and r.json().get("success"), r.text[:150])
for path in ("/api/equipment", "/api/conversation", "/api/notifications", "/api/reports/summary"):
    resp = anon.get(path)
    check(f"после восстановления работает {path}", resp.status_code == 200, resp.status_code)
check("главная страница открывается", anon.get("/").status_code == 200)


print("\nАрхивы файлов той же ночи")
stamp = source.stem.replace("factory_", "")
for label in ("photos", "chatfiles", "certs"):
    archive = ROOT / "backups" / f"{label}_{stamp}.tar.gz"
    if not archive.exists():
        print(f"  —    {label}: архива за эту ночь нет (папка была пустой или ещё не входила в бэкап)")
        continue
    target = Path(tempfile.mkdtemp(prefix="acai_restore_"))
    try:
        with tarfile.open(archive) as tar:
            tar.extractall(target, filter="data")
        files = [p for p in target.rglob("*") if p.is_file()]
        # вложений в переписке может ещё не быть — важно, что архив читается
        check(f"{label}: архив распаковывается ({len(files)} файлов)", target.exists())
    finally:
        shutil.rmtree(target, ignore_errors=True)

monitoring = ROOT / "backups" / f"monitoring_{stamp}.db"
check("история датчиков (monitoring.db) есть в той же ночной копии", monitoring.exists(), monitoring.name)
if monitoring.exists():
    # её восстанавливают заменой файла при остановленном сервере — проверяем, что копия годится
    probe = Path(tempfile.mkdtemp(prefix="acai_restore_")) / "monitoring.db"
    shutil.copy2(monitoring, probe)
    conn = sqlite3.connect(probe)
    ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
    readings = conn.execute("SELECT COUNT(*) FROM sensor_readings").fetchone()[0]
    conn.close()
    shutil.rmtree(probe.parent, ignore_errors=True)
    check(f"копия истории датчиков целая и читается ({readings} показаний)", ok == "ok" and readings > 0, ok)

finish("Восстановление из бэкапа")
