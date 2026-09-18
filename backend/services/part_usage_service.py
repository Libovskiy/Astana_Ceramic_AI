"""
Связь ремонта со складом: что подсказать слесарю и кто списывает.

ЗАЧЕМ. ИИ советует заменить подшипник, слесарь его меняет и пишет
«заменил подшипник» — а на складе остаётся прежнее число. Через месяц
станок стоит, потому что подшипника нет, хотя в системе он «есть».

КАК РЕШЕНО (решение владельца, 18.09.2026). Списывает не слесарь:
за склад отвечают главный механик (запчасти оборудования) и главный
энергетик — главный электрик (кабель, контакторы, датчики). Значит,
система должна не списывать сама, а СКАЗАТЬ ответственному, что по
такому-то ремонту, судя по тексту и рекомендации ИИ, скорее всего
взяли такую-то деталь. Он сверяет и проводит списание — одной кнопкой.

Поэтому здесь два разных дела:

  1. suggest_for_text() — догадка по тексту. Ищет в складе названия и
     каталожные номера, которые встречаются в рекомендации ИИ или в
     отчёте о ремонте. Догадка честная: помечается как предположение,
     ничего не списывается без человека.

  2. open_writeoff() / pending() / apply() / skip() — заявка на
     списание. Появляется, когда специалист отмечает ремонт, идёт
     тому, кто отвечает за эту дисциплину, и живёт до решения.

И третье, для цеха: stock_note() — строка «на складе 3 шт» или «на
складе нет» рядом с советом ИИ, чтобы слесарь не шёл к полке зря.

Ничего из этого не списывает остаток само. Автоматическое списание по
догадке ИИ сделало бы склад ещё менее достоверным, чем сейчас.
"""

import json
import re
import sqlite3
from datetime import datetime

from backend.config import DB_NAME


def get_connection():
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# Кто за что отвечает. Слесарь и электрик тут не при чём — они
# заявку создают самим фактом ремонта, но не проводят её.
RESPONSIBLE = {
    "mechanical": ("chief_mechanic",),
    "electrical": ("chief_electrician",),
}

# Видят и проводят любую заявку, независимо от дисциплины.
OVERSEERS = ("admin", "director", "chief_engineer")

# Какие категории склада к какой дисциплине относятся. Расходники —
# к обеим: масло и смазку берут и механики, и электрики.
CATEGORY_DISCIPLINE = {
    "mechanical": ("mechanical", "consumable", "other"),
    "electrical": ("electrical", "consumable", "other"),
}


def init_part_usage():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS part_writeoffs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL UNIQUE,   -- одна заявка на обращение
            equipment_id INTEGER,
            equipment_name TEXT,
            discipline TEXT,                   -- mechanical / electrical
            repair_text TEXT,                  -- что написал специалист
            suggested TEXT,                    -- догадка: json со списком деталей
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',   -- pending / done / skipped
            resolved_by TEXT,
            resolved_at TEXT,
            note TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_writeoffs_status ON part_writeoffs(status, discipline)")

    # В журнале склада не было ни обращения, ни станка: нельзя было
    # ответить «на что ушло» и «что меняем чаще всего».
    columns = {row[1] for row in conn.execute("PRAGMA table_info(parts_log)")}
    for column in ("case_id INTEGER", "equipment_id INTEGER", "note TEXT"):
        name = column.split()[0]
        if name not in columns:
            conn.execute(f"ALTER TABLE parts_log ADD COLUMN {column}")

    conn.commit()
    conn.close()


# ── догадка по тексту ─────────────────────────────────────

_WORD = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9\-\.]{2,}")


def _normalize(text: str) -> str:
    return (text or "").lower().replace("ё", "е")


def _stem(word: str) -> str:
    """
    Грубая основа слова: «подшипника», «подшипники» → «подшипник».

    Полноценной морфологии здесь не нужно и нет: сравниваются названия
    со склада с текстом ремонта, и хватает совпадения по началу слова.
    """
    word = word.strip(".,;:()«»\"'")
    return word[:-2] if len(word) > 6 else word[:-1] if len(word) > 4 else word


def _tokens(text: str) -> set:
    return {_stem(w) for w in _WORD.findall(_normalize(text))}


def suggest_for_text(text: str, equipment_id=None, discipline=None, limit: int = 5) -> list:
    """
    Что из склада упомянуто в тексте. Возвращает список деталей с
    остатком и причиной совпадения — это предположение, не факт.
    """
    if not (text or "").strip():
        return []

    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT p.*, e.name AS eq_name
            FROM parts p
            LEFT JOIN equipment e ON e.id = p.equipment_id
        """).fetchall()
    finally:
        conn.close()

    allowed = CATEGORY_DISCIPLINE.get(discipline) if discipline else None
    text_norm = _normalize(text)
    text_tokens = _tokens(text)

    found = []

    for row in rows:
        part = dict(row)

        if allowed and (part.get("category") or "other") not in allowed:
            continue

        score = 0
        why = None

        # Каталожный номер в тексте — самое надёжное совпадение.
        number = _normalize(part.get("part_number") or "")
        if len(number) >= 3 and number not in ("—", "-") and number in text_norm:
            score += 10
            why = f"в тексте есть номер {part['part_number']}"

        # Название: совпадать должны значимые слова, а не любое «для».
        name_tokens = {t for t in _tokens(part.get("name") or "") if len(t) >= 4}
        hit = name_tokens & text_tokens
        if hit:
            score += 3 * len(hit)
            why = why or f"в тексте есть «{', '.join(sorted(hit))}»"

        if not score:
            continue

        # Деталь именно этого станка важнее общей со склада.
        if equipment_id and part.get("equipment_id") == equipment_id:
            score += 4

        found.append({
            "part_id": part["id"],
            "name": part["name"],
            "part_number": part.get("part_number"),
            "unit": part.get("unit") or "шт",
            "stock": part.get("quantity") or 0,
            "min_quantity": part.get("min_quantity") or 0,
            "equipment_name": part.get("eq_name"),
            "last_used_at": part.get("last_used_at"),
            "why": why,
            "score": score,
        })

    found.sort(key=lambda item: -item["score"])
    return found[:limit]


def stock_note(text: str, equipment_id=None, discipline=None) -> str:
    """
    Строка про склад к совету ИИ: есть ли деталь и где её взять.

    Пустая строка, если в совете нет ничего похожего на складскую
    позицию — лишнего шума в ответе не будет.
    """
    items = suggest_for_text(text, equipment_id=equipment_id, discipline=discipline, limit=3)
    if not items:
        return ""

    lines = []
    for item in items:
        where = f" · {item['equipment_name']}" if item.get("equipment_name") else ""
        if item["stock"] > 0:
            low = " (это последнее — ниже минимума)" if item["stock"] <= item["min_quantity"] else ""
            lines.append(f"📦 {item['name']} — на складе {item['stock']:g} {item['unit']}{low}{where}")
        else:
            last = f", последний раз брали {item['last_used_at'][:10]}" if item.get("last_used_at") else ""
            lines.append(f"📦 {item['name']} — на складе НЕТ{last}. Скажите снабжению, не ищите зря.")

    return "\n".join(lines)


# ── заявка на списание ────────────────────────────────────

def _case_context(conn, case_id: int) -> dict:
    row = conn.execute("""
        SELECT c.id, c.equipment_id, c.machine, c.required_discipline,
               c.draft_resolution_comment, c.resolution_comment,
               e.name AS equipment_name, e.discipline AS equipment_discipline
        FROM cases c
        LEFT JOIN equipment e ON e.id = c.equipment_id
        WHERE c.id = ?
    """, (case_id,)).fetchone()
    return dict(row) if row else {}


def open_writeoff(case_id: int, repair_text: str = "") -> int | None:
    """
    Специалист отметил ремонт — заводим заявку ответственному.

    Догадку собираем из двух источников: что написал специалист и что
    советовал ИИ в этом обращении (совет мог быть точнее текста —
    «заменить подшипник 6208» против «поменял, что стучало»).

    Молчит и ничего не создаёт, если в складе нет ни одной похожей
    позиции: пустая заявка «возможно что-то взяли» никому не нужна.
    """
    conn = get_connection()
    try:
        case = _case_context(conn, case_id)
        if not case:
            return None

        existing = conn.execute(
            "SELECT id, status FROM part_writeoffs WHERE case_id = ?", (case_id,)
        ).fetchone()
        if existing:
            return existing["id"]

        advice = conn.execute(
            "SELECT message FROM chat_history WHERE case_id = ? AND role = 'assistant' ORDER BY id",
            (case_id,)
        ).fetchall()

        discipline = (case.get("required_discipline")
                      or case.get("equipment_discipline") or "mechanical")
        if discipline not in RESPONSIBLE:
            discipline = "mechanical"

        text = "\n".join(filter(None, [
            repair_text or case.get("draft_resolution_comment") or case.get("resolution_comment") or "",
            *[row["message"] for row in advice],
        ]))

        suggested = suggest_for_text(text, equipment_id=case.get("equipment_id"), discipline=discipline)
        if not suggested:
            return None

        cursor = conn.execute("""
            INSERT INTO part_writeoffs
                (case_id, equipment_id, equipment_name, discipline, repair_text,
                 suggested, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
        """, (
            case_id, case.get("equipment_id"),
            case.get("equipment_name") or case.get("machine"),
            discipline,
            (repair_text or case.get("draft_resolution_comment") or "")[:1000],
            json.dumps(suggested, ensure_ascii=False),
            now(),
        ))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def can_resolve(user: dict, discipline: str) -> bool:
    role = (user or {}).get("role")
    return role in OVERSEERS or role in RESPONSIBLE.get(discipline, ())


def pending(user: dict) -> list:
    """Заявки, которые должен разобрать именно этот человек."""
    role = (user or {}).get("role")

    if role in OVERSEERS:
        disciplines = tuple(RESPONSIBLE)
    else:
        disciplines = tuple(d for d, roles in RESPONSIBLE.items() if role in roles)

    if not disciplines:
        return []

    placeholders = ",".join("?" * len(disciplines))
    conn = get_connection()
    try:
        rows = conn.execute(f"""
            SELECT w.*, c.symptom, c.worker_question
            FROM part_writeoffs w
            LEFT JOIN cases c ON c.id = w.case_id
            WHERE w.status = 'pending' AND w.discipline IN ({placeholders})
              AND COALESCE(c.is_test, 0) = 0
            ORDER BY w.id DESC
        """, disciplines).fetchall()
    finally:
        conn.close()

    items = []
    for row in rows:
        item = dict(row)
        try:
            item["suggested"] = json.loads(item.get("suggested") or "[]")
        except ValueError:
            item["suggested"] = []
        items.append(item)
    return items


def pending_count(user: dict) -> int:
    return len(pending(user))


def apply(writeoff_id: int, items: list, user: dict, note: str = "") -> dict:
    """
    Провести списание: снять остаток и записать, на какое обращение ушло.

    В минус не уходим — если на складе меньше, чем списывают, ставим
    ноль и говорим об этом прямо: значит, учёт уже расходился с полкой.
    """
    conn = get_connection()
    try:
        writeoff = conn.execute("SELECT * FROM part_writeoffs WHERE id = ?", (writeoff_id,)).fetchone()
        if not writeoff:
            raise ValueError("Заявка не найдена.")
        if writeoff["status"] != "pending":
            raise ValueError("Эта заявка уже разобрана.")
        if not can_resolve(user, writeoff["discipline"]):
            raise PermissionError("Списывать по этой части отвечает другой человек.")

        who = (user or {}).get("full_name") or (user or {}).get("username")
        stamp = now()
        written, shortages = [], []

        for entry in items or []:
            part_id = int(entry.get("part_id"))
            quantity = float(entry.get("quantity") or 0)
            if quantity <= 0:
                continue

            part = conn.execute("SELECT * FROM parts WHERE id = ?", (part_id,)).fetchone()
            if not part:
                continue

            stock = float(part["quantity"] or 0)
            taken = min(quantity, stock)
            if taken < quantity:
                shortages.append(f"{part['name']}: списали {taken:g} из {quantity:g} — на складе было меньше")

            conn.execute(
                "UPDATE parts SET quantity = ?, last_used_at = ? WHERE id = ?",
                (stock - taken, stamp, part_id)
            )
            conn.execute("""
                INSERT INTO parts_log
                    (part_id, quantity_change, direction, changed_by, changed_at,
                     case_id, equipment_id, note)
                VALUES (?, ?, 'out', ?, ?, ?, ?, ?)
            """, (
                part_id, quantity, who, stamp,
                writeoff["case_id"], writeoff["equipment_id"],
                note or f"ремонт по обращению №{writeoff['case_id']}",
            ))
            written.append(f"{part['name']} — {quantity:g} {part['unit'] or 'шт'}")

        conn.execute("""
            UPDATE part_writeoffs
            SET status = 'done', resolved_by = ?, resolved_at = ?, note = ?
            WHERE id = ?
        """, (who, stamp, note or None, writeoff_id))
        conn.commit()

        return {"written": written, "shortages": shortages, "case_id": writeoff["case_id"]}
    finally:
        conn.close()


def skip(writeoff_id: int, user: dict, note: str = "") -> dict:
    """«Ничего со склада не брали» — заявка закрывается без списания."""
    conn = get_connection()
    try:
        writeoff = conn.execute("SELECT * FROM part_writeoffs WHERE id = ?", (writeoff_id,)).fetchone()
        if not writeoff:
            raise ValueError("Заявка не найдена.")
        if writeoff["status"] != "pending":
            raise ValueError("Эта заявка уже разобрана.")
        if not can_resolve(user, writeoff["discipline"]):
            raise PermissionError("Списывать по этой части отвечает другой человек.")

        who = (user or {}).get("full_name") or (user or {}).get("username")
        conn.execute("""
            UPDATE part_writeoffs
            SET status = 'skipped', resolved_by = ?, resolved_at = ?, note = ?
            WHERE id = ?
        """, (who, now(), note or None, writeoff_id))
        conn.commit()
        return {"case_id": writeoff["case_id"]}
    finally:
        conn.close()


def history_for_part(part_id: int, limit: int = 20) -> list:
    """На что ушла деталь: обращение, станок, кто списал."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT l.*, e.name AS equipment_name
            FROM parts_log l
            LEFT JOIN equipment e ON e.id = l.equipment_id
            WHERE l.part_id = ?
            ORDER BY l.id DESC LIMIT ?
        """, (part_id, limit)).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def add_stock_note(case_id: int, advice_text: str) -> str | None:
    """
    Дописать в переписку строку про склад к совету ИИ.

    Отдельным сообщением с ролью 'system', а не внутри совета: совет
    сравнивается с тем, что ИИ уже предлагал (`_tried_actions` в
    conversation_service), и любая приписка в его тексте заставила бы
    ИИ повторять шаги по кругу. Системные строки в это сравнение и в
    промпт не попадают.

    Повторно одно и то же не пишем: на каждом шаге напоминать про
    остаток незачем.
    """
    conn = get_connection()
    try:
        case = _case_context(conn, case_id)
        if not case:
            return None
        discipline = (case.get("required_discipline")
                      or case.get("equipment_discipline") or None)

        note = stock_note(advice_text, equipment_id=case.get("equipment_id"), discipline=discipline)
        if not note:
            return None

        already = conn.execute(
            "SELECT 1 FROM chat_history WHERE case_id = ? AND role = 'system' AND message = ? LIMIT 1",
            (case_id, note)
        ).fetchone()
        if already:
            return None
    finally:
        conn.close()

    from backend.services.conversation_service import add_message
    add_message(case_id, "system", note, author="ACAI")
    return note
