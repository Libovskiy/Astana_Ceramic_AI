"""
Кто что может делать с регламентами.

Здесь важна одна непривычная вещь: заместитель директора и главный
инженер НЕ могут менять технологические нормы. По должности они
выше технолога, по этому вопросу — нет.

Причина простая. Норма это профессиональное решение, за которое
отвечает технолог: он знает сырьё, он видит результаты обжига, он
отвечает за марку. Если норму может поменять руководитель «под
план», нормы перестают быть нормами и становятся пожеланиями. При
разборе брака выяснится, что зазор поменяли по звонку, а не по
расчёту, и виноватого не найти.

Технолог при этом меняет нормы САМ, без чужого утверждения — но
каждое изменение требует причины, создаёт новую версию и попадает
в журнал. Свобода и след одновременно.

Разместить: backend/services/regulation_rbac.py
"""


# =========================================================
# ЧТО МОЖНО ДЕЛАТЬ
# =========================================================

ACTIONS = {

    # Смотреть регламенты
    "regulation.view": (
        "technologist", "lab_technician",
        "chief_engineer", "director", "admin", "analyst", "engineer",
        "shift_supervisor",
        "chief_mechanic", "mechanic",
        "chief_electrician", "electrician",
        "worker",
    ),

    # Создать регламент на вид продукции
    "regulation.create": ("technologist", "lab_technician", "director", "admin"),

    # Изменить нормы — новая версия, обязательная причина.
    #
    # Директор здесь по решению заказчика: у него полный бизнес-
    # доступ. Главного инженера и зама нет — по должности они выше
    # технолога, по этому вопросу нет. Норма это профессиональное
    # решение, за которое отвечает технолог: он знает сырьё и
    # отвечает за марку. Если норму можно поменять "под план",
    # она перестаёт быть нормой.
    "regulation.edit": ("technologist", "lab_technician", "director", "admin"),

    # Ввести в действие: черновик становится рабочим
    "regulation.activate": ("technologist", "lab_technician", "director", "admin"),

    "regulation.archive": ("technologist", "lab_technician", "director", "admin"),

    # =====================================================
    # ЗАМЕРЫ
    # =====================================================

    # Внести факт руками
    "measurement.create": (
        "lab_technician", "technologist",
        "shift_supervisor", "engineer", "admin",
    ),

    "measurement.view": (
        "technologist", "lab_technician",
        "chief_engineer", "director", "admin", "analyst", "engineer",
        "shift_supervisor",
    ),

    # Правка внесённого замера. Лаборанта тут нет намеренно:
    # исправлять свой же замер задним числом — это способ
    # незаметно подогнать результат. Ошибся — вносит новый с
    # пометкой, старый остаётся.
    "measurement.edit": ("technologist", "director", "admin"),

    # =====================================================
    # ОБСЛУЖИВАНИЕ
    # =====================================================

    "maintenance.create": (
        "chief_mechanic", "chief_electrician",
        "chief_engineer", "admin",
    ),

    "maintenance.complete": (
        "mechanic", "chief_mechanic",
        "electrician", "chief_electrician",
        "chief_engineer", "admin",
    ),

    "maintenance.view": (
        "chief_mechanic", "mechanic",
        "chief_electrician", "electrician",
        "chief_engineer", "director", "admin",
        "shift_supervisor", "engineer", "analyst",
    ),

    # =====================================================
    # СТРУКТУРА ПРОИЗВОДСТВА
    # =====================================================

    # Главный инженер управляет структурой завода: этапами,
    # оборудованием, частями и документами. Это не даёт ему права
    # менять технологические нормы — для этого остаётся отдельное
    # regulation.edit.
    "structure.edit": (
        "chief_engineer", "technologist", "director", "admin",
        "chief_mechanic", "chief_electrician",
    ),

    # =====================================================
    # ДОКУМЕНТЫ ОБОРУДОВАНИЯ
    # =====================================================

    "document.attach": (
        "chief_mechanic", "chief_electrician",
        "chief_engineer", "technologist", "admin", "director",
    ),

    "document.approve": (
        "chief_engineer", "chief_mechanic", "technologist", "director", "admin",
    ),
}


# Пояснения для интерфейса: почему кнопки нет.
# Человек должен понимать, что это правило, а не поломка.
DENIED_REASON = {
    "regulation.edit": (
        "Технологические нормы меняет технолог. Это его "
        "профессиональная ответственность — если норму можно "
        "поменять решением руководителя, она перестаёт быть нормой."
    ),
    "regulation.create": "Создавать регламенты может технолог или лаборант.",
    "regulation.activate": "Вводить регламент в действие может технолог или лаборант.",
    "measurement.edit": (
        "Исправлять внесённый замер может технолог. Если ошиблись — "
        "внесите новый замер, старый останется в истории."
    ),
    "measurement.create": "Вносить замеры могут лаборант и технолог.",
    "maintenance.create": "Планы обслуживания заводят главный механик и главный электрик.",
    "structure.edit": (
        "Изменять структуру производства могут главный инженер, технолог, "
        "директор, главный механик и главный электрик."
    ),
}


def can(user, action: str) -> bool:

    if not user:
        return False

    allowed = ACTIONS.get(action)

    if allowed is None:
        # Неизвестное действие — запрещаем. Опечатка в названии не
        # должна открывать доступ всем.
        return False

    return user.get("role") in allowed


def why_denied(action: str) -> str:

    return DENIED_REASON.get(
        action,
        "У вашей роли нет доступа к этому действию."
    )


def permissions_for(user) -> dict:
    """
    Все права разом — фронтенду, чтобы не спрашивать по одному и
    не показывать кнопки, которые всё равно не сработают.
    """

    return {action: can(user, action) for action in ACTIONS}
