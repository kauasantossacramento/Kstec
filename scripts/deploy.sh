#!/usr/bin/env bash
# Atualiza a aplicação na VPS para uma tag/imagem. Chamado pelo workflow de deploy ou manualmente:
#   ./scripts/deploy.sh v1.2.0
set -euo pipefail
cd "$(dirname "$0")/.."
TAG="${1:-latest}"
export KS_IMAGE="ghcr.io/kauasantossacramento/kscentral:${TAG}"
COMPOSE="docker compose -f docker/compose.yml --env-file .env"

./scripts/backup.sh
$COMPOSE pull web worker beat
$COMPOSE up -d --no-build
$COMPOSE exec -T web python manage.py check --deploy --fail-level ERROR
echo "Deploy de $KS_IMAGE concluído."
