#!/usr/bin/env bash
# Restaura um backup gerado por backup.sh.
#   ./scripts/restore.sh backups/diario/kscentral_2026-10-08_0215.tar.gz.enc
# ATENÇÃO: substitui o banco e a mídia atuais. Use --teste para restaurar em um banco
# temporário (kscentral_restore) e validar sem tocar produção (teste mensal, seção 12).
set -euo pipefail

cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

ARQ="${1:?informe o arquivo .enc}"
MODO="${2:-}"
COMPOSE="docker compose -f docker/compose.yml --env-file .env"
DB="${POSTGRES_DB:-kscentral}"
USR="${POSTGRES_USER:-kscentral}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
INICIO=$(date +%s)

openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BACKUP_PASSPHRASE -in "$ARQ" | tar -C "$TMP" -xzf -
(cd "$TMP" && sha256sum -c SHA256SUMS)

if [ "$MODO" = "--teste" ]; then
  DB_ALVO="${DB}_restore"
  $COMPOSE exec -T db dropdb -U "$USR" --if-exists "$DB_ALVO"
  $COMPOSE exec -T db createdb -U "$USR" "$DB_ALVO"
  $COMPOSE exec -T db pg_restore -U "$USR" -d "$DB_ALVO" --no-owner < "$TMP/db.dump"
  N=$($COMPOSE exec -T db psql -U "$USR" -d "$DB_ALVO" -tAc "select count(*) from django_migrations")
  echo "Restauração de teste OK: $N migrações aplicadas em $DB_ALVO. Tempo: $(( $(date +%s) - INICIO ))s"
  $COMPOSE exec -T db dropdb -U "$USR" "$DB_ALVO"
  exit 0
fi

read -r -p "Isto SUBSTITUI o banco '$DB' e a mídia. Digite RESTAURAR para continuar: " OK
[ "$OK" = "RESTAURAR" ] || { echo "Cancelado."; exit 1; }

$COMPOSE stop web worker beat
$COMPOSE exec -T db pg_restore -U "$USR" -d "$DB" --clean --if-exists --no-owner < "$TMP/db.dump"
$COMPOSE run --rm -T --no-deps --entrypoint "" web sh -c "rm -rf /app/media/* && tar -C /app -xzf -" < "$TMP/media.tar.gz"
$COMPOSE up -d
echo "Restauração concluída em $(( $(date +%s) - INICIO ))s."
