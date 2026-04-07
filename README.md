# TicketFlow

TicketFlow после рефакторинга:

- Backend: `FastAPI` + `SQLAlchemy` + `Alembic` + session-auth.
- Frontend: `React` + `Vite` (SPA, собирается в `app/static/web`).
- База данных: `PostgreSQL`.
- Контур запуска: `Docker Compose` (`app + postgres`).

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

- `http://localhost:8000`

При старте `app` автоматически выполняет:

```bash
alembic upgrade head
```

и затем поднимает `uvicorn`.

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

### Платежки

- вход: `ONEC_PAYMENTS_SOURCE_DIR` (например, `/mnt/1c-payments`)
- перенос в FTP: `FTP_PAYMENTS_DIR` (например, `/srv/ftp/payments`)
- мониторинг результата:
  - `FTP_PAYMENTS_PROCESSED_DIR`
  - `FTP_PAYMENTS_ERROR_DIR`

### Временные метки

Для `ticket` и `payment` в качестве `occurred_at` используется время файла
из файловой системы (на Linux обычно `mtime`).

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

## Импорт снапшота

После применения миграций можно загрузить тестовые XML:

```bash
python scripts/import_backup_snapshot.py 2025-11-13
```

По умолчанию скрипт берет каталог `2025-11-13`.
