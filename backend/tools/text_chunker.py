import re

CHUNK_SIZE = 1000


def split_text(text: str):

    # Убираем лишние пробелы
    text = re.sub(r"\s+", " ", text)

    # Делим по предложениям
    sentences = re.split(r"(?<=[.!?])\s+", text)

    chunks = []
    current = ""

    for sentence in sentences:

        if len(current) + len(sentence) < CHUNK_SIZE:

            current += sentence + " "

        else:

            chunks.append(current.strip())
            current = sentence + " "

    if current:
        chunks.append(current.strip())

    return chunks