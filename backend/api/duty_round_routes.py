"""
Обход дежурного электрика и слесаря: листы, фото, сдача, журнал,
неисправности. Логика и права — в backend/services/duty_round_service.py.

Фото лежат рядом с фото «Обхода смены», в своей подпапке
data/checklist_photos/duty/ГГГГ/ММ/ — та же папка уже исключена из
выкладки и попадает в бэкап. Отдаются только через
/api/duty-round/photo/{id} с проверкой входа и роли.
"""

import hashlib
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from backend.api.checklist_routes import MAX_UPLOAD_BYTES, _process, _sniff, current_user
from backend.config import CHECKLIST_PHOTOS_DIR
from backend.services import duty_round_service as svc
from backend.services.audit_service import log_action

router = APIRouter(prefix="/api/duty-round", tags=["duty-round"])

PHOTOS_DIR = CHECKLIST_PHOTOS_DIR


def viewer(user: dict = Depends(current_user)):
    if user["role"] != "admin" and user["role"] not in svc.VIEW_ROLES:
        raise HTTPException(status_code=403, detail="Обход дежурного вам недоступен.")
    return user


def _conductor(user: dict, kind: str) -> None:
    if kind not in svc.TEMPLATES:
        raise HTTPException(status_code=400, detail="Нет такого листа обхода.")
    if kind not in svc.can_conduct(user["role"]):
        who = "электрик" if kind == "el" else "слесарь"
        raise HTTPException(status_code=403, detail=f"Этот лист заполняет дежурный {who}.")


def _who(user: dict) -> str:
    return user.get("full_name") or user.get("username") or "?"


# ── листы и права ─────────────────────────────────────────
@router.get("/template")
def template(user: dict = Depends(viewer)):
    """Оба листа и что этому человеку можно — кнопки страница рисует отсюда."""
    return {
        "success": True,
        "templates": svc.TEMPLATES,
        "severities": svc.SEVERITIES,
        "can_conduct": svc.can_conduct(user["role"]),
        "can_resolve": svc.can_resolve(user["role"]),
        "full_name": _who(user),
    }


# ── фото ──────────────────────────────────────────────────
@router.post("/photo")
async def upload_photo(file: UploadFile = File(...), kind: str = Form(...),
                       user: dict = Depends(viewer)):
    _conductor(user, kind)

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
        raise HTTPException(status_code=415,
                            detail="Формат HEIC не поддерживается — в настройках камеры iPhone "
                                   "выберите «Наиболее совместимый»")

    file_hash = hashlib.sha256(raw).hexdigest()
    data, new_mime, ext, _w, _h = _process(raw, ext)
    mime = new_mime or mime

    now = datetime.now()
    rel_path = (Path("duty") / f"{now:%Y}" / f"{now:%m}" / f"{file_hash}{ext}").as_posix()
    dest = PHOTOS_DIR / rel_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        dest.write_bytes(data)

    conn = svc._db()
    try:
        cur = conn.execute(
            """INSERT INTO duty_round_photos
               (file_hash, rel_path, mime, size_bytes, uploaded_by, created_at)
               VALUES (?,?,?,?,?,?)""",
            (file_hash, rel_path, mime, len(data), user.get("username"), svc._now()),
        )
        conn.commit()
        photo_id = cur.lastrowid
    finally:
        conn.close()
    return {"success": True, "id": photo_id}


@router.get("/photo/{photo_id}")
def get_photo(photo_id: int, user: dict = Depends(viewer)):
    conn = svc._db()
    try:
        row = conn.execute(
            "SELECT rel_path, mime, round_id, uploaded_by FROM duty_round_photos WHERE id = ?",
            (photo_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Фото не найдено")
    # черновик чужого незаконченного обхода не показываем
    if row["round_id"] is None and row["uploaded_by"] != user.get("username") \
            and user["role"] != "admin":
        raise HTTPException(status_code=404, detail="Фото не найдено")

    path = (PHOTOS_DIR / row["rel_path"]).resolve()
    if not path.is_relative_to(PHOTOS_DIR.resolve()) or not path.exists():
        raise HTTPException(status_code=404, detail="Файл потерян")
    return FileResponse(path, media_type=row["mime"] or "image/jpeg",
                        headers={"Cache-Control": "private, max-age=86400"})


@router.delete("/photo/{photo_id}")
def delete_photo(photo_id: int, user: dict = Depends(viewer)):
    conn = svc._db()
    try:
        row = conn.execute(
            "SELECT rel_path, file_hash, round_id, uploaded_by FROM duty_round_photos WHERE id = ?",
            (photo_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Фото не найдено")
        if row["round_id"] is not None:
            raise HTTPException(status_code=409, detail="Обход уже сдан, фото удалить нельзя")
        if row["uploaded_by"] != user.get("username") and user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Это не ваше фото")
        conn.execute("DELETE FROM duty_round_photos WHERE id = ?", (photo_id,))
        conn.commit()
        still = conn.execute(
            "SELECT 1 FROM duty_round_photos WHERE file_hash = ? LIMIT 1", (row["file_hash"],)
        ).fetchone()
    finally:
        conn.close()
    if not still:
        try:
            (PHOTOS_DIR / row["rel_path"]).unlink(missing_ok=True)
        except OSError:
            pass
    return {"success": True}


# ── сдача обхода ──────────────────────────────────────────
@router.post("/round")
def submit_round(request: dict, user: dict = Depends(viewer)):
    kind = request.get("kind")
    _conductor(user, kind)
    try:
        saved = svc.save_round(kind, user, request)
    except svc.RoundError as error:
        raise HTTPException(status_code=400, detail=str(error))

    try:
        log_action(
            username=user.get("username"), role=user.get("role"),
            action="duty_round_saved", target=f"duty_round:{saved['round_id']}",
            details=f"{svc.TEMPLATES[kind]['full_title']}: проверено {saved['checked']} "
                    f"из {saved['total']}, неисправностей {saved['bad']}",
        )
    except Exception:
        pass
    return {"success": True, **saved}


# ── журнал ────────────────────────────────────────────────
@router.get("/rounds")
def rounds(kind: str | None = None, limit: int = 60, user: dict = Depends(viewer)):
    return {"success": True, "rounds": svc.list_rounds(kind, limit)}


@router.get("/rounds/{round_id}")
def round_detail(round_id: int, user: dict = Depends(viewer)):
    rnd = svc.get_round(round_id)
    if not rnd:
        raise HTTPException(status_code=404, detail="Обход не найден")
    rnd["report"] = svc.report_text(rnd)
    return {"success": True, "round": rnd}


# ── неисправности ─────────────────────────────────────────
@router.get("/faults")
def faults(resolved: bool = False, user: dict = Depends(viewer)):
    out = {"success": True, "open": svc.open_faults()}
    if resolved:
        out["resolved"] = svc.resolved_faults()
    return out


def _repairer(user: dict, fault_id: int) -> dict:
    fault = svc.get_fault(fault_id)
    if not fault:
        raise HTTPException(status_code=404, detail="Неисправность не найдена")
    if fault["kind"] not in svc.can_resolve(user["role"]):
        who = "электрик" if fault["kind"] == "el" else "слесарь"
        raise HTTPException(status_code=403,
                            detail=f"Ремонт отмечает {who}, его начальник или главный инженер.")
    return fault


@router.post("/faults/{fault_id}/start")
def start_repair(fault_id: int, user: dict = Depends(viewer)):
    fault = _repairer(user, fault_id)
    try:
        rep = svc.start_repair(fault_id, user)
    except svc.RepairError as error:
        raise HTTPException(status_code=409, detail=str(error))
    log_action(
        username=_who(user), role=user["role"],
        action="duty_repair_started", target=f"duty_repair:{rep['id']}",
        details=f"Начат ремонт: {fault['equipment']} — {fault['item']}",
    )
    return {"success": True, "repair": rep}


@router.post("/faults/{fault_id}/resolve")
def resolve(fault_id: int, request: dict | None = None, user: dict = Depends(viewer)):
    """
    «Закончил ремонт». Если «Начал» не нажимали — в запросе started_at:
    человек указывает начало сам, иначе время ремонта не из чего считать.
    """
    fault = _repairer(user, fault_id)
    body = request or {}
    try:
        rep = svc.finish_repair(fault_id, user, body.get("note") or "", body.get("started_at"))
    except svc.RepairError as error:
        raise HTTPException(status_code=400, detail=str(error))
    log_action(
        username=_who(user), role=user["role"],
        action="duty_fault_resolved", target=f"duty_repair:{rep['id']}",
        details=f"Устранено: {fault['equipment']} — {fault['item']}, ремонт "
                f"{svc.fmt_minutes(rep['repair_min'])}"
                + (" (начало указано вручную)" if rep["start_entered_late"] else "")
                + f", записей закрыто: {rep['closed']}",
        before={"resolved_at": None},
        after={"resolved_by": _who(user), "started_at": rep["started_at"],
               "finished_at": rep["finished_at"], "repair_min": rep["repair_min"]},
    )
    return {"success": True, "closed": rep["closed"], "repair": rep}


# ── время ремонтов за месяц — для руководства ─────────────
@router.get("/repairs")
def repairs(month: str | None = None, user: dict = Depends(viewer)):
    from datetime import datetime as _dt
    try:
        rep = svc.repairs_month(month or _dt.now().strftime("%Y-%m"))
    except svc.RepairError as error:
        raise HTTPException(status_code=400, detail=str(error))
    rep["report"] = svc.month_report_text(rep)
    return {"success": True, **rep}
