# 03 — База данных

## Миграции

SQL-файлы в `migrations/`, применяются **по порядку имени**, учёт в таблице
`schema_migrations`. Раннер — `scripts/migrate.py` (idempotent, применяет только
непринятые). На Railway прогоняются автоматически при старте.

**Добавить миграцию:** создать `migrations/007_описание.sql`. При следующем
деплое применится автоматически. Не редактировать уже применённые файлы —
только новые.

| Файл | Содержимое |
|------|------------|
| `001_initial_schema.sql` | Все таблицы ТЗ §8 |
| `002_stage_mapping_seed.sql` | Флаг `is_excluded` + посев сопоставления статусов «Воронки1» |
| `003_monthly_costs.sql` | Таблица `monthly_costs` (ранняя версия — ЗП/налоги) |
| `004_monthly_costs_totals.sql` | Переход `monthly_costs` на прямые тоталы `cost_marketing`/`cost_sales` |
| `005_seed_monthly_costs.sql` | Посев исторических месячных затрат (из таблицы заказчика) |
| `006_seed_costs_touches.sql` | Посев рекламы по месяц×источник (лист «Затраты и касания») |

> Посевные миграции (005/006) заливают исторические данные один раз. Правки
> через UI сохраняются — миграция повторно не выполняется.

## Таблицы

### `app_users`
Пользователи и роли.
`id, email (uniq), password_hash, role (admin/marketer/viewer), is_active, created_at`.

### `pipeline_statuses`
Статусы воронок amoCRM и их сопоставление с этапами.
`status_id (PK), pipeline_id, name, sort_order, mapped_stage, is_excluded`.
`mapped_stage ∈ {mql, sql, meeting_scheduled, meeting_held, invoiced, won, lost, none}`.
Редактируется admin; синк НЕ перезатирает `mapped_stage`/`is_excluded`.

### `managers`
Ответственные из amoCRM. `amo_user_id (PK), name, is_active`.

### `sources`
Справочник источников (объединение значений из сделок). `id, name (uniq), is_active`.

### `deals`
Сделки — центральная таблица.
`amo_lead_id (PK), pipeline_id, current_status_id, responsible_user_id, source,
price, created_at, closed_at, is_won, is_lost, client_type, monthly_payment,
sum_platform, sum_implementation, sum_manager, sum_courses, license_months,
max_stage_reached, reached_mql, reached_sql, meeting_scheduled, meeting_held,
invoiced, sold (bool-флаги этапов), stage_source (events/fallback), synced_at,
raw (jsonb — сырой ответ amoCRM)`.

### `deal_stage_history`
История смены статусов (события `lead_status_changed`).
`id, amo_lead_id, status_id, mapped_stage, changed_at`
(уник. по `amo_lead_id, status_id, changed_at`).

### `costs_touches`
Реклама по источникам (ручной ввод).
`id, period_month (date, 1-е число), source, amount, touches, comment, created_by,
created_at, updated_at` (уник. по `period_month, source`).

### `monthly_costs`
Месячные тоталы затрат (ручной ввод).
`period_month (PK), cost_marketing, cost_sales, comment, created_by, updated_at`.
- `cost_marketing` — «Расходы на маркетинг» (уже включает рекламу и ЗП маркетинга).
- `cost_sales` — «Расходы на продажи» (ЗП продаж и налоги).

### `sync_log`
Журнал запусков синхронизации.
`id, started_at, finished_at, deals_synced, events_synced, status (ok/error/running),
message`.

### `schema_migrations`
Служебная — применённые миграции. Не трогать вручную.

## Связи и целостность

- `deals.responsible_user_id` → `managers.amo_user_id` (LEFT JOIN в метриках).
- `deals.current_status_id` → `pipeline_statuses.status_id`.
- `deal_stage_history.amo_lead_id` → `deals.amo_lead_id` (удаляются вместе при сверке).
- Источники в метриках матчатся по строке `deals.source` = `costs_touches.source`
  (имена рекламных кампаний и лид-источников могут различаться — см. док. 05, 10).
