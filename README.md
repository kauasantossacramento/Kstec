# KS CENTRAL

Sistema de Gestão Integrada da **KS TEC Soluções de Tecnologia LTDA** (CNPJ 62.501.281/0001-13 · Valença/BA).

Stack: Python 3.12 · Django 5.2 · PostgreSQL 16 · Redis · Celery · HTMX + Alpine.js.

- Especificação completa: [`docs/plano_desenvolvimento.md`](docs/plano_desenvolvimento.md)
- **Manual de deploy:** [`docs/deploy.md`](docs/deploy.md)
- Andamento por fase: [`docs/fases.md`](docs/fases.md)

## Rodando localmente

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # ajuste DATABASE_URL/REDIS_URL para localhost e DJANGO_SETTINGS_MODULE=config.settings.dev
python manage.py migrate
python manage.py runserver
celery -A config worker -l info     # outro terminal
celery -A config beat -l info       # outro terminal
```

Testes: `pytest` · Lint: `ruff check .`
