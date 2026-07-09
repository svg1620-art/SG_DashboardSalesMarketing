-- DashboardSales&Marketing — начальная схема БД (Stage 1)
-- Источник правды — база данных. Все таблицы из ТЗ §8.

-- Пользователи приложения
CREATE TABLE IF NOT EXISTS app_users (
    id            SERIAL PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin', 'marketer', 'viewer')),
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Статусы воронки amoCRM и их сопоставление этапам воронки (§3)
CREATE TABLE IF NOT EXISTS pipeline_statuses (
    status_id    BIGINT PRIMARY KEY,
    pipeline_id  BIGINT,
    name         TEXT NOT NULL,
    sort_order   INTEGER NOT NULL DEFAULT 0,
    mapped_stage TEXT NOT NULL DEFAULT 'none'
        CHECK (mapped_stage IN ('mql', 'sql', 'meeting_scheduled',
                                'meeting_held', 'invoiced', 'won', 'lost', 'none'))
);

-- Менеджеры (пользователи amoCRM)
CREATE TABLE IF NOT EXISTS managers (
    amo_user_id BIGINT PRIMARY KEY,
    name        TEXT NOT NULL,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE
);

-- Источники (объединение источников из сделок и ручных затрат)
CREATE TABLE IF NOT EXISTS sources (
    id        SERIAL PRIMARY KEY,
    name      TEXT NOT NULL UNIQUE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- Сделки из amoCRM
CREATE TABLE IF NOT EXISTS deals (
    amo_lead_id        BIGINT PRIMARY KEY,
    pipeline_id        BIGINT,
    current_status_id  BIGINT,
    responsible_user_id BIGINT,
    source             TEXT,
    price              NUMERIC(14, 2),
    created_at         TIMESTAMPTZ,
    closed_at          TIMESTAMPTZ,
    is_won             BOOLEAN NOT NULL DEFAULT FALSE,
    is_lost            BOOLEAN NOT NULL DEFAULT FALSE,
    client_type        TEXT,
    monthly_payment    NUMERIC(14, 2),
    sum_platform       NUMERIC(14, 2),
    sum_implementation NUMERIC(14, 2),
    sum_manager        NUMERIC(14, 2),
    sum_courses        NUMERIC(14, 2),
    license_months     INTEGER,
    max_stage_reached  INTEGER NOT NULL DEFAULT 0,
    reached_mql        BOOLEAN NOT NULL DEFAULT FALSE,
    reached_sql        BOOLEAN NOT NULL DEFAULT FALSE,
    meeting_scheduled  BOOLEAN NOT NULL DEFAULT FALSE,
    meeting_held       BOOLEAN NOT NULL DEFAULT FALSE,
    invoiced           BOOLEAN NOT NULL DEFAULT FALSE,
    sold               BOOLEAN NOT NULL DEFAULT FALSE,
    stage_source       TEXT NOT NULL DEFAULT 'events'
        CHECK (stage_source IN ('events', 'fallback')),
    synced_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw                JSONB
);

CREATE INDEX IF NOT EXISTS idx_deals_created_at ON deals (created_at);
CREATE INDEX IF NOT EXISTS idx_deals_source ON deals (source);
CREATE INDEX IF NOT EXISTS idx_deals_responsible ON deals (responsible_user_id);

-- История смены статусов сделок
CREATE TABLE IF NOT EXISTS deal_stage_history (
    id           SERIAL PRIMARY KEY,
    amo_lead_id  BIGINT NOT NULL,
    status_id    BIGINT,
    mapped_stage TEXT,
    changed_at   TIMESTAMPTZ,
    UNIQUE (amo_lead_id, status_id, changed_at)
);

CREATE INDEX IF NOT EXISTS idx_stage_history_lead ON deal_stage_history (amo_lead_id);

-- Затраты и касания (ручной ввод)
CREATE TABLE IF NOT EXISTS costs_touches (
    id           SERIAL PRIMARY KEY,
    period_month DATE NOT NULL,
    source       TEXT NOT NULL,
    amount       NUMERIC(14, 2) NOT NULL DEFAULT 0,
    touches      INTEGER NOT NULL DEFAULT 0,
    comment      TEXT,
    created_by   INTEGER REFERENCES app_users (id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (period_month, source)
);

-- Журнал синхронизаций
CREATE TABLE IF NOT EXISTS sync_log (
    id            SERIAL PRIMARY KEY,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    deals_synced  INTEGER NOT NULL DEFAULT 0,
    events_synced INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'error', 'running')),
    message       TEXT
);
