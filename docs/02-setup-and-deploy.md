# 02 — Установка и деплой

## Локальный запуск

Требуется Python 3.11+ и доступный PostgreSQL.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # заполнить переменные (ниже)
python scripts/migrate.py --create-admin
python wsgi.py                  # http://localhost:8000
```

`scripts/migrate.py`:
- **без флагов** — применяет непринятые миграции (учёт в таблице `schema_migrations`);
- **`--create-admin`** — дополнительно создаёт/обновляет админа из
  `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` (идемпотентно, `ON CONFLICT`).

Локальный запуск веб-сервера — `python wsgi.py` (dev) или
`gunicorn wsgi:app` (как в проде).

## Переменные окружения

| Переменная | Назначение | Обяз. |
|------------|------------|:-----:|
| `SECRET_KEY` | Ключ подписи сессий Flask (случайная строка) | ✔ |
| `DATABASE_URL` | PostgreSQL. На Railway — `${{Postgres.DATABASE_URL}}` одной строкой. `postgres://` авто-нормализуется в `postgresql://`. | ✔ |
| `AMOCRM_SUBDOMAIN` | Субдомен amoCRM (только имя: `mycompany`). Код сам вычищает схему/`.amocrm.ru`/пробелы. | ✔¹ |
| `AMOCRM_TOKEN` | Долгоживущий токен доступа amoCRM (интеграция → «Ключи и доступы»). | ✔¹ |
| `AMOCRM_PIPELINE_ID` | ID целевой воронки. По умолчанию `3807` («Воронка1»). | — |
| `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` | Первичный админ для `--create-admin`. | — |
| `ANTHROPIC_API_KEY` | Ключ Claude API для кнопки «Рекомендации от нейросети». | —² |
| `AI_MODEL` | Модель Claude. По умолчанию `claude-opus-4-8`. | — |
| `LTV_MONTHS` | Расчётный срок жизни клиента (LT) для LTV. По умолчанию `21`. | — |
| `SYNC_HOUR_UTC` | Час ежедневного автосинка (UTC). По умолчанию `2`. | — |
| `ENABLE_SCHEDULER` | `1`/`0` — включён ли APScheduler. По умолчанию `1`. | — |
| `BACKFILL_SINCE_YEAR` | С какого года тянуть историю событий при бэкофилле. По умолчанию `2023`. | — |
| `FLASK_ENV` | `production`/`development` (влияет на `SESSION_COOKIE_SECURE`). | — |

¹ Обязательны для синхронизации. Без них приложение поднимется, но данных не будет.
² Без ключа приложение работает, кнопка AI отдаёт понятную ошибку.

Шаблон — в `.env.example`.

## Деплой на Railway

1. **New Project → Deploy from GitHub repo** → выбрать репозиторий и ветку.
2. Добавить **PostgreSQL** (регион **EU** — задаётся при создании плагина, потом
   не меняется; по ТЗ данные хранятся в EU).
3. У сервиса `web` в **Variables** задать переменные из таблицы выше.
   Обязательно `DATABASE_URL = ${{Postgres.DATABASE_URL}}` (референс на плагин).
4. Старт-команда (`railway.json`) при каждом деплое:
   ```
   python scripts/migrate.py --create-admin && gunicorn wsgi:app --bind 0.0.0.0:$PORT ...
   ```
   — прогоняет миграции, создаёт/обновляет админа, поднимает gunicorn.

Деплой запускается автоматически при push в отслеживаемую ветку GitHub.

### Первичная загрузка данных

После первого деплоя: войти админом → **Синхронизация** → **«Первичный
бэкофилл»**. Тянет все сделки целевой воронки с `BACKFILL_SINCE_YEAR` и историю
событий смены статусов. Занимает несколько минут (порядка 16 тыс. сделок).

## Проверка работоспособности

- `GET /healthz` — либнесс-проба (200 OK).
- Страница **amoCRM** (`/admin/amocrm-check`, только admin) — проверяет
  `/account`, список воронок и реальную глубину истории событий.
