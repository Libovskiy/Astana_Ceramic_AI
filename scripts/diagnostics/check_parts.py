"""
Сверка списка деталей: сколько было, сколько стало.

ЗАЧЕМ. 21.09.2026 правка словаря («цеп» ловил «цепной стол») починила
пересчёт втрое — и молча потеряла подшипники: правильное написание
встречается 6 раз, а со всеми вариантами 28. Общее число деталей после
правки тоже упало, поэтому падение одной строки в нём не читалось.

Отсюда правило: после КАЖДОЙ правки словаря сверяем по каждой детали
отдельно, а любое изменение больше чем вдвое объясняем вслух. Проверка
смотрит и вниз, и вверх: потерять деталь так же плохо, как насчитать
лишнего.

    python scripts/diagnostics/check_parts.py          # сверить
    python scripts/diagnostics/check_parts.py --save   # принять как новую норму

Выход 1 — если что-то изменилось сильнее чем вдвое или исчезло.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.chdir(Path(__file__).resolve().parents[2])

from backend.services.production_import_service import PART_ROOTS, parts_mentioned

BASELINE = Path(__file__).with_name("parts_baseline.json")
LIMIT = 99


def counts() -> dict:
    return {item["part"]: item["cases"] for item in parts_mentioned(limit=LIMIT)}


def main() -> int:
    now = counts()
    save = "--save" in sys.argv

    if not BASELINE.exists():
        BASELINE.write_text(json.dumps(now, ensure_ascii=False, indent=1) + "\n")
        print(f"Снимок создан: {BASELINE.name}, деталей {len(now)}.")
        return 0

    was = json.loads(BASELINE.read_text())
    names = sorted(set(was) | set(now), key=lambda name: -now.get(name, 0))

    problems = []
    print(f"{'деталь':24} было  стало")
    for name in names:
        before, after = was.get(name, 0), now.get(name, 0)
        mark = ""
        if before and not after:
            mark = "ПРОПАЛА — объясните, куда"
        elif after and not before:
            mark = "новая"
        elif before and after:
            change = after / before if after > before else before / after
            if change >= 2:
                mark = f"изменилось в {change:.1f} раза — объясните"
        if "объясните" in mark:
            problems.append(f"{name}: было {before}, стало {after}")
        print(f"{name:24} {before:4d}  {after:5d}  {mark}")

    if not now:
        print("\nВ отчёте нет записей — сверять не с чем.")
        return 0

    if save:
        BASELINE.write_text(json.dumps(now, ensure_ascii=False, indent=1) + "\n")
        print("\nСнимок обновлён — эти числа теперь считаются нормой.")
        return 0

    if problems:
        print("\nНужно объяснить:")
        for line in problems:
            print("  •", line)
        print("Если изменение правильное — запустите с --save.")
        return 1

    print(f"\nВсё сходится: {len(now)} деталей из {len(PART_ROOTS)} в словаре.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
