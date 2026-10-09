# Andamento por fase

Registro do que foi entregue em cada fase do roteiro (plano, seção 13) e do que depende de ação externa.

## Fase 0 — Fundação e infraestrutura ✅

- `pyproject.toml` (ruff, pytest), `requirements*.txt`, pre-commit.
- `config/settings/{base,dev,test,prod}.py` com `django-environ`; `America/Bahia`, `pt-br`, separador de milhar.
- Celery + `django-celery-beat` (agenda completa do anexo 14.3), Sentry, logs JSON (`structlog`).
- Docker: `docker/Dockerfile`, `docker/compose.yml` (`web`, `worker`, `beat`, `db`, `redis`, `caddy`) com healthchecks; `docker/Caddyfile` com TLS automático.
- CI (`.github/workflows/ci.yml`): lint + migrações em dia + testes com Postgres + build/publicação da imagem no GHCR; deploy por tag (`deploy.yml`).
- `scripts/backup.sh` (criptografado, retenção 30+12, rclone), `scripts/restore.sh` (com modo `--teste`), `scripts/deploy.sh`.
- `/health` com checagem de banco e cache.
- Usuário customizado (login por e-mail) criado já na fundação para não exigir troca de `AUTH_USER_MODEL` depois.
