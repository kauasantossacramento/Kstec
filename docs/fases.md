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

## Fase 1 — Núcleo, design system e cadastros ✅

- `core`: `ModeloBase` (UUID v7, empresa, carimbos, autor, `simple_history`), Empresa, Usuario (login por e-mail), papéis (Administrador, Financeiro, Fiscal, Operação, Leitura), Endereco, Anexo (SHA-256, retenção legal), Parametro, Segredo (Fernet), Notificacao, LogIntegracao (segredos mascarados), LogAcesso.
- Segurança: MFA TOTP obrigatório para Administrador/Financeiro/Fiscal (`django-otp`), `django-axes` (5 tentativas/1h), senha mínima de 10 caracteres, sessão de 8h, CSP `script-src 'self'` (htmx e Chart.js vendorizados em `static/vendor/`, sem CDN de scripts).
- Design system: `static/css/tokens.css` (tokens da seção 4.2), `app.css`, `app.js` (Ctrl+K, atalhos `N`, `G C/F/P/T/R`, `?`, toasts, máscaras BRL/CPF/CNPJ/CEP, confirmação com digitação do número, gráficos). Catálogo vivo em `/_componentes/`.
- CRUD genérico (`apps/core/crud.py`): lista com busca, filtros, ordenação e paginação HTMX, detalhe com anexos e histórico, formulários estilizados; leitura liberada, escrita por papel.
- `cadastros`: Pessoa (cliente/órgão/fornecedor) + Contato; consulta automática de CNPJ (BrasilAPI) e CEP (ViaCEP); validação de dígitos.
- `seed_inicial` cria a empresa KS TEC (CNPJ 62.501.281/0001-13, Valença/BA 2932903), papéis e parâmetros.
- Logos em SVG provisórios (o PNG oficial não pôde ser baixado do ambiente de desenvolvimento) — ver `static/img/README.md`.

## Fase 2 — Contratos e certidões ✅

- `contratos`: Contrato, Aditivo, ItemContrato, Empenho, Competencia (geração automática pela vigência, inclusive aditivos de prazo; comando `gerar_competencias`).
- Hub do contrato com abas `Resumo · Notas · Financeiro · Tarefas · Relatórios · Custos · Sistemas/SLA · Documentos · Histórico` (abas de módulos futuros exibem `empty_state`; cada app registra sua aba em `apps/contratos/abas.py`).
- Indicadores: valor atualizado, faturado, saldo, % executado, dias para o fim; alertas de vigência (90/60/30) e saldo < 20% (task diária + notificação por e-mail).
- Técnicos (papel Operação) só veem contratos em que estão alocados.
- `certidoes`: TipoCertidao (seed com 10 tipos), Certidao com upload de PDF e extração de validade/código/situação, semáforo APTA/ATENÇÃO/INAPTA, alertas 30/15/7/0 dias, Kit de habilitação (ZIP + índice PDF; vencidas ficam fora com aviso).
- Agenda de obrigações (`/agenda/`) e "Precisa da sua atenção" no painel, alimentados por provedores registrados por cada app (`apps/core/agenda.py`).
