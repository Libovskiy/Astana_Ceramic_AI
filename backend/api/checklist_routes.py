"""
Обход смены: загрузка фото на диск, защищённая отдача, сохранение обхода.

Файлы лежат в data/checklist_photos/ГГГГ/ММ/<sha256>.<ext> — вне docs/,
потому что docs смонтирован как StaticFiles на /docs-files без авторизации.
Отдаём только через /api/checklist/photo/{id} с проверкой сессии.

Подключение в main.py (две строки ПОСЛЕ app = FastAPI()):
    from backend.api.checklist_routes import router as checklist_router
    app.include_router(checklist_router)
"""
import hashlib
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Cookie, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from backend.config import DB_NAME, BASE_DIR
from backend.services.auth_service import get_user_by_session

router = APIRouter(prefix="/api/checklist", tags=["checklist"])

PHOTOS_DIR = BASE_DIR / "data" / "checklist_photos"

MAX_UPLOAD_BYTES = 12 * 1024 * 1024   # 12 МБ — телефон после сжатия отдаёт ~200-600 КБ
MAX_SIDE = 1600                        # длинная сторона после ресайза на сервере
JPEG_QUALITY = 82
DEDUP_DAYS = 30                        # окно поиска дублей по содержимому


# ── авторизация ───────────────────────────────────────────
# Свою зависимость, а не импорт из main.py — иначе циклический импорт.
def current_user(session_token: str | None = Cookie(default=None)):
    user = get_user_by_session(session_token)
    if user is None:
        raise HTTPException(status_code=401, detail="Не авторизован.")
    return user


def _db():
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    """
    Местное время завода. Весь ACAI пишет datetime.now(), фронт читает
    строку без пояса как местную — держим один стандарт, иначе даты
    разъезжаются на 5 часов (см. timeAgo в acai_layout.js).
    """
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _who(user) -> str:
    return user.get("full_name") or user.get("username") or "?"


# ── определение типа по содержимому, не по Content-Type ──
def _sniff(head: bytes):
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg", ".jpg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", ".png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp", ".webp"
    if head[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1", b"ftypmsf1"):
        return "image/heic", ".heic"
    return None, None


def _process(raw: bytes, ext: str):
    """
    Если есть Pillow — ужимаем и срезаем EXIF (в EXIF лежат GPS и модель телефона).
    Если Pillow нет — кладём как есть, размеры неизвестны.
    Возвращает (bytes, mime, ext, width, height).
    """
    try:
        import io
        from PIL import Image
    except ImportError:
        return raw, None, ext, None, None

    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
        out = io.BytesIO()
        # save без exif= — метаданные не переносятся
        img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        return out.getvalue(), "image/jpeg", ".jpg", img.width, img.height
    except Exception:
        return raw, None, ext, None, None


# ── загрузка ──────────────────────────────────────────────
@router.post("/photo")
async def upload_checklist_photo(
    file: UploadFile = File(...),
    equipment_id: int = Form(...),
    user: dict = Depends(current_user),
):
    # читаем кусками — чтобы 200-мегабайтный файл не лёг в память целиком
    raw = bytearray()
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        raw.extend(chunk)
        if len(raw) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Файл больше 12 МБ")
    raw = bytes(raw)

    if not raw:
        raise HTTPException(status_code=400, detail="Пустой файл")

    mime, ext = _sniff(raw[:16])
    if mime is None:
        raise HTTPException(status_code=415, detail="Это не изображение (ждём JPEG, PNG или WEBP)")
    if mime == "image/heic":
        raise HTTPException(
            status_code=415,
            detail="Формат HEIC не поддерживается — в настройках камеры iPhone выбери «Наиболее совместимый»",
        )

    # хэш считаем от ОРИГИНАЛА: тогда повторная отправка того же снимка
    # ловится, даже если сжатие на сервере даст другие байты
    file_hash = hashlib.sha256(raw).hexdigest()

    conn = _db()
    try:
        cutoff = (datetime.now() - timedelta(days=DEDUP_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
        dup = conn.execute(
            """SELECT id, equipment_id, created_at FROM checklist_photos
               WHERE file_hash = ? AND created_at > ?
               ORDER BY id LIMIT 1""",
            (file_hash, cutoff),
        ).fetchone()
        if dup:
            # файл не пишем повторно и строку не плодим — возвращаем старую
            return {
                "success": True,
                "duplicate": True,
                "id": dup["id"],
                "message": "Это фото уже загружали — сделай новый снимок",
            }

        data, new_mime, ext, width, height = _process(raw, ext)
        mime = new_mime or mime

        now = datetime.now()
        rel_dir = Path(f"{now:%Y}") / f"{now:%m}"
        rel_path = (rel_dir / f"{file_hash}{ext}").as_posix()
        dest = PHOTOS_DIR / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            dest.write_bytes(data)

        cur = conn.execute(
            """INSERT INTO checklist_photos
               (round_id, equipment_id, file_hash, rel_path, mime, size_bytes,
                width, height, uploaded_by, created_at)
               VALUES (NULL,?,?,?,?,?,?,?,?,?)""",
            (equipment_id, file_hash, rel_path, mime, len(data),
             width, height, user.get("username"), _now()),
        )
        conn.commit()
        photo_id = cur.lastrowid
    finally:
        conn.close()

    return {"success": True, "duplicate": False, "id": photo_id, "size": len(data)}


# ── отдача ────────────────────────────────────────────────
@router.get("/photo/{photo_id}")
def get_checklist_photo(photo_id: int, user: dict = Depends(current_user)):
    conn = _db()
    row = conn.execute(
        "SELECT rel_path, mime FROM checklist_photos WHERE id = ?", (photo_id,)
    ).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Фото не найдено")

    # rel_path писали мы сами, но проверяем, что путь не вылез из папки
    path = (PHOTOS_DIR / row["rel_path"]).resolve()
    if not str(path).startswith(str(PHOTOS_DIR.resolve())) or not path.exists():
        raise HTTPException(status_code=404, detail="Файл потерян")

    return FileResponse(
        path,
        media_type=row["mime"] or "image/jpeg",
        headers={"Cache-Control": "private, max-age=86400"},
    )


# ── фото по оборудованию (для карточки станка) ────────────
@router.get("/photos")
def photos_by_equipment(
    equipment_id: int,
    limit: int = 12,
    user: dict = Depends(current_user),
):
    """
    Снимки с обходов по одной единице оборудования, свежие первыми.
    Только привязанные к сданному обходу — черновики чужих незавершённых
    обходов показывать нельзя.
    """
    conn = _db()
    rows = conn.execute(
        """SELECT p.id, p.created_at, p.uploaded_by, p.round_id,
                  i.status, i.note, i.task_id
           FROM checklist_photos p
           LEFT JOIN checklist_items i
                  ON i.round_id = p.round_id
                 AND i.equipment_id = p.equipment_id
           WHERE p.equipment_id = ? AND p.round_id IS NOT NULL
           ORDER BY p.id DESC LIMIT ?""",
        (equipment_id, min(limit, 50)),
    ).fetchall()
    conn.close()
    return {"success": True, "photos": [dict(r) for r in rows]}


# ── удаление до отправки обхода ───────────────────────────
@router.delete("/photo/{photo_id}")
def delete_checklist_photo(photo_id: int, user: dict = Depends(current_user)):
    conn = _db()
    try:
        row = conn.execute(
            "SELECT rel_path, file_hash, round_id, uploaded_by FROM checklist_photos WHERE id = ?",
            (photo_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Фото не найдено")
        # привязанное к сданному обходу фото не трогаем — это уже документ
        if row["round_id"] is not None:
            raise HTTPException(status_code=409, detail="Обход уже сдан, фото удалить нельзя")
        if row["uploaded_by"] != user.get("username") and user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Это не ваше фото")

        conn.execute("DELETE FROM checklist_photos WHERE id = ?", (photo_id,))
        conn.commit()

        # файл удаляем только если на него больше никто не ссылается
        still = conn.execute(
            "SELECT 1 FROM checklist_photos WHERE file_hash = ? LIMIT 1", (row["file_hash"],)
        ).fetchone()
        if not still:
            try:
                (PHOTOS_DIR / row["rel_path"]).unlink(missing_ok=True)
            except Exception:
                pass
    finally:
        conn.close()
    return {"success": True}


# ── сохранение обхода ─────────────────────────────────────
@router.post("/round")
def save_round(request: dict, user: dict = Depends(current_user)):
    items = request.get("items") or []
    if not items:
        raise HTTPException(status_code=400, detail="Пустой обход")

    counts = {"ok": 0, "warn": 0, "bad": 0}
    for it in items:
        if it.get("status") in counts:
            counts[it["status"]] += 1

    problems = []   # что уйдёт главному инженеру

    conn = _db()
    try:
        cur = conn.execute(
            """INSERT INTO checklist_rounds
               (started_at, finished_at, shift, username, full_name,
                total_count, ok_count, warn_count, bad_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                request.get("started_at"),
                _now(),
                request.get("shift"),
                user.get("username"),
                _who(user),
                len(items),
                counts["ok"], counts["warn"], counts["bad"],
            ),
        )
        round_id = cur.lastrowid

        for it in items:
            status = it.get("status")
            eq_id = it.get("equipment_id")
            note = (it.get("note") or "").strip()

            icur = conn.execute(
                """INSERT INTO checklist_items (round_id, equipment_id, status, note, created_at)
                   VALUES (?,?,?,?,?)""",
                (round_id, eq_id, status, note, _now()),
            )
            item_id = icur.lastrowid

            photo_ids = [int(p) for p in (it.get("photo_ids") or [])]
            for pid in photo_ids:
                conn.execute(
                    """UPDATE checklist_photos SET round_id = ?
                       WHERE id = ? AND round_id IS NULL AND uploaded_by = ?""",
                    (round_id, pid, user.get("username")),
                )

            if status in ("warn", "bad"):
                eq = conn.execute(
                    "SELECT name, location FROM equipment WHERE id = ?", (eq_id,)
                ).fetchone()
                problems.append({
                    "item_id": item_id,
                    "equipment_id": eq_id,
                    "equipment_name": eq["name"] if eq else f"Оборудование #{eq_id}",
                    "location": (eq["location"] if eq else "") or "",
                    "status": status,
                    "note": note,
                    "photo_ids": photo_ids,
                })
        conn.commit()
    finally:
        conn.close()

    try:
        from backend.services.audit_service import log_action
        log_action(
            username=user.get("username"), role=user.get("role"),
            action="checklist_round_saved", target=f"round:{round_id}",
            details=f"ok={counts['ok']} warn={counts['warn']} bad={counts['bad']}",
        )
    except Exception:
        pass

    return {
        "success": True,
        "round_id": round_id,
        "problems": [
            {
                "item_id": pr["item_id"],
                "equipment_id": pr["equipment_id"],
                "equipment_name": pr["equipment_name"],
                "status": pr["status"],
                "note": pr["note"],
            }
            for pr in problems
        ],
        **counts,
    }


# ── привязка пункта обхода к обращению ────────────────────
@router.post("/link-case")
def link_case(request: dict, user: dict = Depends(current_user)):
    """
    Фронт создаёт обращение через /diagnose и возвращает сюда его id.
    Тогда фото с обхода видны прямо в карточке обращения.
    """
    round_id = request.get("round_id")
    equipment_id = request.get("equipment_id")
    case_id = request.get("case_id")
    if not all((round_id, equipment_id, case_id)):
        raise HTTPException(status_code=400, detail="Нужны round_id, equipment_id и case_id")

    conn = _db()
    try:
        conn.execute(
            """UPDATE checklist_items SET case_id = ?
               WHERE round_id = ? AND equipment_id = ?""",
            (case_id, round_id, equipment_id),
        )
        conn.execute(
            """UPDATE checklist_photos SET case_id = ?
               WHERE round_id = ? AND equipment_id = ?""",
            (case_id, round_id, equipment_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {"success": True}


# ── фото по обращению (для карточки на /cases) ────────────
@router.get("/photos-by-case")
def photos_by_case(case_ids: str, user: dict = Depends(current_user)):
    """
    case_ids — id через запятую. Одним запросом на всю страницу,
    чтобы не дёргать сервер по разу на каждое обращение.
    """
    ids = [int(x) for x in case_ids.split(",") if x.strip().isdigit()][:100]
    if not ids:
        return {"success": True, "photos": {}}

    placeholders = ",".join("?" * len(ids))
    conn = _db()
    rows = conn.execute(
        f"""SELECT id, case_id FROM checklist_photos
            WHERE case_id IN ({placeholders}) ORDER BY id""",
        ids,
    ).fetchall()
    conn.close()

    grouped: dict[str, list] = {}
    for r in rows:
        grouped.setdefault(str(r["case_id"]), []).append(r["id"])
    return {"success": True, "photos": grouped}


# ── история обходов ───────────────────────────────────────
@router.get("/rounds")
def list_rounds(limit: int = 50, user: dict = Depends(current_user)):
    conn = _db()
    rows = conn.execute(
        """SELECT r.*, (SELECT COUNT(*) FROM checklist_photos p WHERE p.round_id = r.id) AS photo_count
           FROM checklist_rounds r ORDER BY r.id DESC LIMIT ?""",
        (min(limit, 200),),
    ).fetchall()
    conn.close()
    return {"success": True, "rounds": [dict(r) for r in rows]}


@router.get("/rounds/{round_id}")
def get_round(round_id: int, user: dict = Depends(current_user)):
    conn = _db()
    head = conn.execute("SELECT * FROM checklist_rounds WHERE id = ?", (round_id,)).fetchone()
    if not head:
        conn.close()
        raise HTTPException(status_code=404, detail="Обход не найден")

    items = conn.execute(
        """SELECT i.*, e.name AS equipment_name, e.location
           FROM checklist_items i
           LEFT JOIN equipment e ON e.id = i.equipment_id
           WHERE i.round_id = ? ORDER BY i.id""",
        (round_id,),
    ).fetchall()
    photos = conn.execute(
        "SELECT id, equipment_id FROM checklist_photos WHERE round_id = ? ORDER BY id", (round_id,)
    ).fetchall()
    conn.close()

    by_eq: dict = {}
    for ph in photos:
        by_eq.setdefault(ph["equipment_id"], []).append(ph["id"])

    out = []
    for i in items:
        d = dict(i)
        d["photo_ids"] = by_eq.get(i["equipment_id"], [])
        out.append(d)

    return {"success": True, "round": dict(head), "items": out}

