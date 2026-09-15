"""
Keyword-детектор станка для /chat (свободный текст без выбора
станка из списка). Для /diagnose не используется — там станок
выбран явно.

Правка: DOCS_ROOT берётся из config (был относительный
Path("docs/Machines") — зависел от рабочей директории процесса).
"""

from backend.config import DOCS_MACHINES_PATH

DOCS_ROOT = DOCS_MACHINES_PATH

# Пока простая база ключевых слов.
# Потом заменим на GPT.
MACHINES = {
    "messersi": {
        "keywords": [
            "пленка",
            "обмотка",
            "упаковка",
            "стретч",
            "stretch"
        ],
        "folder": DOCS_ROOT / "Messersi"
    },

    "fanuc_loader": {
        "keywords": [
            "робот",
            "кирпич",
            "паллет",
            "палета",
            "захват"
        ],
        "folder": DOCS_ROOT / "Fanuc"
    }
}


def _normalize(text: str) -> str:
    """
    "ё" и "е" — разные символы для Python, но одно и то же слово
    для человека ("плёнка" / "пленка"). Приводим оба варианта
    к одному виду перед сравнением ключевых слов, иначе поиск
    молча не находит совпадение.
    """

    return text.lower().replace("ё", "е")


def detect_machine(text: str):

    text = _normalize(text)

    for machine, info in MACHINES.items():

        for keyword in info["keywords"]:

            if _normalize(keyword) in text:

                return {
                    "machine": machine,
                    "folder": str(info["folder"])
                }

    return None
