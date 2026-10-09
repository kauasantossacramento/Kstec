# KS CENTRAL

Sistema de Gestão Integrada da **KS TEC Soluções de Tecnologia LTDA** (CNPJ 62.501.281/0001-13 · Valença/BA).

Stack: Python 3.12 · Django 5.2 · PostgreSQL 16 · Redis · Celery · HTMX + Alpine.js.

- Especificação completa: [`docs/plano_desenvolvimento.md`](docs/plano_desenvolvimento.md)
- **Manual de deploy:** [`docs/deploy.md`](docs/deploy.md)
- Andamento por fase: [`docs/fases.md`](docs/fases.md)
- **Passagem para o próximo agente:** [`docs/PASSAGEM_AGENTE_IA.md`](docs/PASSAGEM_AGENTE_IA.md)

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

## Windows sem Docker (demonstração local)

Veja o [roteiro de instalação e testes locais](docs/testes_locais.md).
O perfil `config.settings.local` usa SQLite e tarefas síncronas.
O módulo Fiscal permite rascunhos, configuração A1/token cifrados, emissão municipal,
consulta, XML autorizado, DANFSe PDF e envio documental avulso ou contratual.
O canal municipal foi validado com uma nota real; emissão nacional direta retornou E0039.
Financeiro já permite lançamentos, baixas integrais auditadas, recorrências,
demonstrativo por competência, caixa e faixas de atraso. Operação permite tarefas,
quadro, apontamentos de horas, evidências e relatórios aprovados, com acesso por alocação.
Custos por contrato têm composição, BDI e exportação XLSX/PDF. Envio contratual
exige certidões válidas e documentos aprovados da competência. E-mail local é simulado.
Os aceites completos das fases 5 e 6 e as pendências estão em `docs/fases.md`.
