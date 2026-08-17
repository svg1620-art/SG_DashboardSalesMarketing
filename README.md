# DashboardSales&Marketing

Веб-платформа аналитики воронки продаж — миграция с Google Sheets + amoCRM на
самостоятельный сервис (Flask + PostgreSQL + Railway) с прямой интеграцией к
amoCRM API. **Источник правды — база данных**, а не ячейки таблицы.

> Рабочее название продукта: **DashboardSales&Marketing** (в исходном ТЗ —
> «SG_FunnelBoard»).

---

## Быстрый старт (локально)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # заполнить DATABASE_URL, amoCRM, ключи
python scripts/migrate.py --create-admin
python wsgi.py                  # http://localhost:8000
```

Подробности — в [`docs/02-setup-and-deploy.md`](docs/02-setup-and-deploy.md).

---

## Документация

Полный комплект для передачи проекта — в папке [`docs/`](docs/):

| Файл | О чём |
|------|-------|
| [01 — Обзор и архитектура](docs/01-overview-architecture.md) | Стек, принципы, потоки данных, структура репозитория |
| [02 — Установка и деплой](docs/02-setup-and-deploy.md) | Локальный запуск, переменные окружения, Railway |
| [03 — База данных](docs/03-database.md) | Схема, все таблицы, миграции |
| [04 — Интеграция amoCRM и синхронизация](docs/04-amocrm-sync.md) | Клиент API, движок синка, сверка удалённых |
| [05 — Воронка и метрики](docs/05-funnel-and-metrics.md) | Этапы, когортная атрибуция, юнит-экономика (CAC/LTV) |
| [06 — Функции и интерфейс](docs/06-features-and-ui.md) | Дашборды, затраты, экспорт, нейросеть, роли |
| [07 — Справочник маршрутов](docs/07-routes-reference.md) | Все HTTP-эндпоинты |
| [08 — Эксплуатация (runbook)](docs/08-operations-runbook.md) | Деплой, синк, диагностика проблем |
| [09 — Расширение и соглашения](docs/09-extending-and-conventions.md) | Как добавлять метрики, поля, вкладки, миграции |
| [10 — Чек-лист передачи](docs/10-handoff-checklist.md) | Онбординг нового разработчика, доступы, открытые вопросы |
| [CHANGELOG](docs/CHANGELOG.md) | История разработки по стадиям |

---

## Технологический стек

Flask 3 + Jinja2 · PostgreSQL (psycopg2) · APScheduler · httpx · Chart.js ·
openpyxl · anthropic (Claude API) · gunicorn · Railway (регион EU).

## Статус

Все стадии плана ТЗ реализованы (см. [CHANGELOG](docs/CHANGELOG.md)). Открытые
вопросы и возможные доработки — в [чек-листе передачи](docs/10-handoff-checklist.md).
