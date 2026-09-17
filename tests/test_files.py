"""
Файлы: загрузка, выдача, удаление — и попытки добраться до чужого.

  1. Переписка: фото (EXIF с координатами срезается), голосовое, документ;
     получатель скачивает, посторонний и не вошедший — нет; HTML и SVG
     отдаются на скачивание, а не открываются на сайте; имя «../../» не
     выводит из папки; удалённое сообщение стирает файл; 50 МБ — предел;
     удаление группы стирает все её файлы.
  2. Фото обходов: не-картинка не принимается, EXIF срезается, дубль не
     пишется второй раз, чужое неотправленное фото не удалить.
  3. Документы станков: загружает только главный специалист, запрещённые
     расширения не принимаются, скачивание только со входом, «../» и
     соседняя папка «docs_*» недоступны.
  4. Бэкапы: делает только владелец, копия проходит проверку целостности,
     восстановить «../factory.db» нельзя.

Всё — в песочнице (tests/sandbox.py): копия базы и временная папка для
файлов. После прогона проверяется, что в живых папках не появилось ни
одного файла.

Запуск из корня проекта: python tests/test_files.py
"""

import io
import os
import sqlite3
import time
from pathlib import Path

from sandbox import Sandbox, check, finish, ROOT

# Что лежит в живых папках до прогона — чтобы убедиться, что ничего не добавилось
LIVE_DIRS = [ROOT / "uploads" / "messenger", ROOT / "data" / "checklist_photos",
             ROOT / "docs", ROOT / "backups", ROOT / "frontend" / "static" / "uploads"]


def snapshot(dirs):
    files = set()
    for d in dirs:
        if d.exists():
            files.update(str(p) for p in d.rglob("*") if p.is_file())
    return files


live_before = snapshot(LIVE_DIRS)

sb = Sandbox()
FILES = Path(sb.files_root)

from PIL import Image


def jpeg_with_gps(color=(200, 30, 30)):
    """Снимок с EXIF: модель телефона и координаты — то, что утекать не должно."""
    img = Image.new("RGB", (900, 600), color)
    exif = Image.Exif()
    exif[0x0110] = "Секретный телефон"          # Model
    exif[0x8825] = {1: "N", 2: (51.0, 10.0, 0.0), 3: "E", 4: (71.0, 26.0, 0.0)}   # GPS
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def has_exif(data: bytes) -> bool:
    with Image.open(io.BytesIO(data)) as img:
        exif = img.getexif()
        return bool(exif.get(0x0110) or exif.get(0x8825))


check("в тестовом снимке EXIF действительно есть", has_exif(jpeg_with_gps()))


# ─────────────────────────────────────────────────────────
print("\n1. Вложения переписки")

alice = sb.user("mechanic")
bob = sb.user("electrician")
stranger = sb.user("mechanic")

dm = alice.post("/api/messenger/conversations/dm", json={"user_id": bob.id}).json()["conversation_id"]


def upload(client, conv, name, data, mime, caption=""):
    return client.post(
        f"/api/messenger/conversations/{conv}/attachments",
        files={"file": (name, data, mime)}, data={"caption": caption},
    )


def stored_path(message_id):
    row = sb.db().execute("SELECT stored_path, preview_path FROM team_attachments WHERE message_id = ?", (message_id,)).fetchone()
    return (FILES / "uploads" / "messenger" / row["stored_path"],
            FILES / "uploads" / "messenger" / row["preview_path"] if row["preview_path"] else None)


r = upload(alice, dm, "шильдик.jpg", jpeg_with_gps(), "image/jpeg", "фото шильдика")
photo = r.json().get("message", {}) if r.status_code == 200 else {}
att = photo.get("attachment") or {}
check("фото загружено", r.status_code == 200 and att.get("kind") == "image", r.text[:200])
original, preview = stored_path(photo["id"])
check("файл лёг в папку песочницы", original.exists() and str(FILES) in str(original))

r = bob.get(att["url"])
check("получатель открывает фото", r.status_code == 200 and "attachment" not in r.headers.get("content-disposition", ""))
r = bob.get(att["preview_url"])
check("превью для ленты без EXIF (координаты и модель телефона срезаны)", r.status_code == 200 and not has_exif(r.content))

check("посторонний не скачает фото", stranger.get(att["url"]).status_code == 403)
check("без входа не скачать", sb.anonymous().get(att["url"]).status_code == 401)

r = upload(alice, dm, "голос.webm", b"\x1aE\xdf\xa3" + os.urandom(4000), "audio/webm")
voice = (r.json().get("message") or {}).get("attachment") or {}
check("голосовое — проигрыватель", r.status_code == 200 and voice.get("kind") == "audio", r.text[:200])

for name, mime, body in (
    ("страница.html", "text/html", b"<script>alert(document.cookie)</script>"),
    ("рисунок.svg", "image/svg+xml", b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"),
):
    r = upload(alice, dm, name, body, mime)
    a = (r.json().get("message") or {}).get("attachment") or {}
    got = bob.get(a.get("url", "/x"))
    check(f"{name}: отдаётся на скачивание, не исполняется на сайте",
          got.status_code == 200 and "attachment" in got.headers.get("content-disposition", ""),
          (r.status_code, got.headers.get("content-disposition")))

r = upload(alice, dm, "../../factory.db", b"not a database", "application/octet-stream")
evil = r.json().get("message") or {}
evil_path, _ = stored_path(evil["id"]) if evil else (None, None)
check("имя «../../factory.db» не выводит из папки вложений",
      r.status_code == 200 and evil_path and evil_path.resolve().is_relative_to((FILES / "uploads" / "messenger").resolve())
      and evil_path.name != "factory.db", evil_path)

big = b"0" * (50 * 1024 * 1024 + 1)
r = upload(alice, dm, "большой.bin", big, "application/octet-stream")
check("файл больше 50 МБ не принимается", r.status_code == 413, r.status_code)
del big

r = alice.delete(f"/api/messenger/messages/{photo['id']}")
check("удаление сообщения стирает файл и превью",
      r.status_code == 200 and not original.exists() and (preview is None or not preview.exists()))
check("удалённое фото больше не скачать", bob.get(att["url"]).status_code in (400, 404))

group = alice.post("/api/messenger/conversations/group", json={"title": "Проверка файлов", "member_ids": [bob.id]}).json()["conversation_id"]
paths = []
for i in range(2):
    m = upload(bob, group, f"акт{i}.pdf", b"%PDF-1.4 test " + os.urandom(100), "application/pdf").json()["message"]
    paths.append(stored_path(m["id"])[0])
check("файлы группы на диске", all(p.exists() for p in paths))
r = alice.delete(f"/api/messenger/conversations/{group}")
check("удаление группы для всех стирает её файлы", r.status_code == 200 and not any(p.exists() for p in paths), r.text[:150])


# ─────────────────────────────────────────────────────────
print("\n2. Фото обходов смены")

master = sb.user("shift_supervisor")
other_master = sb.user("shift_supervisor")

r = master.post("/api/checklist/photo", files={"file": ("x.jpg", b"<?php echo 1; ?>", "image/jpeg")}, data={"equipment_id": sb.equipment_id})
check("не-картинка под видом .jpg не принимается", r.status_code == 415, r.status_code)

shot = jpeg_with_gps((30, 120, 200))
r = master.post("/api/checklist/photo", files={"file": ("обход.jpg", shot, "image/jpeg")}, data={"equipment_id": sb.equipment_id})
photo_id = r.json().get("id")
check("фото обхода загружено", r.status_code == 200 and photo_id, r.text[:150])
rel = sb.db().execute("SELECT rel_path FROM checklist_photos WHERE id = ?", (photo_id,)).fetchone()["rel_path"]
photo_file = FILES / "data" / "checklist_photos" / rel
check("фото лежит в папке песочницы", photo_file.exists())

got = master.get(f"/api/checklist/photo/{photo_id}")
check("фото обхода без EXIF", got.status_code == 200 and not has_exif(got.content))
check("без входа фото обхода не открыть", sb.anonymous().get(f"/api/checklist/photo/{photo_id}").status_code == 401)

r = master.post("/api/checklist/photo", files={"file": ("снова.jpg", shot, "image/jpeg")}, data={"equipment_id": sb.equipment_id})
check("тот же снимок второй раз не пишется", r.status_code == 200 and r.json().get("duplicate") is True, r.text[:150])

check("чужое неотправленное фото не удалить", other_master.delete(f"/api/checklist/photo/{photo_id}").status_code == 403)
r = master.delete(f"/api/checklist/photo/{photo_id}")
check("своё фото удаляется вместе с файлом", r.status_code == 200 and not photo_file.exists())


# ─────────────────────────────────────────────────────────
print("\n3. Документы станков")

import base64

chief = sb.user("chief_engineer")
mechanic = sb.user("mechanic")
pdf = b"%PDF-1.4\n% ACAI test\n" + os.urandom(500)
b64 = base64.b64encode(pdf).decode()


def upload_doc(client, filename, data=b64):
    return client.post(f"/api/equipment/{sb.equipment_id}/documents/upload",
                       json={"filename": filename, "content": data, "title": filename})


r = upload_doc(mechanic, "паспорт.pdf")
check("механик документы станка не загружает", r.status_code == 403, r.status_code)

r = upload_doc(chief, "паспорт.pdf")
doc = r.json() if r.status_code == 200 else {}
row = sb.db().execute("SELECT file_path FROM equipment_documents WHERE id = ?", (doc.get("id"),)).fetchone()
check("главный инженер загрузил паспорт, он в карточке станка", r.status_code == 200 and row, r.text[:200])
doc_path = FILES / "docs" / row["file_path"] if row else None
check("документ лёг в папку песочницы", doc_path and doc_path.exists())
check("русское имя файла сохранилось", doc_path and doc_path.name == "паспорт.pdf", doc_path and doc_path.name)

r = upload_doc(chief, "паспорт.pdf")
row2 = sb.db().execute("SELECT file_path FROM equipment_documents WHERE id = ?", (r.json().get("id"),)).fetchone()
check("вторая ревизия с тем же именем не затирает первую",
      r.status_code == 200 and row2 and row2["file_path"] != row["file_path"] and doc_path.read_bytes() == pdf)

r = upload_doc(chief, "вирус.exe", base64.b64encode(b"MZ" + os.urandom(100)).decode())
check("исполняемый файл не принимается", r.status_code == 400, r.status_code)
check("и не остался на диске", not any(p.suffix == ".exe" for p in (FILES / "docs").rglob("*")))

r = upload_doc(chief, "../../backend/api/main.pdf")
row3 = sb.db().execute("SELECT file_path FROM equipment_documents WHERE id = ?", (r.json().get("id"),)).fetchone() if r.status_code == 200 else None
check("имя «../../» не выводит из папки документов",
      row3 is None or (FILES / "docs" / row3["file_path"]).resolve().is_relative_to((FILES / "docs").resolve()),
      row3 and row3["file_path"])

r = upload_doc(chief, "битый.pdf", "это не base64 !!!")
check("повреждённый файл не принимается", r.status_code == 400, r.status_code)

r = chief.post(f"/api/equipment/{sb.equipment_id}/documents/upload", content=b"\xff\xd8\xff" + os.urandom(300),
               headers={"Content-Type": "application/octet-stream"})
check("двоичный мусор вместо запроса — 422, а не падение сервера", r.status_code == 422, r.status_code)

r = sb.anonymous().post("/auth/login", json={"username": "x"})
check("ответ об ошибке формата не возвращает присланное", r.status_code == 422 and '"input"' not in r.text, r.text[:150])

equipment_name = sb.db().execute("SELECT name FROM equipment WHERE id = ?", (sb.equipment_id,)).fetchone()["name"]
safe = equipment_name.replace("/", "-")
r = chief.post(f"/api/equipment/{sb.equipment_id}/documents/upload-b64", json={"filename": "схема.pdf", "data": b64})
check("загрузка со страницы «Оборудование» работает",
      r.status_code == 200 and r.json().get("success") and (FILES / "docs" / safe / "схема.pdf").exists(), r.text[:200])
r = chief.post(f"/api/equipment/{sb.equipment_id}/documents/upload-b64",
               json={"filename": "../../backend/api/main.py", "data": base64.b64encode("print('взлом')".encode()).decode()})
check("через эту загрузку не записать .py", r.status_code == 415 or not r.json().get("success"), r.text[:150])
check("код сайта не тронут", "взлом" not in (ROOT / "backend" / "api" / "main.py").read_text())

from urllib.parse import quote
url = "/docs-files/" + quote(row["file_path"])
check("со входом документ скачивается", mechanic.get(url).status_code == 200)
check("без входа документ не скачать", sb.anonymous().get(url).status_code == 401)

secret = FILES / "docs_old" / "секрет.txt"
secret.parent.mkdir(parents=True, exist_ok=True)
secret.write_text("не для всех")
(FILES / "outside.txt").write_text("за пределами docs")
# «../» в адресе клиент схлопывает сам, до сервера доходит только закодированное —
# им и пользуется тот, кто пробует выйти из папки. Ждём именно отказ 403:
# 404 значило бы, что запрос вообще не дошёл до проверки.
secret_quoted = quote("секрет.txt")
for bad in ("..%2Foutside.txt", "%2e%2e/outside.txt", f"..%2Fdocs_old%2F{secret_quoted}",
            f"%2e%2e/docs_old/{secret_quoted}", "%2e%2e/%2e%2e/factory.db"):
    resp = mechanic.get("/docs-files/" + bad)
    check(f"путь «{bad}» не выводит из docs", resp.status_code == 403 and "не для всех" not in resp.text,
          (resp.status_code, resp.text[:80]))


# ─────────────────────────────────────────────────────────
print("\n4. Бэкапы")

owner = sb.user("admin", username="t-owner")
admin = sb.user("admin")

check("не-владелец бэкап не делает", admin.post("/api/backups/create").status_code == 403)
r = owner.post("/api/backups/create")
name = r.json().get("file") if r.status_code == 200 else None
check("владелец сделал бэкап", r.status_code == 200 and name, r.text[:200])
backup = FILES / "backups" / (name or "-")
check("копия в папке песочницы", backup.exists())
if backup.exists():
    ok = sqlite3.connect(backup).execute("PRAGMA integrity_check").fetchone()[0]
    check("копия базы целая", ok == "ok", ok)

for bad in ("../factory.db", "/etc/passwd", "..\\factory.db"):
    resp = owner.post("/api/backups/restore", json={"filename": bad})
    check(f"восстановить из «{bad}» нельзя", resp.status_code in (400, 403, 404), resp.status_code)


# ─────────────────────────────────────────────────────────
print("\nЖивые папки")
added = snapshot(LIVE_DIRS) - live_before
check("в живых папках не появилось ни одного файла", not added, sorted(added)[:5])

finish("Файлы")
