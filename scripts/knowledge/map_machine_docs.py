#!/usr/bin/env python3
"""
Строит карту «станок → папка с документацией».

Зачем. Поиск привязывает станок к папке по совпадению слов. Но в базе
станок называется «Дезинтегратор PL 601», а папка — «2.ДЕЗИНТИГРАТОР
PL601-08»: через «и», с номером и без пробела. Слова не совпадают,
совпадений ноль, и система берёт документацию наугад — так дезинтегратору
достался паспорт питателя.

Опечатки в словах неизбежны, а вот номер модели пишут одинаково:
PL601, PL024, DTE117, СМК126, УСМ40. По нему и сопоставляем.

    cd /Users/champ_01/Documents/FactoryAssistant
    python3 map_machine_docs.py            # показать предложения
    python3 map_machine_docs.py --apply    # записать в config.py
"""
import argparse
import re
import shutil
import sqlite3
import sys
import unicodedata
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DOCS = BASE_DIR / "docs"
DB = BASE_DIR / "factory.db"
CONFIG = BASE_DIR / "backend" / "config.py"


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", str(text or "")).lower()
    # ё→е и и→е: «дезинтигратор» и «дезинтегратор» должны сойтись
    return text.replace("ё", "е")


def model_keys(text: str) -> set:
    """
    Номера моделей в устойчивом виде: PL 601 → pl601, PL601-08 → pl601,
    СМК 126 → смк126, УСМ 40 → усм40. Суффиксы после дефиса отбрасываем:
    в базе станок «PL 601», в папке «PL601-08» — это одно и то же.
    """
    t = normalize(text)
    keys = set()

    # буквенный префикс + число: pl601, dte117, смк126, усм40, optima800
    for match in re.finditer(r"([a-zа-я]{2,10})[\s\-_]*([0-9]{2,4})", t):
        keys.add(match.group(1) + match.group(2))

    # отдельно стоящие номера от трёх знаков: 575, 117, 126
    for match in re.finditer(r"\b([0-9]{3,4})\b", t):
        keys.add(match.group(1))

    return keys


def leaf_folders():
    """Папки, в которых лежат PDF напрямую."""
    out = []
    for path in sorted(DOCS.rglob("*")):
        if not path.is_dir():
            continue
        if "uploads" in path.parts:
            continue
        if any(child.suffix.lower() == ".pdf" for child in path.iterdir() if child.is_file()):
            out.append(path)
    return out


def equipment_names():
    if not DB.exists():
        print("✗ factory.db не найдена")
        sys.exit(1)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT name FROM equipment WHERE COALESCE(level,'') != 'component' ORDER BY name"
    ).fetchall()
    conn.close()
    return [r["name"] for r in rows if r["name"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="записать карту в config.py")
    args = ap.parse_args()

    folders = leaf_folders()
    machines = equipment_names()

    print(f"Станков в базе:        {len(machines)}")
    print(f"Папок с документами:   {len(folders)}\n")
    print("=" * 78)

    mapping = {}
    unmatched = []

    for machine in machines:
        keys = model_keys(machine)
        if not keys:
            unmatched.append((machine, "нет номера модели в названии"))
            continue

        hits = []
        for folder in folders:
            common = keys & model_keys(folder.name)
            if common:
                hits.append((len(common), folder))

        if not hits:
            unmatched.append((machine, f"номер {', '.join(sorted(keys))} не найден ни в одной папке"))
            continue

        hits.sort(key=lambda x: -x[0])
        best = [f for _, f in hits]

        mapping[normalize(machine)] = [f.name for f in best[:3]]

        print(f"\n{machine}")
        for folder in best[:3]:
            print(f"    → {folder.relative_to(DOCS)}")

    print("\n" + "=" * 78)
    print(f"Сопоставлено: {len(mapping)}")

    if unmatched:
        print(f"\nБез документации ({len(unmatched)}):")
        for machine, reason in unmatched[:20]:
            print(f"  {machine} — {reason}")
        if len(unmatched) > 20:
            print(f"  ... и ещё {len(unmatched) - 20}")
        print("\nЭто не ошибка: у части станков документации может не быть.")

    if not args.apply:
        print("\nЭто предпросмотр. Проверьте пары выше.")
        print("Если верно — python3 map_machine_docs.py --apply")
        return

    text = CONFIG.read_text(encoding="utf-8")

    lines = ["MACHINE_DOCS_MAP = {"]
    lines.append("    # Собрано map_machine_docs.py по номерам моделей.")
    lines.append("    # В базе «Дезинтегратор PL 601», в папке «2.ДЕЗИНТИГРАТОР PL601-08» —")
    lines.append("    # слова расходятся, номер совпадает. Правьте руками, если что-то не так.")
    for key in sorted(mapping):
        value = ", ".join(f'"{v}"' for v in mapping[key])
        lines.append(f'    "{key}": [{value}],')
    lines.append("}")
    new_block = "\n".join(lines)

    if "MACHINE_DOCS_MAP = {}" in text:
        text = text.replace("MACHINE_DOCS_MAP = {}", new_block, 1)
    else:
        old = re.search(r"MACHINE_DOCS_MAP = \{.*?\n\}", text, re.S)
        if not old:
            print("✗ не нашёл MACHINE_DOCS_MAP в config.py")
            sys.exit(1)
        text = text[:old.start()] + new_block + text[old.end():]

    shutil.copy2(CONFIG, CONFIG.with_suffix(".py.bak-docsmap"))
    CONFIG.write_text(text, encoding="utf-8")
    print(f"\n✓ карта записана в config.py ({len(mapping)} станков)")
    print("  копия: backend/config.py.bak-docsmap")

    import py_compile
    try:
        py_compile.compile(str(CONFIG), doraise=True)
        print("✓ config.py компилируется")
    except Exception as error:
        print(f"✗ синтаксическая ошибка: {error}")
        sys.exit(1)

    print("\nДальше: очистить __pycache__ и перезапустить сервер.")


if __name__ == "__main__":
    main()
