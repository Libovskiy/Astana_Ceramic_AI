"""
Надиктовка: голос -> текст.

Рабочий у станка в перчатках печатать не будет, а описать поломку
голосом — «пресс гудит и не набирает давление» — может. Браузер
записывает звук, сюда приходит файл, OpenAI превращает его в текст,
текст подставляется в поле ввода. Отправляет человек сам, прочитав:
распознавание ошибается на названиях станков, и уйти в обращение
должно то, что он подтвердил.

Звук на сервере не хранится — только в памяти на время распознавания.
"""

from fastapi import APIRouter, Cookie, Depends, File, HTTPException, UploadFile

from backend.services.auth_service import get_user_by_session
from backend.services.rate_limit_service import check_rate_limit

router = APIRouter(prefix="/api/voice", tags=["voice"])

# Минута речи в webm/opus — около полумегабайта; 15 МБ хватит с запасом
# даже на несжатый wav с телефона.
MAX_BYTES = 15 * 1024 * 1024

# Подсказка распознаванию: без неё «PL024» превращается в «пи эль ноль
# двадцать четыре», а «вальцы» — в «вальсы».
PROMPT = (
    "Завод керамического кирпича Astana Ceramic. Оборудование: вальцы, "
    "дезинтегратор, дробилка, экструдер, резчик, вагонетка, туннельная "
    "печь, сушилка, питатель PL024, KP-10, робот FANUC, упаковочная машина. "
    "Ошибка A102, подшипник, редуктор, ремень, частотник."
)


def current_user(session_token: str | None = Cookie(default=None)):
    user = get_user_by_session(session_token)
    if user is None:
        raise HTTPException(status_code=401, detail="Не авторизован.")
    return user


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...), user: dict = Depends(current_user)):

    if not check_rate_limit(f"voice:{user['id']}"):
        raise HTTPException(status_code=429, detail="Слишком часто. Подождите минуту.")

    from backend.services.ai_service import client

    if client is None:
        raise HTTPException(status_code=503, detail="Распознавание речи не настроено (нет ключа OpenAI).")

    data = await file.read(MAX_BYTES + 1)

    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="Запись слишком длинная — не больше пары минут.")

    if len(data) < 1000:
        raise HTTPException(status_code=400, detail="Запись пустая — проверьте микрофон.")

    name = file.filename or "voice.webm"

    last_error = None

    # Основная модель точнее на шумной записи; whisper-1 — запасная,
    # если на ключе нет доступа к первой.
    for model in ("gpt-4o-mini-transcribe", "whisper-1"):
        try:
            result = client.audio.transcriptions.create(
                model=model,
                file=(name, data, file.content_type or "audio/webm"),
                language="ru",
                prompt=PROMPT,
            )
            text = (getattr(result, "text", "") or "").strip()
            return {"success": True, "text": text}
        except Exception as error:
            last_error = error
            print(f"[voice] {model}: {error}")

    raise HTTPException(status_code=502, detail="Не удалось распознать речь. Попробуйте ещё раз или напишите текстом.")
