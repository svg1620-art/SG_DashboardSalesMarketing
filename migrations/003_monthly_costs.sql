-- Stage 4/6: операционные затраты месяца для CAC (ЗП + налог на ФОТ).
-- Реклама берётся из costs_touches (авто), налог с оборота 6% — от выручки (авто).

CREATE TABLE IF NOT EXISTS monthly_costs (
    period_month     DATE PRIMARY KEY,
    salary_sales     NUMERIC(14, 2) NOT NULL DEFAULT 0,  -- ЗП отдела продаж (РОП+МОПы)
    salary_marketing NUMERIC(14, 2) NOT NULL DEFAULT 0,  -- ЗП маркетинга
    payroll_tax_pct  NUMERIC(6, 3)  NOT NULL DEFAULT 0,  -- налог на ФОТ, % от суммы ЗП
    comment          TEXT,
    created_by       INTEGER REFERENCES app_users (id),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
