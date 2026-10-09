#!/bin/sh
set -e
# Somente o serviço web aplica migrações (evita corrida com worker/beat).
if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  python manage.py migrate --noinput
  python manage.py collectstatic --noinput -v0
fi
exec "$@"
