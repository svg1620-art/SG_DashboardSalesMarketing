# DashboardSales&Marketing

Веб-платформа аналитики воронки продаж — миграция с Google Sheets + amoCRM на
самостоятельный сервис стека ServiceGuru (Flask + PostgreSQL + Railway) с прямой
интеграцией к amoCRM API. Источник правды — база данных.

> Рабочее название продукта закреплено: **DashboardSales&Marketing**
> (в ТЗ фигурировало как «SG_FunnelBoard (уточнить)»).

## Статус

**Stage 1 — Каркас + БД + авторизация** (ТЗ §11):

- Flask-скелет (app factory, блюпринты, gunicorn/`wsgi.py`).
- Модель данных PostgreSQL — все таблицы ТЗ §8, миграции в `migrations/`.
- Идемпотентный запуск миграций + bootstrap администратора (`scripts/migrate.py`).
- Аутентификация email + пароль (PBKDF2), сессии, роли `admin / marketer / viewer`.
- Проверочный вызов amoCRM (`/admin/amocrm-check`): `/account`, `/leads/pipelines`
  и проба реальной глубины истории событий `lead_status_changed` (ТЗ §6, §11).
- Фирменный стиль SG: тёмная база `#0A0A0D`, синий `#1467F5`, циан `#00BFDC`,
  Manrope + JetBrains Mono.

**Stage 2 — Движок синхронизации** (ТЗ §6):

- Клиент amoCRM с пагинацией (`_links.next`), ретраями и обработкой лимитов:
  пользователи, кастомные поля, сделки, история событий `lead_status_changed`.
- Сопоставление статус → этап воронки (§3) — посев `migrations/002` по данным
  «Воронки1», далее редактируется admin; синхронизация не перезатирает правки.
- Вычисление этапов (`app/stages.py`): `max_stage_reached` + флаги, линейная
  порядковая воронка, фолбэк для сделок без истории, исключение «Дубль» из MQL.
- Идемпотентный upsert сделок/истории/источников/менеджеров (§10, без дублей).
- Фоновая синхронизация с прогрессом + журнал `sync_log`; страница
  `/admin/sync`, кнопка «Обновить сейчас» (admin/marketer), бэкофилл (admin).
- Ежедневный автосинк через APScheduler; advisory-lock от двойного запуска.

**Stage 3 — Дашборд «По источникам»** (ТЗ §4):

- Единая панель фильтров (период / менеджер / источник / воронка) — `_filters.html`.
- Метрики воронки на лету (`app/metrics.py`): по каждому источнику + строка
  «Все источники». Конверсии, доходимость, % неквала, CPL, цена встречи/продажи,
  ROAS, средний чек, выручка. Cost-метрики подхватывают `costs_touches`.
- Визуальная воронка на Chart.js (вендорится в `static/vendor/`, без CDN).
- Вкладки-навигация; «По месяцам/менеджерам/затраты/сделки/экспорт» — заглушки.

Дальнейшие стадии (по месяцам, по менеджерам, затраты, экспорт) — в следующих сессиях.

## Технологический стек

Flask + Jinja2 + HTMX · PostgreSQL (psycopg2-binary) · APScheduler · httpx ·
Chart.js · openpyxl · gunicorn · Railway (регион EU).

## Локальный запуск

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # заполните DATABASE_URL и amoCRM
python scripts/migrate.py --create-admin
python wsgi.py                  # http://localhost:8000
```

## Переменные окружения

| Переменная | Назначение |
|------------|------------|
| `SECRET_KEY` | Ключ подписи сессий Flask |
| `DATABASE_URL` | PostgreSQL (на Railway — внутренней ссылкой, одной строкой) |
| `AMOCRM_SUBDOMAIN` | Субдомен amoCRM (`{subdomain}.amocrm.ru`) |
| `AMOCRM_TOKEN` | Долгоживущий токен доступа amoCRM |
| `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` | Первичный админ для `--create-admin` |

## Деплой на Railway

`railway.json` при старте прогоняет миграции, создаёт/обновляет администратора
из `BOOTSTRAP_ADMIN_EMAIL`/`BOOTSTRAP_ADMIN_PASSWORD` (идемпотентно) и поднимает
gunicorn. Секреты и `DATABASE_URL` задаются через Variables. Файловая система
эфемерна — всё в БД.

## Структура

```
app/
  __init__.py          фабрика приложения
  config.py            конфигурация из окружения
  db.py                пул psycopg2 + помощники запросов
  auth.py              пароли, сессии, роли, вход/выход
  amocrm.py            клиент amoCRM (проверки Stage 1)
  blueprints/          дашборды (заглушки) + admin
  templates/           Jinja2 (фирменный стиль SG)
  static/css/
migrations/            SQL-миграции
scripts/migrate.py     раннер миграций + bootstrap админа
wsgi.py                точка входа gunicorn
```
