#!/usr/bin/env bash
# Backup diário criptografado do KS CENTRAL (seção 12): pg_dump + mídia.
# Retenção: 30 diários + 12 mensais. Uso (no host, via cron):
#   15 2 * * * cd /srv/kscentral && ./scripts/backup.sh >> /var/log/kscentral-backup.log 2>&1
set -euo pipefail

cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

COMPOSE="docker compose -f docker/compose.yml --env-file .env"
DESTINO="${BACKUP_DIR:-./backups}"
DATA="$(date +%Y-%m-%d_%H%M)"
DIA_MES="$(date +%d)"
: "${BACKUP_PASSPHRASE:?Defina BACKUP_PASSPHRASE no .env}"

mkdir -p "$DESTINO/diario" "$DESTINO/mensal"
ARQ="$DESTINO/diario/kscentral_${DATA}.tar.gz.enc"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "[$(date -Is)] Gerando dump do banco..."
$COMPOSE exec -T db pg_dump -U "${POSTGRES_USER:-kscentral}" -d "${POSTGRES_DB:-kscentral}" -Fc > "$TMP/db.dump"

echo "[$(date -Is)] Copiando mídia..."
$COMPOSE exec -T web tar -C /app -czf - media > "$TMP/media.tar.gz"

sha256sum "$TMP/db.dump" "$TMP/media.tar.gz" > "$TMP/SHA256SUMS"
tar -C "$TMP" -czf - db.dump media.tar.gz SHA256SUMS \
  | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass env:BACKUP_PASSPHRASE -out "$ARQ"
echo "[$(date -Is)] Backup gerado: $ARQ ($(du -h "$ARQ" | cut -f1))"

if [ "$DIA_MES" = "01" ]; then
  cp "$ARQ" "$DESTINO/mensal/"
fi

# Retenção
ls -1t "$DESTINO/diario/"*.enc 2>/dev/null | tail -n +31 | xargs -r rm -f
ls -1t "$DESTINO/mensal/"*.enc 2>/dev/null | tail -n +13 | xargs -r rm -f

# Cópia externa (Nextcloud/S3 via rclone), se configurada
if [ -n "${BACKUP_RCLONE_REMOTE:-}" ] && command -v rclone >/dev/null; then
  rclone sync "$DESTINO" "$BACKUP_RCLONE_REMOTE" --quiet
  echo "[$(date -Is)] Sincronizado com $BACKUP_RCLONE_REMOTE"
fi
