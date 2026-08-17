# 07 — Справочник маршрутов

Доступ: 🔓 без входа · 👤 любой вошедший · 🟡 marketer+ · 🔴 admin.

## Аутентификация (`app/auth.py`)

| Метод | Путь | Доступ | Назначение |
|-------|------|:------:|------------|
| GET/POST | `/login` | 🔓 | Вход |
| GET | `/logout` | 👤 | Выход |

## Дашборды (`blueprints/dashboard_bp.py`)

| Метод | Путь | Доступ | Назначение |
|-------|------|:------:|------------|
| GET | `/` | 👤 | Редирект на «По источникам» |
| GET | `/dashboard/sources` | 👤 | Дашборд по источникам |
| GET | `/dashboard/months` | 👤 | Дашборд по месяцам |
| GET | `/dashboard/managers` | 👤 | Дашборд по менеджерам |
| GET | `/dashboard/deals` | 👤 | Таблица сделок (поиск, пагинация) |
| GET | `/dashboard/export` | 👤 | Страница экспорта |
| GET | `/dashboard/export.xlsx` | 👤 | Скачать Excel (учитывает фильтры) |
| POST | `/ai/recommendations?page=…` | 👤 | AI-анализ раздела (нужен `ANTHROPIC_API_KEY`) |

## Затраты (`blueprints/dashboard_bp.py`)

| Метод | Путь | Доступ | Назначение |
|-------|------|:------:|------------|
| GET | `/dashboard/costs` | 👤 | Просмотр (ввод — только marketer+) |
| POST | `/dashboard/costs/touches` | 🟡 | Сохранить рекламу по источнику (upsert) |
| POST | `/dashboard/costs/touches/<id>/delete` | 🟡 | Удалить строку рекламы |
| POST | `/dashboard/costs/operating` | 🟡 | Сохранить затраты месяца (upsert) |
| POST | `/dashboard/costs/operating/<month>/delete` | 🟡 | Удалить затраты месяца |

## Администрирование (`blueprints/admin_bp.py`)

| Метод | Путь | Доступ | Назначение |
|-------|------|:------:|------------|
| GET | `/admin/amocrm-check` | 🔴 | Проверка подключения amoCRM |
| GET | `/admin/sync` | 🟡 | Страница синхронизации + журнал |
| POST | `/admin/sync/run` | 🟡 | «Обновить сейчас» (инкрементальный) |
| POST | `/admin/sync/backfill` | 🔴 | Первичный бэкофилл |
| GET | `/admin/sync/progress` | 🟡 | JSON живого статуса (для polling) |
| GET | `/admin/users` | 🔴 | Список пользователей |
| POST | `/admin/users/create` | 🔴 | Создать пользователя |
| POST | `/admin/users/<id>/update` | 🔴 | Сменить роль/пароль/активность |
| POST | `/admin/users/<id>/delete` | 🔴 | Удалить пользователя |

## Служебное

| Метод | Путь | Доступ | Назначение |
|-------|------|:------:|------------|
| GET | `/healthz` | 🔓 | Проба живости (200) |

> Точный список декораторов доступа — в исходниках блюпринтов
> (`@login_required`, `@role_required("marketer")`, `@role_required("admin")`).
