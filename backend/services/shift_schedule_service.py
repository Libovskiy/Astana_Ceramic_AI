"""
График смен: кто работает прямо сейчас.

Зачем: раньше смену ("День"/"Ночь") человек выбирал руками в
выпадающем списке. На практике это значит, что в 23:40 уставший
оператор оставит "День", и весь учёт выпуска за ночь уедет не в ту
смену. Теперь смена и бригада вычисляются от даты и времени, а
человек ничего не выбирает.

РЕЖИМ РАБОТЫ
    День:  09:00 - 21:00
    Ночь:  21:00 - 09:00 следующих суток

Ночная смена, начавшаяся в 21:00 понедельника, ЦЕЛИКОМ относится к
понедельнику — включая часы после полуночи. Иначе выпуск одной
смены разрезался бы полуночью на два дня, и сравнивать смены между
собой стало бы невозможно.

БРИГАДЫ
    Четыре бригады: А, Б, В, Г. Цикл 4 суток:

        1-е сутки — дневная смена (09:00-21:00)
        2-е сутки — ночная смена (21:00-09:00)
        3-и сутки — выходной (начинается сразу после ночной,
                    как только человек сдал смену в 9 утра)
        4-е сутки — выходной

    Отдых после ночной получается двое полных суток: с 09:00
    третьего дня до 09:00 пятого, когда бригада снова выходит в
    день.

    Бригады сдвинуты друг относительно друга на сутки, поэтому в
    любой день ровно одна бригада в дне и ровно одна в ночи —
    четвёртая нужна именно для этого.

    Если график изменится — меняется ТОЛЬКО таблица ROTATION ниже,
    остальной код трогать не нужно.
"""

from datetime import datetime, timedelta, date


DAY_START_HOUR = 9
NIGHT_START_HOUR = 21

SHIFT_DAY = "День"
SHIFT_NIGHT = "Ночь"

BRIGADES = ("А", "Б", "В", "Г")

# Дата, с которой считается цикл. В этот день бригада А выходит
# в первый дневной день своего цикла.
CYCLE_START = date(2026, 8, 24)

# Цикл на 4 суток. Индекс — номер дня в цикле.
#   "Д" — дневная смена, "Н" — ночная, "-" — выходной
ROTATION = {
    "А": ["Д", "Н", "-", "-"],
    "Б": ["-", "Д", "Н", "-"],
    "В": ["-", "-", "Д", "Н"],
    "Г": ["Н", "-", "-", "Д"],
}

CYCLE_LENGTH = 4


def get_shift_at(moment: datetime | None = None):
    """
    Какая смена идёт в этот момент.

    Возвращает:
        {
          "shift": "День" | "Ночь",
          "shift_date": "2026-08-24",   # сутки, к которым отнесён выпуск
          "brigade": "А",
          "started_at": datetime,
          "ends_at": datetime,
          "minutes_left": 145
        }

    shift_date для ночной смены — дата её НАЧАЛА, даже если сейчас
    уже за полночь.
    """

    moment = moment or datetime.now()

    if DAY_START_HOUR <= moment.hour < NIGHT_START_HOUR:

        shift = SHIFT_DAY
        shift_day = moment.date()
        started_at = moment.replace(hour=DAY_START_HOUR, minute=0, second=0, microsecond=0)
        ends_at = moment.replace(hour=NIGHT_START_HOUR, minute=0, second=0, microsecond=0)

    else:

        shift = SHIFT_NIGHT

        if moment.hour >= NIGHT_START_HOUR:
            # Вечер: смена началась сегодня
            shift_day = moment.date()
            started_at = moment.replace(hour=NIGHT_START_HOUR, minute=0, second=0, microsecond=0)
            ends_at = started_at + timedelta(hours=12)
        else:
            # Ночь после полуночи: смена началась вчера
            shift_day = moment.date() - timedelta(days=1)
            started_at = datetime.combine(shift_day, datetime.min.time()).replace(hour=NIGHT_START_HOUR)
            ends_at = started_at + timedelta(hours=12)

    return {
        "shift": shift,
        "shift_date": shift_day.strftime("%Y-%m-%d"),
        "brigade": get_brigade(shift_day, shift),
        "started_at": started_at,
        "ends_at": ends_at,
        "minutes_left": max(round((ends_at - moment).total_seconds() / 60), 0)
    }


def get_brigade(shift_day: date, shift: str):
    """Какая бригада выходит в эту смену этих суток."""

    offset = (shift_day - CYCLE_START).days % CYCLE_LENGTH

    mark = "Д" if shift == SHIFT_DAY else "Н"

    for brigade, pattern in ROTATION.items():
        if pattern[offset] == mark:
            return brigade

    return None


def get_day_schedule(shift_day: date | None = None):
    """Кто работает в эти сутки: день и ночь."""

    shift_day = shift_day or datetime.now().date()

    return {
        "date": shift_day.strftime("%Y-%m-%d"),
        "day": get_brigade(shift_day, SHIFT_DAY),
        "night": get_brigade(shift_day, SHIFT_NIGHT)
    }


def get_month_schedule(year: int, month: int):
    """Табель на месяц — для проверки глазами и печати."""

    import calendar

    days = calendar.monthrange(year, month)[1]

    return [
        get_day_schedule(date(year, month, day))
        for day in range(1, days + 1)
    ]


def is_working_now(brigade: str, moment: datetime | None = None) -> bool:
    """Работает ли эта бригада прямо сейчас."""

    return get_shift_at(moment)["brigade"] == brigade


if __name__ == "__main__":

    now = get_shift_at()

    print(f"Сейчас:      {now['shift']} смена, бригада {now['brigade']}")
    print(f"Учёт за:     {now['shift_date']}")
    print(f"Начало:      {now['started_at'].strftime('%d.%m %H:%M')}")
    print(f"Конец:       {now['ends_at'].strftime('%d.%m %H:%M')}")
    print(f"Осталось:    {now['minutes_left']} мин\n")

    print("Ближайшие 10 суток:")
    print(f"{'дата':<12} {'день':<6} {'ночь':<6}")

    for offset in range(10):
        day = datetime.now().date() + timedelta(days=offset)
        item = get_day_schedule(day)
        print(f"{item['date']:<12} {item['day'] or '—':<6} {item['night'] or '—':<6}")
