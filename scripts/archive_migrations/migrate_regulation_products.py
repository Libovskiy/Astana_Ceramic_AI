"""
Миграция: вид продукции → изделие → версии регламента изделия.

Зачем
-----
Версии регламента считались по одному полю «вид продукции», и на пару
(вид, версия) стоял запрет повторов. Из-за этого два РАЗНЫХ изделия с
одним видом система считала версиями друг друга.

Как это выглядело на заводе. 23.09.2026 технолог за семь минут завёл
девять регламентов. Четыре блока — 2.1NF, 6.9NF, 25-10.7NF и снова
6.9NF — легли версиями 1, 2, 3, 4 одного «CERABLOCK», как будто каждое
следующее изделие заменило предыдущее. Дальше он стал дописывать точки
к виду: «Cerablock», «Cerablock.», «Cerablock..» — это был единственный
способ получить свободное имя. Он не ошибался, он обходил ограничение.

Та же причина у 38 версий «1.4 НФ пустотелый» и у пары «кирпич /
Полнотелый», где поля «вид» и «название» перепутаны при создании.

Что делает миграция
-------------------
1. Приводит вид к справочнику: Полнотелый, Пустотелый, Блок.
   Восемь написаний сливаются в три.
2. Приводит название изделия к одному виду записи.
3. Перенумеровывает версии внутри изделия.
4. Убирает в архив два регламента, заведённых дважды по ошибке ввода
   (согласовано с технологом 25.09.2026).
5. Пересобирает таблицу с новым ключом UNIQUE (product_type, name,
   version) — в SQLite ограничение иначе не поменять.

Ничего не удаляется: архивные версии остаются историей, id и все
ссылки на них сохраняются.

Таблица соответствия согласована с технологом до запуска.

Запуск один раз:  python scripts/archive_migrations/migrate_regulation_products.py [путь_к_базе]
"""

import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

DB = sys.argv[1] if len(sys.argv) > 1 else "factory.db"

# ── Вид продукции: как в справочнике product_types ──────────────────
VID = {
    "пустотелый": "Пустотелый",
    "полнотелый": "Полнотелый",
    # Поля перепутаны при создании: в «виде» стояло «кирпич»,
    # а в «названии» — «Полнотелый».
    "кирпич": "Полнотелый",
    # Cerablock — торговое имя блоков, а не отдельный вид. Так
    # регламенты сходятся с разбором Экселя, где блоки идут видом
    # «Блок» и считаются кубометрами.
    "cerablock": "Блок",
    "блок": "Блок",
}

# ── Изделие: одна запись вместо разнобоя ────────────────────────────
IZD = {
    "1.4 нф пустотелый": "1,4 НФ пустотелый",
    "2.1 нф пустотелый": "2,1 НФ пустотелый",
    "1.4 нф полнотелый": "1,4 НФ полнотелый",
    "полнотелый": "Полнотелый (размер не указан)",
    "2.1nf cerablock": "2,1 НФ Cerablock",
    "6.9nf cerablock": "6,9 НФ Cerablock",
    "25-10.7nf cerablock": "25-10,7 НФ Cerablock",
    "38 - 10.7nf cerablock": "38-10,7 НФ Cerablock",
    "4.6nf cerablock": "4,6 НФ Cerablock",
}

# Заведены дважды за две минуты, оба пустые. Технолог решил оставить
# по одной версии, вторую убрать в архив как ошибку ввода.
DOUBLE_ENTRY = {46: "6,9 НФ Cerablock", 47: "25-10,7 НФ Cerablock"}


def fold(value: str) -> str:
    """Точки в конце дописывали, чтобы обойти запрет повторов."""
    return re.sub(r"[.\s]+$", "", (value or "").strip()).lower()


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = [dict(r) for r in cur.execute(
        "SELECT * FROM regulations ORDER BY id")]
    if not rows:
        print("Регламентов нет — переносить нечего.")
        return

    # ── 1-3. Вид, изделие, номер версии внутри изделия ──────────────
    counter = defaultdict(int)
    plan = []
    for row in rows:
        vid = VID.get(fold(row["product_type"]), row["product_type"])
        izd = IZD.get(fold(row["name"]), row["name"])
        counter[(vid, izd)] += 1
        plan.append((row, vid, izd, counter[(vid, izd)]))

    # ── 5. Пересборка таблицы с новым ключом ────────────────────────
    # Сначала снимаем старое ограничение, иначе перенумерация упрётся
    # в UNIQUE (product_type, version) на полпути.
    schema = cur.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='regulations'"
    ).fetchone()["sql"]

    new_schema = schema.replace(
        "UNIQUE (product_type, version)",
        "UNIQUE (product_type, name, version)",
    ).replace("regulations", "regulations_new", 1)

    if "UNIQUE (product_type, name, version)" not in new_schema:
        print("Ключ в схеме не найден — база уже перенесена? Выходим, ничего не меняя.")
        return

    cur.execute("PRAGMA foreign_keys = OFF")
    cur.execute(new_schema)

    columns = [c["name"] for c in cur.execute("PRAGMA table_info(regulations)")]
    placeholders = ", ".join("?" for _ in columns)
    quoted = ", ".join(f'"{c}"' for c in columns)

    for row, vid, izd, ver in plan:
        item = dict(row)
        item["product_type"] = vid
        item["name"] = izd
        item["version"] = ver
        # ── 4. Повторный ввод — в архив ─────────────────────────────
        if row["id"] in DOUBLE_ENTRY and item["status"] != "archived":
            item["status"] = "archived"
        cur.execute(
            f'INSERT INTO regulations_new ({quoted}) VALUES ({placeholders})',
            [item[c] for c in columns],
        )

    cur.execute("DROP TABLE regulations")
    cur.execute("ALTER TABLE regulations_new RENAME TO regulations")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_reg_product "
        "ON regulations(product_type, name, status)"
    )
    cur.execute("PRAGMA foreign_keys = ON")
    conn.commit()

    # ── Отчёт ───────────────────────────────────────────────────────
    print(f"Перенесено регламентов: {len(plan)}\n")
    print("ВИДЫ")
    merged = defaultdict(set)
    for row, vid, _, _ in plan:
        merged[vid].add(row["product_type"])
    for vid, olds in sorted(merged.items()):
        print(f"  {vid:11} ← {', '.join(sorted(olds))}")

    print("\nИЗДЕЛИЯ")
    for r in cur.execute(
        "SELECT product_type, name, COUNT(*) n, "
        "SUM(status='active') a, SUM(status='draft') d, SUM(status='archived') ar "
        "FROM regulations GROUP BY product_type, name "
        "ORDER BY product_type, name"
    ):
        print(f"  {r['product_type']:11} · {r['name']:30} "
              f"версий {r['n']:2}  действующих {r['a']}  черновиков {r['d']}  в архиве {r['ar']}")

    broken = cur.execute(
        "SELECT COUNT(*) FROM regulations r1 JOIN regulations r2 "
        "ON r1.product_type=r2.product_type AND r1.name=r2.name "
        "AND r1.version=r2.version AND r1.id<r2.id"
    ).fetchone()[0]
    print(f"\nПовторов «вид + изделие + версия»: {broken}")

    for name, table, column in (
        ("параметров", "regulation_parameters", "regulation_id"),
        ("этапов", "regulation_stages", "regulation_id"),
        ("ознакомлений", "regulation_ack", "regulation_id"),
        ("записей истории", "regulation_changes", "regulation_id"),
    ):
        total = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        orphan = cur.execute(
            f"SELECT COUNT(*) FROM {table} t "
            f"LEFT JOIN regulations r ON r.id = t.{column} WHERE r.id IS NULL"
        ).fetchone()[0]
        print(f"  {name}: {total}, потеряли регламент: {orphan}")

    conn.close()


if __name__ == "__main__":
    main()
