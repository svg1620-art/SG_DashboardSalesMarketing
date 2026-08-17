# 01 — Обзор и архитектура

## Что это

Внутренняя веб-платформа аналитики воронки продаж и маркетинга. Заменяет
Google-таблицу с ручными формулами: напрямую синхронизирует данные из amoCRM в
PostgreSQL и строит дашборды (по источникам, месяцам, менеджерам), считает
юнит-экономику (CAC / LTV / LTV:CAC), даёт ввод затрат, экспорт в Excel и
AI-рекомендации.

## Технологический стек

| Слой | Технология |
|------|------------|
| Backend | Flask 3 + Jinja2, gunicorn |
| БД | PostgreSQL (Railway managed), `psycopg2-binary` (пул соединений) |
| Планировщик | APScheduler (ежедневный автосинк) |
| HTTP к amoCRM | `httpx` (пагинация, ретраи, обработка 429) |
| Графики | Chart.js (вендорится локально в `static/vendor/`, без CDN) |
| Экспорт | `openpyxl` (генерация в память) |
| Нейросеть | `anthropic` SDK, модель `claude-opus-4-8` |
| Деплой | Railway (nixpacks), исходники в GitHub |

Версии зафиксированы в `requirements.txt`.

## Архитектурные принципы

- **Источник правды — БД.** amoCRM синкается в PostgreSQL; дашборды считают
  метрики SQL-агрегацией на лету. Таблица amoCRM больше не нужна.
- **Идемпотентность синка.** Upsert по `amo_lead_id` — повторный прогон не плодит
  дубли. Плюс сверка: сделки, исчезнувшие из воронки amoCRM, удаляются (см. док. 04).
- **Когортная атрибуция.** Все метрики привязаны к месяцу *создания* лида и
  «догоняются» по мере закрытия сделок (см. док. 05). Это ключевое отличие
  методики — не по дате закрытия.
- **ФС Railway эфемерна.** Ничего не пишем на диск: экспорт генерится в память,
  всё состояние — в БД.
- **Правки данных не перетираются синком.** Сопоставление статус→этап и флаг
  «исключить» редактируются, синхронизация их сохраняет.

## Потоки данных

```
amoCRM API v4  ──(httpx, пагинация)──►  sync.py  ──►  PostgreSQL
   /users, /leads/pipelines,                            (deals, deal_stage_history,
   /leads, /events, /custom_fields                       managers, pipeline_statuses,
                                                          sources, costs_touches,
                                                          monthly_costs, sync_log)
                                                              │
                          Ручной ввод затрат ────────────────┤
                                                              ▼
                                      metrics.py  ──(SQL-агрегация)──►  Дашборды (Jinja + Chart.js)
                                                              ├──►  export.py  ──►  Excel (в память)
                                                              └──►  ai.py  ──►  Claude API  ──►  рекомендации
```

## Структура репозитория

```
app/
  __init__.py          Фабрика приложения (create_app), Jinja-фильтры, планировщик
  config.py            Конфигурация из переменных окружения
  db.py                Пул psycopg2 (ThreadedConnectionPool) + помощники query/execute
  auth.py              Пароли (PBKDF2), сессии, роли, декораторы доступа, вход/выход
  amocrm.py            Клиент amoCRM API v4 (пагинация, ретраи)
  sync.py              Движок синхронизации amoCRM → PostgreSQL (фоновый поток)
  stages.py            Чистая логика вычисления этапов воронки (юнит-тестируемая)
  scheduler.py         APScheduler: ежедневный автосинк
  metrics.py           Расчёт всех метрик дашбордов (SQL-агрегация)
  export.py            Экспорт в Excel (openpyxl)
  ai.py                Анализ и рекомендации через Claude API
  blueprints/
    dashboard_bp.py    Дашборды, затраты, сделки, экспорт, AI-эндпоинт
    admin_bp.py        Проверка amoCRM, синхронизация, управление пользователями
  templates/           Jinja2 (фирменный стиль SG)
  static/css/style.css Стили (палитра SG)
  static/vendor/       Chart.js (вендор)
migrations/            SQL-миграции (нумерованные, применяются по порядку)
scripts/migrate.py     Раннер миграций + bootstrap администратора
wsgi.py                Точка входа gunicorn (gunicorn wsgi:app)
railway.json           Конфиг Railway (старт: миграции + admin + gunicorn)
Procfile               Fallback-команда веб-процесса
docs/                  Эта документация
```

## Фирменный стиль

Тёмная база `#0A0A0D`, синий `#1467F5`, циан `#00BFDC`, мятный `#26E0A0`;
шрифты Manrope (текст) + JetBrains Mono (цифры). Палитра и компоненты — в
`static/css/style.css`. Цвета типов клиента: МКК синий, КК циан, СКК мятный
(`metrics.CLIENT_TYPE_COLORS`).
