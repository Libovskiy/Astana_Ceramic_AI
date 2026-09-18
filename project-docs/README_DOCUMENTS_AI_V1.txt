[Записка о доработке от 30.08.2026. Сверено с кодом 18.09.2026 — в силе, с поправками в конце файла]
[Как система устроена сейчас: AI_CONTEXT.md и README.md в корне проекта]

ACAI — Documents + Approval + AI ingestion V1

Что добавлено:
- Документы оборудования/частей/этапов имеют lifecycle: pending -> approved/rejected/archived.
- Технический документ становится доступным AI только после approved.
- После approved PDF автоматически ставится в фоновую индексацию Chroma.
- knowledge_status: blocked/pending/indexed/error.
- Ошибка AI-индексации не отменяет подтверждение; она видна в карточке документа.
- Audit фиксирует загрузку, подтверждение, отклонение и архивацию.
- Подтверждение доступно ролям из document.approve: главный механик, технолог, директор, admin.
- Для технолога/директора/admin загруженный документ авто-подтверждается по существующему правилу проекта.
- Остальные загрузчики получают статус «На проверке».
- Существующие файлы и factory.db не заменять.

Запуск:
python -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000

Миграция колонок выполняется при старте через init_regulation_extensions().

------------------------------------------------------------------
ЧТО ИЗМЕНИЛОСЬ К 18.09.2026

- Подтверждать документ может ещё и главный инженер: в коде список
  document.approve — chief_engineer, chief_mechanic, technologist,
  director, admin (backend/services/regulation_rbac.py).
- Загрузка документа к станку идёт двумя путями, оба рабочие:
  POST /api/equipment/{id}/documents/upload-b64  — со страницы
  «Оборудование» (роли: admin, director, chief_engineer,
  chief_mechanic, chief_electrician);
  POST /api/structure/equipment/{id}/documents   — из паспорта
  станка, право structure.edit.
- Схема базы приводится в порядок не в init_regulation_extensions(),
  а в одном месте: backend/services/schema_service.ensure_schema().
  Оно же зовётся после восстановления из бэкапа.
- Состояние индексации видно в интерфейсе: значок у документа берётся
  из /api/equipment/{id}/documents/status.
