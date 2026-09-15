"""
Диагностика документации: какие PDF реально дают текст, а какие
являются сканами и молча пропускаются при сборке базы знаний.

Ничего не меняет. Запуск: python check_docs.py
Разместить в корне проекта.

Зачем: build_knowledge_base берёт текст через page.get_text().
У скана (фотография страницы) текстового слоя нет, get_text()
возвращает пустоту, страница пропускается — и документ попадает в
базу как ноль кусков, без единой ошибки в логе. Внешне сборка
проходит успешно, а искать не по чему.
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))


import sys
from pathlib import Path

import fitz

from backend.config import DOCS_PATH, BASE_DIR
from backend.tools.text_chunker import split_text
from backend.tools.document_filter import is_useful


# Файлы из прежней базы знаний — проверяем, на месте ли они
PREVIOUS_DOCS = [
    "MESSERSI.pdf",
    "РЕДУКТОРЫ РЭ.pdf",
    "Нормы ТБ и Техобслуживания оборудовании  -BOSHAN.pdf",
    "ВАКУУМНЫЙ НАСОС.pdf",
    "HMI71 Manual Desapilado y Empaquetado - RU.pdf",
    "ШКАФ УПРАВЛЕНИЯ 1-ШУ1 Уголь РЭ.pdf",
    "ПИТАТЕЛЬ ЛЕНТОЧНЫЙ - PL05-2 ПАСПОРТ.pdf",
]


def analyse(pdf):

    doc = fitz.open(pdf)

    pages = doc.page_count
    chars = 0
    pages_with_text = 0
    chunks_total = 0
    chunks_kept = 0

    try:

        for page in doc:

            text = page.get_text()

            if text.strip():
                pages_with_text += 1
                chars += len(text)

                clean = " ".join(text.split())

                for chunk in split_text(clean):
                    chunks_total += 1
                    if is_useful(chunk):
                        chunks_kept += 1

    finally:
        doc.close()

    return {
        "pages": pages,
        "pages_with_text": pages_with_text,
        "chars": chars,
        "chunks_total": chunks_total,
        "chunks_kept": chunks_kept
    }


def main():

    if not DOCS_PATH.exists():
        print(f"Папка не найдена: {DOCS_PATH}")
        return

    pdfs = sorted(DOCS_PATH.rglob("*.pdf"))

    print(f"\nПапка документации: {DOCS_PATH}")
    print(f"Найдено PDF: {len(pdfs)}\n")

    scans = []
    filtered_out = []
    good = []
    broken = []

    print(f"{'документ':<52} {'стр':>5} {'с текстом':>10} {'кусков':>8}  вердикт")
    print("-" * 100)

    for pdf in pdfs:

        try:
            info = analyse(pdf)
        except Exception as error:
            broken.append((pdf, str(error)))
            print(f"{pdf.name[:50]:<52} {'?':>5} {'?':>10} {'?':>8}  НЕ ЧИТАЕТСЯ: {error}")
            continue

        name = pdf.name[:50]

        if info["pages_with_text"] == 0:
            verdict = "СКАН — нужен OCR"
            scans.append(pdf)
        elif info["chunks_kept"] == 0 and info["chunks_total"] > 0:
            verdict = "текст есть, но отсеян фильтром"
            filtered_out.append(pdf)
        else:
            verdict = "ок"
            good.append((pdf, info["chunks_kept"]))

        print(
            f"{name:<52} {info['pages']:>5} "
            f"{info['pages_with_text']:>10} {info['chunks_kept']:>8}  {verdict}"
        )

    # -----------------------------------------

    print("\n" + "=" * 100)
    print("ИТОГ")
    print("=" * 100)

    total_chunks = sum(count for _, count in good)

    print(f"  Пригодных документов:      {len(good)}  ({total_chunks} кусков попадёт в базу)")
    print(f"  Сканов без текста:         {len(scans)}")
    print(f"  Отсеяно фильтром:          {len(filtered_out)}")
    print(f"  Не читается:               {len(broken)}")

    if scans:
        print("\n  СКАНЫ (в базу знаний не попадут вообще):")
        for pdf in scans:
            print(f"    - {pdf.relative_to(DOCS_PATH)}")
        print(
            "\n    Такой файл — это картинки страниц. Чтобы по нему можно\n"
            "    было искать, нужен OCR (распознавание). Быстрый вариант:\n"
            "        brew install ocrmypdf tesseract-lang\n"
            "        ocrmypdf -l rus+eng вход.pdf выход.pdf\n"
            "    Либо запросить у поставщика электронные версии."
        )

    if filtered_out:
        print("\n  ОТСЕЯНО ФИЛЬТРОМ document_filter.is_useful:")
        for pdf in filtered_out:
            print(f"    - {pdf.relative_to(DOCS_PATH)}")

    # -----------------------------------------
    # Где старые документы
    # -----------------------------------------

    print("\n" + "=" * 100)
    print("ДОКУМЕНТЫ ИЗ ПРЕЖНЕЙ БАЗЫ ЗНАНИЙ")
    print("=" * 100)

    all_pdfs_in_project = {
        path.name: path
        for path in BASE_DIR.rglob("*.pdf")
    }

    missing = []

    for name in PREVIOUS_DOCS:

        path = all_pdfs_in_project.get(name)

        if path is None:
            print(f"  НЕ НАЙДЕН   {name}")
            missing.append(name)
        else:
            inside = DOCS_PATH in path.parents
            where = path.relative_to(BASE_DIR)
            mark = "в docs" if inside else "ВНЕ docs — не индексируется"
            print(f"  {mark:<28} {where}")

    if missing:
        print(
            f"\n  {len(missing)} документов пропали из проекта. Прежняя база\n"
            "  знаний (850 кусков) была собрана по ним — в том числе\n"
            "  302 куска по упаковочной машине, которая и есть ваш пилот.\n"
            "  Найдите эти файлы и положите обратно в docs/."
        )

    print()


if __name__ == "__main__":
    main()
