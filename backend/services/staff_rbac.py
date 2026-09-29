"""
Кто чьи учётные записи может вести.

ЗАЧЕМ. Раньше «Настройки» открывались только администратору: любая
мелочь вроде забытого пароля шла через него. На заводе это значит,
что электрик в ночную смену ждёт до утра. Владелец 22.09.2026 назвал
устройство прямо: у каждого начальника — свои подчинённые, и пароли
им меняет он сам.

ПРАВИЛА, по которым это построено:

  1. **Над собой — каждый.** Свой пароль меняет любой вошедший, это
     не привилегия.
  2. **Над подчинёнными — начальник.** Главный механик над слесарями,
     главный энергетик над электриками, начальник производства над
     начальниками смен, начальник смены над операторами.
  3. **Начальник смены — только над СВОЕЙ бригадой.** У бригады А
     свой начальник, у Б свой; чужих операторов он не ведёт. Это
     единственное место, где роли мало и нужна ещё и бригада.
  4. **Заводить, удалять и менять роли** — директор и администратор.
     Смена пароля — рабочая мелочь, смена роли — изменение прав, и
     давать её каждому начальнику нельзя. Главный инженер до
     29.09.2026 был в этом же кругу; владелец сузил: он ведёт всех
     людей завода и меняет им пароли, но учётку не заводит, не
     удаляет и роль не переназначает.

Список живёт здесь и только здесь. `users_routes` спрашивает у него,
страница «Настройки» — тоже: иначе кнопка появится там, где сервер
откажет, а это худший вид вранья в интерфейсе.
"""

# Кем командует роль. "*" — всеми.
SUBORDINATE_ROLES: dict[str, tuple[str, ...] | str] = {
    "admin": "*",
    "director": "*",
    "chief_engineer": "*",
    "production_chief": ("shift_supervisor",),
    "shift_supervisor": ("worker",),
    "chief_mechanic": ("mechanic",),
    "chief_electrician": ("electrician",),
}

# Роли, которые ведут только свою бригаду.
BRIGADE_BOUND = ("shift_supervisor",)

# Кто заводит, удаляет и меняет роли. Уже, чем круг тех, кто ведёт
# всех людей: вести — это пароли и сессии, а заводить и удалять —
# другой разговор.
FULL_ACCESS_ROLES = ("admin", "director")


def full_access(role: str) -> bool:
    """Заводит, удаляет и переназначает роли."""
    return role in FULL_ACCESS_ROLES


def leads_everyone(role: str) -> bool:
    """Ведёт всех людей завода: пароли и сессии кому угодно."""
    return SUBORDINATE_ROLES.get(role) == "*"


def sees_settings(role: str) -> bool:
    """Есть ли смысл показывать этой роли «Настройки»."""
    return role in SUBORDINATE_ROLES


def can_manage(actor: dict, target: dict) -> bool:
    """
    Может ли `actor` вести учётку `target`: сменить пароль, закрыть
    сессии. Не про смену роли — это отдельное право (`full_access`).
    """
    if not actor or not target:
        return False

    # Над собой — всегда. Свой пароль человек меняет сам.
    if actor.get("id") == target.get("id"):
        return True

    allowed = SUBORDINATE_ROLES.get(actor.get("role"))
    if allowed is None:
        return False
    if allowed == "*":
        return True

    if target.get("role") not in allowed:
        return False

    # Начальник смены отвечает за свою бригаду, а не за всех рабочих
    # завода. Если бригада не проставлена — не угадываем, отказываем:
    # лучше попросить главного инженера, чем дать лишнее.
    if actor.get("role") in BRIGADE_BOUND:
        mine = (actor.get("brigade") or "").strip()
        theirs = (target.get("brigade") or "").strip()
        return bool(mine) and mine == theirs

    return True


def manageable_users(actor: dict, users: list) -> list:
    """Из общего списка — те, кого этот человек действительно ведёт."""
    return [item for item in users if can_manage(actor, item)]


def scope_text(actor: dict) -> str:
    """
    Чьи учётки человек видит — словами, для заголовка страницы.

    Пустой список без объяснения читается как поломка, поэтому
    объясняем всегда, даже когда подчинённых нет.
    """
    role = (actor or {}).get("role")

    if leads_everyone(role):
        return "Все учётные записи завода"
    if role == "production_chief":
        return "Ваша учётная запись и начальники смен"
    if role == "shift_supervisor":
        brigade = (actor.get("brigade") or "").strip()
        return (f"Ваша учётная запись и операторы бригады {brigade}"
                if brigade else "Только ваша учётная запись: бригада не указана")
    if role == "chief_mechanic":
        return "Ваша учётная запись и слесари"
    if role == "chief_electrician":
        return "Ваша учётная запись и электрики"
    return "Только ваша учётная запись"
