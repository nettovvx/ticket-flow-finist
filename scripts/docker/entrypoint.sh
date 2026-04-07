#!/usr/bin/env sh
set -eu

alembic upgrade head
exec uvicorn app.main:app --host "${SERVER_HOST:-0.0.0.0}" --port "${SERVER_PORT:-8000}"
