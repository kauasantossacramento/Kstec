# Manual de Deploy — KS CENTRAL

> Público: quem administra a VPS da KS TEC. Ambiente alvo: VPS Hetzner (Ubuntu 24.04 LTS) com Docker Compose.
> Serviços: `web` (gunicorn) · `worker` (Celery) · `beat` (agendador) · `db` (PostgreSQL 16) · `redis` · `caddy` (HTTPS automático).

## Sumário

1. [Pré-requisitos](#1-pré-requisitos)
2. [Preparar a VPS](#2-preparar-a-vps)
3. [Obter o código e configurar o `.env`](#3-obter-o-código-e-configurar-o-env)
4. [Primeira subida](#4-primeira-subida)
5. [Carga inicial (seed, tabelas fiscais, usuários)](#5-carga-inicial)
6. [Configuração fiscal (certificado A1, canais NFS-e)](#6-configuração-fiscal)
7. [Atualizações (deploy contínuo por tag)](#7-atualizações)
8. [Backups e restauração](#8-backups-e-restauração)
9. [Monitoramento, logs e Sentry](#9-monitoramento-logs-e-sentry)
10. [Rollback](#10-rollback)
11. [Solução de problemas](#11-solução-de-problemas)
12. [Checklist de go-live](#12-checklist-de-go-live)
13. [Referência: variáveis de ambiente](#13-referência-variáveis-de-ambiente)
14. [Referência: comandos de gestão e tarefas agendadas](#14-referência-comandos-de-gestão-e-tarefas-agendadas)

---

## 1. Pré-requisitos

| Item | Detalhe |
|---|---|
| VPS | Hetzner CX22 ou superior (2 vCPU, 4 GB RAM, 40 GB SSD). Para > 30 sistemas monitorados, CX32. |
| DNS | Registro `A` (e `AAAA`, se houver IPv6) de `central.kstec.online` apontando para a VPS. Opcional: `status.kstec.online` (página pública de status). |
| Portas | 22 (SSH, restrita), 80 e 443 abertas. |
| Contas | GitHub (acesso ao repositório e ao GHCR), SMTP para e-mails, chave da API Gemini, Sentry (opcional), storage externo para backup (Nextcloud/S3). |
| Fiscal | Certificado A1 (e-CNPJ ICP-Brasil, `.pfx` + senha). Ver pendências no plano, seção 14.5. |

## 2. Preparar a VPS

```bash
# como root, uma única vez
adduser --disabled-password --gecos "" ks
usermod -aG sudo ks
apt update && apt -y upgrade
apt -y install ca-certificates curl git ufw fail2ban unattended-upgrades rclone
dpkg-reconfigure -plow unattended-upgrades

# Docker oficial
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  > /etc/apt/sources.list.d/docker.list
apt update && apt -y install docker-ce docker-ce-cli containerd.io docker-compose-plugin
usermod -aG docker ks

# Firewall
ufw default deny incoming && ufw default allow outgoing
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp
ufw enable

# Fuso horário do host (os containers já usam America/Bahia)
timedatectl set-timezone America/Bahia
```

Endurecimento do SSH (`/etc/ssh/sshd_config`): `PasswordAuthentication no`, `PermitRootLogin no`. Reinicie com `systemctl restart ssh` **depois** de confirmar o login por chave com o usuário `ks`.

## 3. Obter o código e configurar o `.env`

```bash
sudo mkdir -p /srv/kscentral && sudo chown ks:ks /srv/kscentral
su - ks
git clone https://github.com/kauasantossacramento/Kstec.git /srv/kscentral
cd /srv/kscentral
cp .env.example .env
chmod 600 .env
```

Gere os segredos e preencha o `.env`:

```bash
# DJANGO_SECRET_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
# FIELD_ENCRYPTION_KEY (Fernet) — GUARDE EM LOCAL SEGURO: sem ela os segredos do banco (senha do PFX, senha E&L) ficam ilegíveis
python3 -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
# POSTGRES_PASSWORD e BACKUP_PASSPHRASE
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Campos obrigatórios em produção: `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `SITE_URL`, `DOMINIO`, `ACME_EMAIL`, `POSTGRES_PASSWORD`, `DATABASE_URL` (com a mesma senha), `FIELD_ENCRYPTION_KEY`, `EMAIL_URL`, `BACKUP_PASSPHRASE`. Ver a [seção 13](#13-referência-variáveis-de-ambiente).

> ⚠️ No `EMAIL_URL`, caracteres especiais do usuário/senha precisam ser codificados (`@` → `%40`).

## 4. Primeira subida

Todos os comandos `docker compose` usam o arquivo em `docker/` e o `.env` da raiz. Crie um alias para facilitar:

```bash
echo 'alias dc="docker compose -f /srv/kscentral/docker/compose.yml --env-file /srv/kscentral/.env"' >> ~/.bashrc
source ~/.bashrc
```

Imagem: o CI publica `ghcr.io/kauasantossacramento/kscentral:<tag>`. Se o pacote for privado, autentique uma vez:

```bash
echo <TOKEN_COM_read:packages> | docker login ghcr.io -u <usuario-github> --password-stdin
```

Subir (puxando a imagem publicada) **ou** construindo localmente na VPS:

```bash
KS_IMAGE=ghcr.io/kauasantossacramento/kscentral:latest dc pull && dc up -d     # imagem publicada
# ou
dc up -d --build                                                               # build local
```

O serviço `web` aplica as migrações e o `collectstatic` automaticamente (`RUN_MIGRATIONS=1`). Verifique:

```bash
dc ps                                  # todos "healthy"/"running"
curl -s https://central.kstec.online/health
# {"status": "ok", "componentes": {"banco": {"status": "ok", ...}, "cache": {"status": "ok"}}}
dc exec web python manage.py check --deploy
```

O Caddy emite o certificado TLS automaticamente na primeira requisição (o DNS precisa já apontar para a VPS).

## 5. Carga inicial

```bash
# Empresa KS TEC, papéis, plano de categorias financeiras, tipos de certidão, prompts de IA
dc exec web python manage.py seed_inicial

# Superusuário (Administrador)
dc exec web python manage.py createsuperuser

# Tabelas fiscais de referência (Anexo B e Anexo VIII do pacote E&L/ABRASF)
# copie os XLSX para a VPS e então:
dc cp ANEXO_B-NBS2-LISTA_SERVICO_NACIONAL.xlsx web:/tmp/
dc cp AnexoVIII-CorrelacaoItemNBSIndOpCClassTrib_IBSCBS.xlsx web:/tmp/
dc exec web python manage.py importar_tabelas_fiscais /tmp/ANEXO_B-NBS2-LISTA_SERVICO_NACIONAL.xlsx \
    /tmp/AnexoVIII-CorrelacaoItemNBSIndOpCClassTrib_IBSCBS.xlsx

# Histórico de notas do portal E&L (XMLs ou ZIP; a exportação do portal é limitada a 90 dias por arquivo)
dc cp notas_2025.zip web:/tmp/
dc exec web python manage.py importar_nfse_el /tmp/notas_2025.zip

# Competências faltantes dos contratos vigentes
dc exec web python manage.py gerar_competencias
```

Após o primeiro login, o Administrador é obrigado a configurar o **MFA (TOTP)** — use Google Authenticator, Aegis ou 1Password. Os papéis Financeiro e Fiscal também exigem MFA.

Usuários: **Configurações → Usuários** (ou `/admin/`). Papéis disponíveis: Administrador, Financeiro, Fiscal, Operação, Leitura.

## 6. Configuração fiscal

> Antes de emitir em produção, leia a seção 6.14 do plano (duplo canal Nacional × E&L) e as pendências 14.5.

1. **Fiscal → Certificados → Novo**: envie o `.pfx` e a senha. O sistema recusa certificado vencido ou de CNPJ diferente do da empresa. O PFX e a senha ficam criptografados no banco (Fernet).
2. **Fiscal → Configuração**:
   - `ambiente`: comece com **PRODUCAO_RESTRITA** (sem valor fiscal).
   - `canais_habilitados`: `NACIONAL` e, se confirmado com a prefeitura, `EL_ABRASF`.
   - `url_el`: URL do webservice E&L de Valença (obter com a prefeitura/E&L).
   - `el_permite_competencia_atual`: deixe **desligado** até haver confirmação formal.
   - `fallback_automatico`: deixe **desligado**.
3. **Fiscal → Perfis fiscais**: cadastre as regras de retenção validadas pelo contador.
4. XSDs oficiais: copie os XSDs vigentes para `apps/fiscal/xml/schemas/nacional/` e `apps/fiscal/xml/schemas/abrasf/` (ver `apps/fiscal/xml/schemas/README.md`), gere uma nova tag e faça o deploy. Sem XSD, a validação local é pulada e um aviso é registrado no log.
5. Teste de conectividade mTLS com a Sefin (produção restrita):

   ```bash
   dc exec web python manage.py testar_sefin
   ```

6. Siga o **protocolo de teste em produção** (plano, seção 6.14.6) e registre o diário de testes antes de definir o `canal_padrao` e mudar `ambiente` para `PRODUCAO`.

## 7. Atualizações

Fluxo padrão (deploy contínuo por tag):

1. Merge na `main` → CI roda lint + testes + build e publica `:latest`.
2. Criar a tag de versão:

   ```bash
   git tag -a v1.3.0 -m "v1.3.0" && git push origin v1.3.0
   ```

3. O CI publica `ghcr.io/kauasantossacramento/kscentral:v1.3.0` e o workflow **Deploy** (ambiente `producao`) entra na VPS via SSH e executa `scripts/deploy.sh v1.3.0`, que:
   - faz um **backup** antes de tudo;
   - baixa a imagem da tag;
   - recria `web`, `worker` e `beat` (o `web` aplica migrações);
   - roda `manage.py check --deploy`.

Segredos necessários no repositório (Settings → Environments → `producao`): `VPS_HOST`, `VPS_USER` (`ks`), `VPS_SSH_KEY` (chave privada dedicada ao deploy, cuja pública está em `~ks/.ssh/authorized_keys`).

Deploy manual (sem GitHub Actions):

```bash
cd /srv/kscentral && git fetch --tags && git checkout v1.3.0
./scripts/deploy.sh v1.3.0
```

## 8. Backups e restauração

`scripts/backup.sh` gera `pg_dump` (formato custom) + mídia em um único arquivo **criptografado com AES-256** (`BACKUP_PASSPHRASE`), com retenção de **30 diários + 12 mensais**, e sincroniza com storage externo via `rclone` se `BACKUP_RCLONE_REMOTE` estiver definido.

Agende no cron do usuário `ks`:

```bash
crontab -e
15 2 * * * cd /srv/kscentral && ./scripts/backup.sh >> /srv/kscentral/backups/backup.log 2>&1
```

Configurar o destino externo (exemplo Nextcloud via WebDAV):

```bash
rclone config   # crie o remote "nextcloud" (tipo webdav, vendor nextcloud)
# no .env:  BACKUP_RCLONE_REMOTE=nextcloud:kscentral-backups
```

**Teste de restauração mensal** (o painel lembra no dia 5 de cada mês) — restaura num banco temporário e não toca a produção:

```bash
./scripts/restore.sh backups/diario/kscentral_AAAA-MM-DD_HHMM.tar.gz.enc --teste
```

Anote o tempo exibido no diário de operação.

**Restauração real** (desastre):

```bash
./scripts/restore.sh backups/diario/kscentral_AAAA-MM-DD_HHMM.tar.gz.enc
# digite RESTAURAR para confirmar
```

> Guarde `BACKUP_PASSPHRASE` e `FIELD_ENCRYPTION_KEY` **fora da VPS** (cofre de senhas). Sem elas, o backup não abre e os segredos do banco não podem ser lidos.

Retenção fiscal: documentos fiscais (XML/PDF de notas) devem ser preservados por 5 anos; o sistema impede a exclusão nesse prazo.

## 9. Monitoramento, logs e Sentry

- **Saúde:** `GET /health` (usado pelo healthcheck do Docker). Recomenda-se cadastrar o próprio KS CENTRAL em um monitor externo.
- **Logs** (JSON, `structlog`):

  ```bash
  dc logs -f web
  dc logs -f worker beat
  dc logs --since 1h worker | grep -i erro
  ```

- **Sentry:** defina `SENTRY_DSN` (erros de Django e Celery). `send_default_pii` está desligado (LGPD).
- **Integrações externas:** cada chamada (Sefin, E&L, Gemini, BrasilAPI) fica em **Configurações → Logs de integração**, com segredos mascarados.
- **Celery:** `dc exec worker celery -A config inspect active`; agendamentos em `/admin/django_celery_beat/`.

## 10. Rollback

```bash
cd /srv/kscentral
git checkout v1.2.0               # versão anterior
./scripts/deploy.sh v1.2.0
```

Se a versão nova aplicou migrações incompatíveis, restaure o backup feito automaticamente no início do deploy (seção 8) **antes** de subir a versão anterior.

## 11. Solução de problemas

| Sintoma | Causa provável | Ação |
|---|---|---|
| Caddy não emite certificado | DNS ainda não propagou ou porta 80 fechada | `dig central.kstec.online`, `ufw status`, `dc logs caddy` |
| `web` não fica healthy | Erro de migração ou `.env` incompleto | `dc logs web`; `prod.py` exige `FIELD_ENCRYPTION_KEY` |
| `400 Bad Request` | Host fora de `DJANGO_ALLOWED_HOSTS` | Ajuste o `.env` e `dc up -d` |
| `403 CSRF` no login | `DJANGO_CSRF_TRUSTED_ORIGINS` sem `https://` | Ajuste o `.env` |
| Usuário bloqueado após senhas erradas | `django-axes` (5 tentativas/1h) | `dc exec web python manage.py axes_reset_username email@x` |
| Usuário perdeu o celular do MFA | — | Administrador: `/admin/otp_totp/totpdevice/` → excluir dispositivo; o usuário reconfigura no próximo login |
| NFS-e `E999` na Sefin | CNPJ não habilitado para API ou assinatura inválida | Ver plano 6.13; `testar_sefin`; conferir certificado |
| Erro ao abrir segredo (`InvalidToken`) | `FIELD_ENCRYPTION_KEY` trocada | Restaurar a chave original |
| Tarefas agendadas não rodam | `beat` parado | `dc ps beat`, `dc restart beat` |
| PDF sem fontes | Fontes ausentes na imagem | A imagem inclui DejaVu; Manrope/JetBrains são carregadas por CSS |
| Disco cheio | Logs Docker / backups | `docker system prune`, revisar retenção, `du -sh backups` |

## 12. Checklist de go-live

- [ ] DNS + HTTPS funcionando; `check --deploy` sem erros.
- [ ] `.env` com todos os segredos; cópia de `FIELD_ENCRYPTION_KEY` e `BACKUP_PASSPHRASE` no cofre.
- [ ] `seed_inicial` executado; dados da empresa conferidos (IM, regime, CNAE).
- [ ] Administrador com MFA ativo; usuários criados com papéis corretos.
- [ ] Backup diário agendado; **restauração de teste** executada e cronometrada.
- [ ] Sentry recebendo eventos (forçar um erro de teste).
- [ ] Certificado A1 carregado; `testar_sefin` OK em produção restrita.
- [ ] Protocolo fiscal 6.14.6 executado e `canal_padrao` definido.
- [ ] Sistemas monitorados cadastrados e verificações aparecendo.
- [ ] Certidões vigentes carregadas.

## 13. Referência: variáveis de ambiente

| Variável | Obrigatória | Descrição |
|---|---|---|
| `DJANGO_SETTINGS_MODULE` | sim | `config.settings.prod` na VPS |
| `DJANGO_SECRET_KEY` | sim | Chave do Django |
| `DJANGO_ALLOWED_HOSTS` | sim | Ex.: `central.kstec.online` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | sim | Ex.: `https://central.kstec.online` |
| `SITE_URL` | sim | URL pública (links de orçamento e status) |
| `DOMINIO`, `ACME_EMAIL` | sim | Usados pelo Caddy |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | sim | Banco |
| `DATABASE_URL` | sim | `postgres://kscentral:<senha>@db:5432/kscentral` |
| `REDIS_URL` | sim | `redis://redis:6379/0` |
| `FIELD_ENCRYPTION_KEY` | sim | Chave Fernet dos segredos |
| `EMAIL_URL`, `DEFAULT_FROM_EMAIL` | sim | SMTP |
| `SENTRY_DSN` | não | Observabilidade |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | não | IA nos relatórios |
| `STORAGE_BACKEND` (+ `AWS_*`) | não | `local` ou `s3` |
| `NFSE_AMBIENTE` | sim | Ambiente padrão sugerido na configuração fiscal |
| `MFA_OBRIGATORIO` | não | `True` (padrão) |
| `BACKUP_DIR`, `BACKUP_PASSPHRASE`, `BACKUP_RCLONE_REMOTE` | sim/sim/não | Backups |
| `KS_IMAGE` | não | Imagem a usar (definida pelo `deploy.sh`) |

## 14. Referência: comandos de gestão e tarefas agendadas

| Comando | Função |
|---|---|
| `seed_inicial` | Empresa KS TEC, papéis, categorias financeiras, tipos de certidão, prompts de IA |
| `importar_tabelas_fiscais <xlsx...>` | LC 116, cTribNac, NBS, correlação IBS/CBS |
| `importar_nfse_el <xml\|zip...>` | Histórico do portal E&L |
| `gerar_competencias` | Cria competências faltantes dos contratos vigentes |
| `testar_sefin` | Chamada autenticada (mTLS) em produção restrita |
| `recalcular_sla <AAAA-MM>` | Reprocessa agregados de SLA |

Tarefas do Celery beat (editáveis em `/admin/django_celery_beat/periodictask/`):

| Tarefa | Frequência |
|---|---|
| `sla.despachar_verificacoes` | 1 min |
| `sla.agregar_dia` / `sla.limpar_brutos` | diária 00:15 / 03:00 |
| `sla.verificar_ssl_todos` | diária 06:00 |
| `certidoes.alertar_vencimentos` | diária 07:00 |
| `fiscal.alertar_certificado` | diária 07:05 |
| `fiscal.criar_guias_iss` | dia 1, 08:00 |
| `fiscal.verificar_adn` | de hora em hora |
| `contratos.alertar_vigencia_saldo` | diária 07:10 |
| `financeiro.marcar_atrasados` / `gerar_recorrencias` | diária 00:30 / 00:35 |
| `comercial.expirar_orcamentos` / `followup` | diária 09:00 / 09:05 |
| `relatorios.lembrete_competencia` | dia 1, 09:00 |
| `ia.verificar_limite_custo` | diária 08:00 |
| `core.lembrete_teste_restauracao` | mensal (dia 5) |
