"""
Замена расплывчатых отсылок «по регламенту» на конкретные действия.

Зачем. Решение вида «выполнить поиск нуля по регламенту» бесполезно
рабочему у станка: он и так знает, что надо по регламенту, ему нужно
знать ЧТО НАЖАТЬ. Тем более что ремонтных регламентов в системе нет —
таблица procedures пуста, а regulations это технологические параметры
производства (температуры, влажность), не порядок ремонта. То есть
отсылка вела в пустоту.

Где конкретное значение объективно зависит от узла (усилие натяжения
струны), текст прямо говорит, где его взять, а не прячется за словом
«регламент».

Запуск (из корня проекта):
    python scripts/knowledge/fix_vague_plc_solutions.py           # просмотр
    python scripts/knowledge/fix_vague_plc_solutions.py --write   # записать
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))

import sys

from backend.services.plc_error_service import _conn, init_plc_error_table

AUTHOR = "ACAI (типовой алгоритм)"

HOME_STEPS = (
    "перевести участок в ручной режим на панели, снять аварию, выбрать на экране этого механизма "
    "команду поиска нуля (Home / поиск базы) и дождаться, пока механизм сам дойдёт до датчика Home "
    "и счётчик обнулится; если механизм стоит за датчиком — сначала отвести его назад вручную"
)

# (что заменить, на что заменить)
REPLACEMENTS: list[tuple[str, str]] = [
    (
        "1) Выполнить поиск нуля (Home) механизма по регламенту — счётчик переполнился и потерял привязку.",
        f"1) Счётчик переполнился и потерял привязку — выполнить поиск нуля: {HOME_STEPS}.",
    ),
    (
        "3) Вернуть механизм в исходное положение и выполнить поиск нуля (Home) по регламенту.",
        f"3) Вернуть механизм в исходное положение и выполнить поиск нуля: {HOME_STEPS}.",
    ),
    (
        "1) Выполнить процедуру поиска Home по регламенту узла.",
        f"1) Выполнить поиск нуля: {HOME_STEPS}.",
    ),
    (
        "1) Выполнить процедуру калибровки/поиска нуля по регламенту узла.",
        f"1) Выполнить калибровку через поиск нуля: {HOME_STEPS}.",
    ),
    (
        "3) Поставить новую струну и выставить натяжение по регламенту.",
        "3) Поставить новую струну и натянуть её до упругого звонкого отклика, без провисания. "
        "Конкретное усилие — по паспорту вашего резчика (руководство Beralmar, раздел по резчику); "
        "если гл. электрик вписал сюда значение — держаться его. Провисшая струна даёт косой рез, "
        "перетянутая рвётся на первом же брусе.",
    ),
    (
        "3) Перезапустить по регламенту.",
        "3) Перезапустить контроллер: остановить линию, снять питание шкафа управления вводным "
        "выключателем, выждать 30 секунд, подать питание и дождаться полной загрузки PLC.",
    ),
    (
        "2) Снять и подать питание на устройство по регламенту.",
        "2) Снять питание с устройства его автоматом в шкафу, выждать 30 секунд, подать снова.",
    ),
]


def main():
    write = "--write" in sys.argv

    init_plc_error_table()
    conn = _conn()

    rows = conn.execute(
        "SELECT id, code, solution, updated_by FROM plc_error_codes WHERE is_active=1 AND solution LIKE '%по регламенту%'"
    ).fetchall()

    changed = 0
    untouched_human = 0
    leftovers = []

    for row in rows:
        # Текст, который вписал человек, не трогаем — он мог сослаться
        # на реальный заводской регламент осознанно.
        if (row["updated_by"] or "") != AUTHOR:
            untouched_human += 1
            continue

        text = row["solution"]
        for old, new in REPLACEMENTS:
            text = text.replace(old, new)

        if text == row["solution"]:
            leftovers.append((row["code"], row["solution"]))
            continue

        changed += 1
        if write:
            conn.execute(
                "UPDATE plc_error_codes SET solution=?, updated_at=datetime('now') WHERE id=?",
                (text, row["id"]),
            )

    if write:
        conn.commit()

    print(f"Решений с «по регламенту»: {len(rows)}")
    print(f"{'Исправлено' if write else 'Будет исправлено'}: {changed}")
    print(f"Не тронуто (текст человека): {untouched_human}")

    if leftovers:
        print(f"Не подошло ни под одну замену: {len(leftovers)}")
        for code, text in leftovers:
            print(f"   {code}: ...{text[max(0, text.find('по регламенту') - 60):][:110]}")

    # Контроль: сколько осталось после замены
    remaining = conn.execute(
        "SELECT COUNT(*) FROM plc_error_codes WHERE is_active=1 AND solution LIKE '%по регламенту%'"
    ).fetchone()[0]
    print(f"Осталось с «по регламенту» в базе: {remaining}")

    if not write:
        print("\nЭто просмотр — ничего не записано. Для записи: --write")

    conn.close()


if __name__ == "__main__":
    main()
