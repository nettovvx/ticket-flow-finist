# TicketFlow

TicketFlow после рефакторинга:

- Backend: `FastAPI` + `SQLAlchemy` + `Alembic` + session-auth.
- Frontend: `React` + `Vite` (SPA, собирается в `app/static/web`).
- База данных: `PostgreSQL`.
- Контур запуска: `Docker Compose` (`app + postgres + caddy`).

## Что уже реализовано

- API для:
  - авторизации (`/api/auth/*`);
  - мониторинга документов (`/api/documents/*`);
  - администрирования пользователей (`/api/admin/users` + смена роли + удаление).
- UI на React:
  - логин;
  - вкладки `Билеты и реализации` / `Платежки`;
  - фильтры и поиск;
  - детализация документа с таймлайном;
  - блок пользователей для `admin`.
- Миграции Alembic:
  - стартовая миграция `20260407_0001_initial_schema.py`.
- Фоновый файловый конвейер:
  - автоматическое перемещение файлов по каталогам;
  - автоматическая фиксация документов/событий в БД;
  - автоматическое связывание `ticket -> realization -> payment`.

## Быстрый старт (Docker Compose)

1. Создайте `.env` из примера:

```bash
cp .env.example .env
```

2. Запустите контейнеры:

```bash
docker compose up --build
```

3. Откройте:

- `http://localhost`

При старте `app` автоматически выполняет:

```bash
alembic upgrade head
```

и затем поднимает `uvicorn`.

## Caddy (домен и SSL)

- В `docker-compose` добавлен `caddy` как reverse proxy перед `app`.
- Для production укажите в `.env`:
  - `CADDY_DOMAIN=ваш.домен`
  - `CADDY_ACME_EMAIL=you@example.com`
- Caddy автоматически выпустит и продлит сертификат Let's Encrypt.

Важно: для `app` используются bind-mount каталоги с хоста (Debian12):

- `/opt/sirena-olt-client/received-files`
- `/srv/ftp/tickets`
- `/srv/ftp/realisations`
- `/srv/ftp/payments`
- `/mnt/1c-gds`
- `/mnt/1c-payments`

Проверьте, что эти пути существуют на хост-машине и доступны на запись контейнеру.
Пути задаются через `HOST_*` переменные в `.env`.

## Автоконвейер файлов

Конвейер работает в фоне внутри backend-процесса и каждые `FILE_SCAN_INTERVAL_SEC`
сканирует каталоги из `.env`.

### Билеты

- вход: `TICKET_INBOX_DIR` (например, `/opt/sirena-olt-client/received-files`)
- перенос в FTP: `FTP_TICKETS_DIR` (например, `/srv/ftp/tickets`)
- мониторинг результата:
  - `FTP_TICKETS_PROCESSED_DIR`
  - `FTP_TICKETS_ERROR_DIR`

### Реализации

- вход: `FTP_REALISATIONS_DIR` (например, `/srv/ftp/realisations`)
- перенос в 1С: `ONEC_REALISATIONS_TARGET_DIR` (например, `/mnt/1c-gds`)
- в мониторинге учитываются только те реализации, у которых найдена связь с уже известным билетом в системе (по `PNR`);
- если связь не найдена, файл просто перемещается в `ONEC_REALISATIONS_TARGET_DIR` без создания карточки/документа в БД.

### Платежки

- вход: `ONEC_PAYMENTS_SOURCE_DIR` (например, `/mnt/1c-payments`)
- перенос в FTP: `FTP_PAYMENTS_DIR` (например, `/srv/ftp/payments`)
- мониторинг результата:
  - `FTP_PAYMENTS_PROCESSED_DIR`
  - `FTP_PAYMENTS_ERROR_DIR`

### Временные метки

Для `ticket` и `payment` в качестве `occurred_at` используется время файла
из файловой системы (на Linux обычно `mtime`).

### Критерий успеха билета

Билет получает статус `success`, когда выполнены оба контрольных факта:

- файл билета попал в `FTP_TICKETS_PROCESSED_DIR` (шаг `ticket_seen_by_mom`);
- связанная реализация перемещена в `ONEC_REALISATIONS_TARGET_DIR` (шаг `realization_copied_to_smb`).

Это позволяет корректно считать успех даже если система была запущена уже при наличии
файлов и ранние шаги (`sirena_received`, `ticket_copied_to_ftp`) не были зафиксированы.

В UI вкладки `Билеты и реализации` отображаются только карточки билетов:

- без отдельных карточек "осиротевших" реализаций;
- с явным индикатором "Связанная реализация пока не найдена" или количеством найденных реализаций.

## Учетные данные по умолчанию

Bootstrap-админ берется из `.env`:

- `BOOTSTRAP_ADMIN_USERNAME` (по умолчанию `admin`)
- `BOOTSTRAP_ADMIN_PASSWORD` (по умолчанию `admin123`)
- `BOOTSTRAP_ADMIN_ROLE` (по умолчанию `admin`)

## Локальная разработка без Docker

1. Установите зависимости backend:

```bash
pip install -r requirements.txt
```

2. Установите зависимости frontend:

```bash
cd frontend
npm install
```

3. Выполните миграции:

```bash
alembic upgrade head
```

4. Соберите frontend:

```bash
cd frontend
npm run build
```

5. Запустите backend:

```bash
uvicorn app.main:app --reload
```

Тестовые XML/снапшоты не включаются в Docker-образ и не требуются для работы конвейера.
