"""
Удаление двух регламентов «Полнотелый (размер не указан)», №39 и №40.

Решение владельца от 25.09.2026, согласовано с технологом. Отдельно
оговорено: весь остальной архив не трогать никогда — там подписи
людей об ознакомлении с конкретными версиями.

Почему удаляем именно эти две. Они заведены 13.09 технической учётной
записью с перепутанными полями: в «виде продукции» стояло «кирпич», в
«названии» — «Полнотелый», без размера изделия. Содержимое — по одному
этапу с именем «12» и по одному параметру «Влажность массы»; в истории
одна запись с причиной «1». Ознакомлений нет, замеров нет.

Перед удалением скрипт САМ проверяет, что наружу они не ссылаются, и
отказывается работать, если найдёт хоть одну внешнюю ссылку. Каскадом
не удаляем: если ссылки появятся, их надо показать человеку, а не
снести вместе с ними.

Запуск один раз:
    python scripts/archive_migrations/delete_regulations_39_40.py [путь_к_базе]
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.services.audit_service import log_action

DB = sys.argv[1] if len(sys.argv) > 1 else "factory.db"
DOOMED = (39, 40)


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = [dict(r) for r in cur.execute(
        "SELECT id, product_type, name, version, status FROM regulations "
        f"WHERE id IN {DOOMED}")]
    if not rows:
        print("Регламентов №39 и №40 в базе нет — удалять нечего.")
        return

    # ── Внешние ссылки: всё, что указывает на них ИЗВНЕ этой пары ───
    outside = []

    acks = cur.execute(
        f"SELECT COUNT(*) FROM regulation_ack WHERE regulation_id IN {DOOMED}").fetchone()[0]
    if acks:
        outside.append(f"подписей об ознакомлении: {acks}")

    measured = cur.execute(
        f"SELECT COUNT(*) FROM measurements WHERE regulation_id IN {DOOMED}").fetchone()[0]
    if measured:
        outside.append(f"замеров по этим нормам: {measured}")

    replaced = cur.execute(
        f"SELECT COUNT(*) FROM regulations WHERE replaced_by IN {DOOMED} "
        f"AND id NOT IN {DOOMED}").fetchone()[0]
    if replaced:
        outside.append(f"другие версии считают их заменой: {replaced}")

    inherited = cur.execute(
        "SELECT COUNT(*) FROM regulation_parameters WHERE source_parameter_id IN "
        f"(SELECT id FROM regulation_parameters WHERE regulation_id IN {DOOMED}) "
        f"AND regulation_id NOT IN {DOOMED}").fetchone()[0]
    if inherited:
        outside.append(f"параметры других версий наследуют их: {inherited}")

    if outside:
        print("НЕ УДАЛЯЮ — на эти регламенты ссылаются:")
        for line in outside:
            print("  •", line)
        print("\nСсылки надо показать человеку и решить с ним, а не удалять каскадом.")
        return

    # ── Что уходит вместе с ними ────────────────────────────────────
    stages = cur.execute(
        f"SELECT COUNT(*) FROM regulation_stages WHERE regulation_id IN {DOOMED}").fetchone()[0]
    params = cur.execute(
        f"SELECT COUNT(*) FROM regulation_parameters WHERE regulation_id IN {DOOMED}").fetchone()[0]
    changes = cur.execute(
        f"SELECT COUNT(*) FROM regulation_changes WHERE regulation_id IN {DOOMED}").fetchone()[0]

    print("Внешних ссылок нет. Удаляю:")
    for row in rows:
        print(f"  №{row['id']} · {row['product_type']} · {row['name']} · "
              f"версия {row['version']} · {row['status']}")
    print(f"  вместе с ними: этапов {stages}, параметров {params}, записей истории {changes}")

    cur.execute(f"DELETE FROM regulation_stage_equipment WHERE regulation_id IN {DOOMED}")
    cur.execute(f"DELETE FROM regulation_parameters WHERE regulation_id IN {DOOMED}")
    cur.execute(f"DELETE FROM regulation_stages WHERE regulation_id IN {DOOMED}")
    cur.execute(f"DELETE FROM regulation_changes WHERE regulation_id IN {DOOMED}")
    cur.execute(f"DELETE FROM regulations WHERE id IN {DOOMED}")
    conn.commit()

    left = cur.execute(
        f"SELECT COUNT(*) FROM regulations WHERE id IN {DOOMED}").fetchone()[0]
    total = cur.execute("SELECT COUNT(*) FROM regulations").fetchone()[0]
    conn.close()

    # ── Запись в журнал изменений ───────────────────────────────────
    for row in rows:
        log_action(
            username="Техническая учётная запись",
            role="admin",
            action="regulation_permanently_deleted",
            target=f"regulation:{row['id']}",
            details=(f"{row['product_type']} · {row['name']} · версия {row['version']} "
                     f"({row['status']}). Удалён по решению владельца 25.09.2026, "
                     f"согласовано с технологом: поля «вид» и «название» были "
                     f"перепутаны при создании, содержимого нет. "
                     f"Копия базы: backups/factory_before_migration_20260925_1043.db"),
        )

    print(f"\nУдалено. Осталось в базе: {left} из этих двух, регламентов всего {total}.")
    print("Запись в журнал изменений сделана по каждому.")


if __name__ == "__main__":
    main()
