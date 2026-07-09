-- Stage 4: переход на прямые месячные тоталы затрат (по образцу листа
-- «Воронка по месяцам (скрипт)»): «Расходы на маркетинг» и «Расходы на продажи».
-- Маркетинг уже включает рекламу (лист «Затраты и касания») и ЗП маркетинга;
-- продажи включают ЗП продаж и налоги. Раскладка на ЗП/налоги больше не нужна.

ALTER TABLE monthly_costs
    ADD COLUMN IF NOT EXISTS cost_marketing NUMERIC(14, 2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS cost_sales     NUMERIC(14, 2) NOT NULL DEFAULT 0;

ALTER TABLE monthly_costs
    DROP COLUMN IF EXISTS salary_sales,
    DROP COLUMN IF EXISTS salary_marketing,
    DROP COLUMN IF EXISTS payroll_tax_pct;
