-- Stage 2: флаг исключения из воронки + посев сопоставления статусов «Воронки1».
-- Значения согласованы по данным /admin/amocrm-check (pipeline_id 3807).
-- Сопоставление далее редактируется admin; синхронизация его не перезатирает.

ALTER TABLE pipeline_statuses
    ADD COLUMN IF NOT EXISTS is_excluded BOOLEAN NOT NULL DEFAULT FALSE;

-- Вехи воронки (§3) + исключаемый «Дубль».
-- ON CONFLICT DO UPDATE выставляет дефолтную раскладку один раз (миграция
-- выполняется единожды), после чего правки admin сохраняются.
INSERT INTO pipeline_statuses (status_id, pipeline_id, name, sort_order, mapped_stage, is_excluded) VALUES
    (54616594, 3807, 'Назначена встреча',           80,    'meeting_scheduled', FALSE),
    (61608022, 3807, 'Не пришел на встречу',         90,    'meeting_scheduled', FALSE),
    (22319275, 3807, 'Проведена встреча',            100,   'meeting_held',      FALSE),
    (22319281, 3807, 'Выставлен счет',               120,   'invoiced',          FALSE),
    (142,      3807, 'Оплата получена',              10000, 'won',               FALSE),
    (143,      3807, 'Закрыто и не реализовано',     11000, 'lost',              FALSE),
    (79225914, 3807, 'Дубль',                        30,    'none',              TRUE)
ON CONFLICT (status_id) DO UPDATE
    SET pipeline_id  = EXCLUDED.pipeline_id,
        name         = EXCLUDED.name,
        sort_order   = EXCLUDED.sort_order,
        mapped_stage = EXCLUDED.mapped_stage,
        is_excluded  = EXCLUDED.is_excluded;
