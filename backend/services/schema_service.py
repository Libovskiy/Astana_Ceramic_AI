"""
Приведение базы к текущей схеме — в одном месте.

Раньше все init_* вызывались только при запуске сервера в main.py. Из-за
этого восстановление из вчерашней копии ломало сайт: в старой базе нет
колонок и таблиц, которые появились позже (нашли на учении
tests/test_restore.py — после восстановления всё падало на
`no such column: cases.is_test`).

Теперь то же самое зовётся и при запуске, и сразу после восстановления
из бэкапа. Все init_* безопасно повторяемы: CREATE TABLE IF NOT EXISTS и
ALTER TABLE только при отсутствии колонки.
"""


def ensure_schema() -> None:
    from backend.services.equipment_service import init_equipment
    from backend.services.case_service import init_cases_tables
    from backend.services.auth_service import init_auth_tables
    from backend.services.knowledge_service import init_knowledge_base
    from backend.services.mix_service import init_mix_table
    from backend.services.audit_service import init_audit_table
    from backend.services.production_log_service import init_production_tables
    from backend.services.downtime_service import init_downtime_table
    from backend.services.procedures_service import init_procedures_tables
    from backend.services.regulation_service import init_regulation_extensions
    from backend.services.task_service import init_task_tables
    from backend.services.plc_error_service import init_plc_error_table
    from backend.services.protection_service import init_protection_tables
    from backend.services.shift_report_service import init_shift_report_tables
    from backend.services.team_chat_service import init_team_chat
    from backend.services.equipment_state_service import init_state_events
    from backend.services.usage_service import init_usage
    from backend.services.push_service import init_push
    from backend.services.observation_service import init_observation

    steps = (
        init_equipment, init_cases_tables, init_auth_tables, init_knowledge_base,
        init_mix_table, init_audit_table, init_production_tables, init_downtime_table,
        init_procedures_tables, init_regulation_extensions, init_task_tables,
        init_plc_error_table, init_protection_tables, init_shift_report_tables,
        init_team_chat, init_state_events, init_usage, init_push, init_observation,
    )

    for step in steps:
        try:
            step()
        except Exception as error:
            # одна отставшая таблица не должна мешать остальным
            print(f"[schema] {step.__name__}: {error}")
