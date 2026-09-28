"""
Документы станка и фото обходов: удаление оставляет след.

Зачем. Аудит изменяющих ручек показал, что один и тот же документ
попадал в журнал или не попадал в зависимости от того, с какой
страницы его принесли: через «Структуру» запись была, через карточку
станка — нет. А удаление документа из карточки не писалось никуда и
отвечало «успешно» даже тогда, когда удалять было нечего.

Фото обхода — свидетельство состояния станка на такой-то час, и вместе
с записью может уйти файл с диска. Загрузку в журнал не пишем: их
десятки за обход, и в самой записи видно, кто и когда снял. Удаление —
пишем всегда. Привязку фото к обращению тоже: привязали не туда — в
карточке чужой поломки окажутся чужие снимки.

Базы и файлы временные, боевые не трогаются.
"""
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sandbox import Sandbox, check, finish   # noqa: E402

sb = Sandbox()
chief = sb.user("chief_engineer")
mech = sb.user("mechanic")
master = sb.user("shift_supervisor", brigade="А")


def count(action):
    """Сколько записей с таким действием. В копии боевой базы часть из
    них уже есть — своё считаем разницей, а не от нуля."""
    return len(journal(action))


def journal(action):
    conn = sb.db()
    rows = conn.execute("SELECT * FROM audit_log WHERE action=? ORDER BY id DESC",
                        (action,)).fetchall()
    conn.close()
    return rows


# ── Документ станка: загрузка ───────────────────────────────────────
PDF = base64.b64encode("%PDF-1.4 проверка\n".encode()).decode()

was_uploads = count("equipment_document_uploaded")

r = chief.post(f"/api/equipment/{sb.equipment_id}/documents/upload-b64",
               json={"filename": "паспорт-проверка.pdf", "data": PDF})
check("документ загружен через карточку станка",
      r.status_code == 200 and r.json().get("success"), r.text[:200])

rows = journal("equipment_document_uploaded")
check("загрузка записана в журнал", len(rows) == was_uploads + 1,
      f"было {was_uploads}, стало {len(rows)}")
check("и видно, что именно загрузили",
      "паспорт-проверка.pdf" in (rows[0]["details"] or ""), dict(rows[0]))

conn = sb.db()
doc = conn.execute(
    "SELECT * FROM equipment_documents WHERE equipment_id=? ORDER BY id DESC LIMIT 1",
    (sb.equipment_id,)).fetchone()
conn.close()
doc_id = doc["id"]

# ── Документ станка: удаление ───────────────────────────────────────
r = mech.delete(f"/api/equipment/{sb.equipment_id}/documents/{doc_id}")
check("механик документы не убирает", r.status_code == 403, r.status_code)

r = chief.delete(f"/api/equipment/{sb.equipment_id}/documents/99999")
check("несуществующий документ — честный 404, а не «успешно»",
      r.status_code == 404, f"{r.status_code} {r.text[:120]}")

r = chief.delete(f"/api/equipment/{sb.equipment_id}/documents/{doc_id}")
check("документ убран из карточки", r.status_code == 200, r.text[:200])

rows = journal("equipment_document_deleted")
check("удаление записано", len(rows) == 1, len(rows))
check("с «было» — какой именно документ",
      "паспорт-проверка.pdf" in (rows[0]["before_json"] or ""), dict(rows[0]))
check("и сказано, что файл на диске остался",
      "остал" in (rows[0]["details"] or ""), dict(rows[0]))

# Парная проверка: 404 выше должен приходить на отсутствующий документ,
# а не на любой. Повторное удаление того же — снова 404, и это
# доказывает, что первое удаление действительно сработало.
r = chief.delete(f"/api/equipment/{sb.equipment_id}/documents/{doc_id}")
check("контрольная: повторное удаление уже убранного — тоже 404",
      r.status_code == 404, f"{r.status_code} {r.text[:120]}")
check("и второй записи в журнале от него нет",
      len(journal("equipment_document_deleted")) == 1,
      len(journal("equipment_document_deleted")))

conn = sb.db()
still = conn.execute("SELECT is_active FROM equipment_documents WHERE id=?", (doc_id,)).fetchone()
conn.close()
check("запись не стёрта, а снята с карточки", still["is_active"] == 0, dict(still))

# Файл остался на диске: паспорта и руководства по нажатию кнопки не стираем.
docs_root = sb.files_root / "docs"
files = list(docs_root.rglob("паспорт-проверка.pdf"))
check("файл документа на диске остался", len(files) == 1, [str(f) for f in files])

# ── Фото обхода: удаление ───────────────────────────────────────────
PNG = bytes.fromhex("89504e470d0a1a0a") + b"\x00" * 64

r = master.http.post("/api/checklist/photo",
                   files={"file": ("обход.png", PNG, "image/png")},
                   data={"equipment_id": str(sb.equipment_id)})
check("фото обхода загружено", r.status_code == 200 and r.json().get("success"),
      f"{r.status_code} {r.text[:200]}")
photo_id = r.json().get("photo_id") or r.json().get("id")

check("загрузка фото журнал не засоряет",
      len(journal("checklist_photo_uploaded")) == 0)

conn = sb.db()
row = conn.execute("SELECT * FROM checklist_photos ORDER BY id DESC LIMIT 1").fetchone()
conn.close()
photo_id = row["id"]
rel_path = row["rel_path"]

r = master.delete(f"/api/checklist/photo/{photo_id}")
check("своё фото до сдачи обхода удаляется", r.status_code == 200, r.text[:200])

rows = journal("checklist_photo_deleted")
check("удаление фото записано", len(rows) == 1, len(rows))
check("и видно, чьё фото и что стало с файлом",
      rel_path in (rows[0]["details"] or "") and "файл" in (rows[0]["details"] or ""),
      dict(rows[0]))

# ── Привязка обхода к обращению ─────────────────────────────────────
r = master.post("/api/checklist/link-case",
              json={"round_id": 1, "equipment_id": sb.equipment_id, "case_id": 777})
check("привязка принята", r.status_code == 200, r.text[:200])
rows = journal("checklist_linked_to_case")
check("привязка записана", len(rows) == 1, len(rows))
check("и в ней видно, к какому обращению",
      "777" in (rows[0]["target"] or ""), dict(rows[0]))

finish("Документы станка и фото обходов: след остаётся")
