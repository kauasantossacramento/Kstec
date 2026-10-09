# Manual de deploy — KS CENTRAL

> **Para quem:** quem publica e administra o KS CENTRAL (você ou o próximo agente).
> **Alvo:** VPS Ubuntu 24.04 LTS com Docker Compose. **Atualizado em 09/10/2026.**
> Serviços: `web` (gunicorn) · `worker` (Celery) · `beat` (agendador) · `whatsapp` (neonize) · `db` (PostgreSQL 16) ·
> `redis` · `caddy` (HTTPS automático).

## Sumário

1. [Onde está o sistema (Git e esta máquina)](#1-onde-está-o-sistema)
2. [Fluxo Git até a produção](#2-fluxo-git-até-a-produção)
3. [Arquitetura de produção](#3-arquitetura-de-produção)
4. [Pré-requisitos](#4-pré-requisitos)
5. [Preparar a VPS](#5-preparar-a-vps)
6. [Código e `.env` na VPS](#6-código-e-env-na-vps)
7. [Primeira subida](#7-primeira-subida)
8. [Dados: banco novo **ou** migração desta máquina](#8-dados-banco-novo-ou-migração-desta-máquina)
9. [Configuração fiscal](#9-configuração-fiscal)
10. [Faturamento recorrente](#10-faturamento-recorrente)
11. [Asaas (cobrança, PIX e webhook)](#11-asaas)
12. [WhatsApp (neonize)](#12-whatsapp)
13. [Monitoramento de sistemas](#13-monitoramento-de-sistemas)
14. [Atualizações](#14-atualizações)
15. [Backups e restauração](#15-backups-e-restauração)
16. [Logs e observabilidade](#16-logs-e-observabilidade)
17. [Rollback](#17-rollback)
18. [Solução de problemas](#18-solução-de-problemas)
19. [Checklist de go-live](#19-checklist-de-go-live)
20. [Referência: variáveis de ambiente](#20-referência-variáveis-de-ambiente)
21. [Referência: comandos e tarefas agendadas](#21-referência-comandos-e-tarefas-agendadas)
22. [Ambiente local nesta máquina](#22-ambiente-local-nesta-máquina)

---

## 1. Onde está o sistema

| Item | Valor |
|---|---|
| Repositório | https://github.com/kauasantossacramento/Kstec (`origin`) |
| Branch de trabalho | **`desenvolvimento-local`** |
| Branch padrão remota | `ccr-86406a8c-5a2ak0` (base de PRs). O CI publica `:latest` apenas para `main` e tags `v*`. |
| Pasta nesta máquina | **`C:\Users\KS TEC\sistema_kstec_`** (Windows 11, PowerShell, Python 3.13 em `.venv`) |
| Pasta antiga preservada | `C:\Users\KS TEC\sistema_kstec` — não usar |
| Pasta na VPS (sugerida) | `/srv/kscentral` |
| Imagem Docker | `ghcr.io/kauasantossacramento/kscentral:<tag>` |

**Nunca vão para o Git** (estão no `.gitignore`) e precisam ser levados à mão, por canal seguro, quando necessário:

| Arquivo/pasta nesta máquina | Conteúdo | Observação |
|---|---|---|
| `.env` | Segredos locais, inclusive **`FIELD_ENCRYPTION_KEY`** | A mesma chave é obrigatória se o banco local for migrado (seção 8B). |
| `local.sqlite3` | Banco local com a configuração fiscal real, A1/token cifrados, NFS-e real nº 2600000000012 | Base da migração de dados. |
| `media\` | XML/PDF arquivados, anexos | Copiar junto com o banco. |
| `.tools\` | Backups (`.tools\backups\*.sqlite3`), evidências fiscais, WeasyPrint Windows, sessão local do WhatsApp | Não copiar para a VPS, exceto o que for pedido. |
| `KS TEC SOLUÇÕES ATÉ 08.2027 (1).pfx` | Certificado A1 original | Já está cifrado no banco; o arquivo serve só para recadastro. |

## 2. Fluxo Git até a produção

Nesta máquina (PowerShell, na pasta do projeto):

```powershell
cd "C:\Users\KS TEC\sistema_kstec_"
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=config.settings.local
.venv\Scripts\python.exe -m pytest --ds=config.settings.test_local
git status                       # confira: nada de .env, sqlite, media, .tools ou .pfx
git add -A
git commit -m "Descrição da mudança"
git push origin desenvolvimento-local
```

Depois, no GitHub:

1. Abra um **Pull Request** de `desenvolvimento-local` para a branch padrão e acompanhe o **CI** (ruff, migrações,
   testes em PostgreSQL, build da imagem). O CI nunca rodou o stack completo desta entrega — trate a primeira execução
   com atenção.
2. Após aprovar e fazer o merge, crie a **tag de versão** a partir da branch padrão:

   ```powershell
   git fetch origin
   git checkout ccr-86406a8c-5a2ak0      # ou a branch padrão vigente
   git pull
   git tag -a v1.4.0 -m "v1.4.0 — faturamento recorrente, Asaas, WhatsApp e monitoramento"
   git push origin v1.4.0
   ```

3. A tag dispara o CI (publica `ghcr.io/kauasantossacramento/kscentral:v1.4.0`) e, se o CI passar, o workflow
   **Deploy** entra na VPS por SSH e executa `scripts/deploy.sh v1.4.0` (seção 14).

> Push não é deploy: só a **tag** publica em produção. Volte para `desenvolvimento-local` depois de taguear.

## 3. Arquitetura de produção

```
Internet ──443──> caddy ──> web (gunicorn, Django) ──> db (PostgreSQL 16)
                                   │                └─> redis (cache, travas, fila Celery)
                                   ├─ worker (Celery: emissões, consultas, rotinas)
                                   ├─ beat   (agenda: DatabaseScheduler, processo único)
                                   └─ whatsapp (manage.py whatsapp_worker: sessão neonize + fila de mensagens)
Asaas ──webhook──> https://<domínio>/cobrancas/webhook/
```

Regras importantes:
- **Apenas um `beat`** e **apenas um `whatsapp`** por número. Não escale esses serviços.
- `worker` pode ter réplicas: todas as rotinas usam **trava distribuída no Redis** e são idempotentes.
- Somente o `web` aplica migrações (`RUN_MIGRATIONS=1`).
- A sessão do WhatsApp fica no volume `whatsapp` (`/app/data/whatsapp/sessao.sqlite3`).

## 4. Pré-requisitos

| Item | Detalhe |
|---|---|
| VPS | 2 vCPU, 4 GB RAM, 40 GB SSD (ex.: Hetzner CX22). Com muitos sistemas monitorados, 4 GB+ livres. |
| DNS | Registro `A` (e `AAAA`) de `central.kstec.online` para o IP da VPS. |
| Portas | 22 (SSH restrito), 80 e 443. |
| Contas | GitHub (repositório e GHCR), SMTP, Asaas (Sandbox e Produção), chip dedicado ao WhatsApp, Sentry (opcional), destino externo de backup (Nextcloud/S3 via rclone). |
| Fiscal | A1 ICP-Brasil da empresa (já cifrado no banco local), token municipal E&L, percentuais vigentes informados pelo contador. |

## 5. Preparar a VPS

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

timedatectl set-timezone America/Bahia
```

Endureça o SSH (`/etc/ssh/sshd_config`: `PasswordAuthentication no`, `PermitRootLogin no`) **depois** de confirmar o
login por chave com o usuário `ks`, e reinicie com `systemctl restart ssh`.

## 6. Código e `.env` na VPS

```bash
sudo mkdir -p /srv/kscentral && sudo chown ks:ks /srv/kscentral
su - ks
git clone https://github.com/kauasantossacramento/Kstec.git /srv/kscentral
cd /srv/kscentral
git checkout v1.4.0            # a tag que será publicada
cp .env.example .env && chmod 600 .env
```

Gerar segredos:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"          # DJANGO_SECRET_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(32))"          # POSTGRES_PASSWORD e BACKUP_PASSPHRASE
python3 -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"   # FIELD_ENCRYPTION_KEY (banco novo)
```

> ⚠️ **`FIELD_ENCRYPTION_KEY`**: se for migrar o banco desta máquina (seção 8B), use **exatamente** o valor do
> `.env` local (`C:\Users\KS TEC\sistema_kstec_\.env`). Outra chave torna ilegíveis o A1, a senha do A1, o token
> municipal, a chave do Asaas e o token do webhook. Guarde-a num cofre de senhas, fora da VPS.

Preencha no mínimo: `DJANGO_SETTINGS_MODULE=config.settings.prod`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`,
`DJANGO_CSRF_TRUSTED_ORIGINS`, `SITE_URL` (https, usado em links e no aviso do webhook), `DOMINIO`, `ACME_EMAIL`,
`POSTGRES_PASSWORD`, `DATABASE_URL`, `REDIS_URL`, `FIELD_ENCRYPTION_KEY`, `EMAIL_URL`, `DEFAULT_FROM_EMAIL`,
`BACKUP_PASSPHRASE`. Ver [seção 20](#20-referência-variáveis-de-ambiente). No `EMAIL_URL`, codifique caracteres
especiais (`@` → `%40`).

## 7. Primeira subida

```bash
echo 'alias dc="docker compose -f /srv/kscentral/docker/compose.yml --env-file /srv/kscentral/.env"' >> ~/.bashrc
source ~/.bashrc

# Se o pacote GHCR for privado:
echo <TOKEN_read:packages> | docker login ghcr.io -u <usuario-github> --password-stdin

# Imagem publicada pelo CI…
KS_IMAGE=ghcr.io/kauasantossacramento/kscentral:v1.4.0 dc pull
KS_IMAGE=ghcr.io/kauasantossacramento/kscentral:v1.4.0 dc up -d
# …ou build na própria VPS
dc up -d --build
```

O `web` aplica migrações e `collectstatic`. Verifique:

```bash
dc ps                                    # web healthy; worker, beat, whatsapp, db, redis, caddy running
curl -s https://central.kstec.online/health
dc exec web python manage.py check --deploy
dc logs --tail 50 beat worker whatsapp
```

O `whatsapp` sobe e aguarda: a configuração nasce **desativada** e nada é enviado até você ativar (seção 12).

## 8. Dados: banco novo **ou** migração desta máquina

Escolha **um** dos caminhos.

### 8A. Banco novo

```bash
dc exec web python manage.py seed_inicial         # empresa, papéis, categorias, tipos de certidão
dc exec web python manage.py createsuperuser
# Tabelas fiscais oficiais (os XLSX não estão no Git):
dc cp ANEXO_B-NBS2-LISTA_SERVICO_NACIONAL.xlsx web:/tmp/
dc cp AnexoVIII-CorrelacaoItemNBSIndOpCClassTrib_IBSCBS.xlsx web:/tmp/
dc exec web python manage.py importar_tabelas_fiscais /tmp/ANEXO_B-NBS2-LISTA_SERVICO_NACIONAL.xlsx \
    /tmp/AnexoVIII-CorrelacaoItemNBSIndOpCClassTrib_IBSCBS.xlsx
# Referências municipais (Valença/BA, LC 010/2021), sem confirmar códigos automaticamente:
dc cp anexo_municipal.pdf web:/tmp/
dc exec web python manage.py importar_servicos_municipais /tmp/anexo_municipal.pdf --municipio 2932903 \
    --fonte "LC municipal 010/2021, Anexo I"
```

Depois cadastre A1, token e percentuais na tela (seção 9) e confirme o código municipal `101` do serviço TI-DEV.

### 8B. Migrar o banco desta máquina (SQLite → PostgreSQL)

Leva a configuração fiscal real, a NFS-e já emitida, cadastros, tabelas fiscais importadas e históricos.
**Ensaie primeiro em uma VPS/compose de homologação.**

Nesta máquina (PowerShell):

```powershell
cd "C:\Users\KS TEC\sistema_kstec_"
# pare o runserver local antes, para o banco não mudar durante a exportação
New-Item -ItemType Directory -Force .tools\migracao | Out-Null
Copy-Item local.sqlite3 .tools\backups\antes-migracao-producao.sqlite3
.venv\Scripts\python.exe -X utf8 manage.py dumpdata --natural-foreign --natural-primary `
  -e contenttypes -e auth.permission -e sessions -e admin.logentry -e axes -e django_celery_beat `
  --indent 1 -o .tools\migracao\dados.json --settings=config.settings.local
Compress-Archive -Path media\* -DestinationPath .tools\migracao\media.zip -Force
Get-FileHash .tools\migracao\dados.json, .tools\migracao\media.zip -Algorithm SHA256
```

Transfira `dados.json` e `media.zip` por canal seguro (ex.: `scp`) — contêm CPF de tomador e documentos fiscais.

Na VPS, com o `.env` usando a **mesma `FIELD_ENCRYPTION_KEY`** e o banco **recém-migrado e vazio**
(não rode `seed_inicial` neste caminho):

```bash
sha256sum dados.json media.zip                    # compare com os hashes locais
dc cp dados.json web:/tmp/dados.json
dc exec web python manage.py loaddata /tmp/dados.json
unzip media.zip -d media_migrada
dc cp media_migrada/. web:/app/media/
dc exec -u root web chown -R ks:ks /app/media
dc exec web python manage.py check --deploy
dc exec web rm /tmp/dados.json && rm -rf dados.json media.zip media_migrada
```

Conferências obrigatórias após a migração:
- **Fiscal → Configuração**: checklist verde, A1 legível e dentro da validade, token presente.
- Abrir a NFS-e nº 2600000000012 e baixar o PDF (confirma mídia e hashes).
- **Nunca retransmitir** essa nota; ela já está autorizada.
- Usuários conseguem entrar; Administrador/Fiscal/Financeiro configuram o MFA no primeiro acesso.

## 9. Configuração fiscal

Tela **Fiscal → Configuração** (papel Fiscal). Campos reais:

| Campo | Produção atual |
|---|---|
| Canal padrão | `Municipal E&L — DPS nacional` (o emissor nacional direto retornou E0039 — município não habilitado) |
| Ambiente | `Produção` (1) |
| Série DPS | `1` |
| Certificado / novo A1 + senha | A1 cifrado; recusa A1 vencido ou de outro CNPJ |
| Novo token municipal | Token E&L (cifrado) |
| ISS padrão / Tributos aproximados do Simples | **2% / 6%**, com fonte e vigência **01–31/10/2026** |
| Perfil padrão, conta de recebimento, prazo | Conferir antes de faturar |

> A cada mês, **atualize percentuais e vigência** com o contador. Sem isso, o checklist falha e os ciclos do
> faturamento recorrente ficam **Bloqueados** (comportamento intencional — nenhuma nota sai com percentual vencido).

Diagnóstico sem emitir: `dc exec web python manage.py diagnosticar_nfse <arquivo.pfx>` e
`dc exec web python manage.py consultar_dps_el <idDPS> --ambiente 1`.

## 10. Faturamento recorrente

1. Contrato **vigente** com cliente, valor e saldo corretos; item do catálogo sem pendências fiscais.
2. **Faturamento → Nova agenda** (ou aba Faturamento do contrato): siga os 4 passos e confira a prévia.
3. Comece no modo **Confirmar**: o sistema prepara e valida a nota no dia programado e pede sua confirmação na tela
   ou no WhatsApp (`SIM <código>`).
4. Confirme que o `beat` está ativo: `/admin/django_celery_beat/periodictask/` deve listar
   `faturamento.planejar_ciclos`, `faturamento.processar_ciclos`, `faturamento.acompanhar_transmissoes`.
5. Acompanhe em **Faturamento** (pendências, bloqueios) e **Previsão de recebimentos**.

## 11. Asaas

1. **Configurações → Cobrança Asaas**: ambiente **Sandbox** primeiro, chave de API, forma padrão, multa/juros,
   baixa automática e **conta da baixa** (crie a conta "Asaas" no financeiro). Salve e clique em **Testar conexão**.
2. Copie a **URL** (`https://central.kstec.online/cobrancas/webhook/`) e o **token** exibidos na tela para
   Asaas → Integrações → Webhooks (cobranças), versão de API v3, eventos de pagamento.
3. Teste: gere uma cobrança num lançamento de receita, pague no Sandbox e verifique a baixa e o aviso.
4. Para produção, troque o ambiente e a chave. Cobranças do Sandbox não migram.

## 12. WhatsApp

> WhatsApp Web via neonize **não é API oficial**. Use chip dedicado, com nome e foto da empresa, aquecido com
> conversas reais. Comece com limites baixos.

1. **Configurações → WhatsApp**: marque *WhatsApp ativo*, transporte **WhatsApp Web (neonize)**, informe **meus
   números**, revise janela, limites, confirmação e automações. Salve.
2. Reinicie o serviço para carregar o transporte: `dc restart whatsapp`.
3. Abra **WhatsApp** no sistema: o QR Code aparece (atualiza sozinho). No celular: *Aparelhos conectados → Conectar
   aparelho*. O estado muda para **Conectado**.
4. **Enviar teste para meus números**; responda `ajuda` para testar os comandos.
5. Cadastre contatos dos clientes com **consentimento e origem** (Cadastros → cliente → Comunicação e cobrança).

Operação:
- Logs: `dc logs -f whatsapp`. Pausa de emergência: envie `pausar` do seu número (ou use o botão de configuração).
- Sessão perdida (desconectado no celular): reabra a tela e leia o QR novamente.
- Trocar de número: `dc stop whatsapp`, `docker volume rm kscentral_whatsapp`, `dc up -d whatsapp`, ler o QR.
- Nunca rode dois `whatsapp_worker` para o mesmo número (a trava no Redis impede no mesmo ambiente).

## 13. Monitoramento de sistemas

**Monitoramento → Sistema**: URL, status HTTP esperado, texto esperado (opcional), intervalo, limite de lentidão,
falhas seguidas para alertar, alerta no WhatsApp e vínculo ao contrato. O `beat` verifica a cada minuto os sistemas
vencidos. Cadastre também o próprio KS CENTRAL num monitor **externo** (o monitor interno não avisa se ele cair).

## 14. Atualizações

Por tag (padrão): ver seção 2. O `scripts/deploy.sh <tag>` faz backup, `pull` de `web worker beat whatsapp`,
`up -d --no-build` e `check --deploy`.

Segredos do workflow (GitHub → Settings → Environments → `producao`): `VPS_HOST`, `VPS_USER` (`ks`),
`VPS_SSH_KEY` (chave dedicada; a pública em `~ks/.ssh/authorized_keys`).

Manual:

```bash
cd /srv/kscentral && git fetch --tags && git checkout v1.4.0
./scripts/deploy.sh v1.4.0
```

## 15. Backups e restauração

`scripts/backup.sh` gera `pg_dump` + mídia, cifrados com AES-256 (`BACKUP_PASSPHRASE`), retenção 30 diários +
12 mensais, e envia ao destino `rclone` se `BACKUP_RCLONE_REMOTE` estiver definido.

```bash
crontab -e
15 2 * * * cd /srv/kscentral && ./scripts/backup.sh >> /srv/kscentral/backups/backup.log 2>&1
```

Teste mensal (não toca a produção): `./scripts/restore.sh backups/diario/<arquivo>.tar.gz.enc --teste`.
Desastre: `./scripts/restore.sh backups/diario/<arquivo>.tar.gz.enc` (digite `RESTAURAR`).

> A sessão do WhatsApp **não** entra no backup: após restaurar em outra VPS, leia o QR de novo.
> Guarde `BACKUP_PASSPHRASE` e `FIELD_ENCRYPTION_KEY` fora da VPS. Documentos fiscais têm retenção de 5 anos.

## 16. Logs e observabilidade

```bash
dc logs -f web
dc logs -f worker beat
dc logs -f whatsapp
dc exec worker celery -A config inspect active
```

- `/health` verifica banco e cache.
- **Configurações → Logs de integração**: chamadas E&L, Asaas, BrasilAPI etc., com segredos mascarados.
- `SENTRY_DSN` habilita Sentry (sem PII).

## 17. Rollback

```bash
cd /srv/kscentral
git checkout v1.3.0
./scripts/deploy.sh v1.3.0
```

Se a versão nova aplicou migrações incompatíveis, restaure o backup feito no início do deploy **antes** de subir a
versão anterior. Ciclos de faturamento já transmitidos continuam válidos: consulte-os, não reenvie.

## 18. Solução de problemas

| Sintoma | Causa provável | Ação |
|---|---|---|
| Caddy sem certificado | DNS não propagou / porta 80 fechada | `dig`, `ufw status`, `dc logs caddy` |
| `web` não fica healthy | `.env` incompleto ou migração falhou | `dc logs web`; `prod.py` exige `FIELD_ENCRYPTION_KEY` |
| `400` / `403 CSRF` | Host ou origem ausente | `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` com `https://` |
| `InvalidToken` ao abrir segredos | `FIELD_ENCRYPTION_KEY` diferente | Restaurar a chave original |
| Ciclos **Bloqueados** em massa | Percentuais fiscais fora da vigência, A1 vencido, saldo/vigência do contrato | Ver mensagem do ciclo; corrigir e clicar **Emitir agora** |
| Ciclo em **Transmitido** por muito tempo | Emissor sem resposta | Consulta automática a cada 10 min; após 3 dias, consultar a DPS manualmente |
| Agendamentos não rodam | `beat` parado ou Redis fora | `dc ps beat redis`, `dc restart beat` |
| WhatsApp "Worker desligado" | Serviço parado | `dc ps whatsapp`, `dc logs whatsapp`, `dc restart whatsapp` |
| WhatsApp não envia a clientes | Fora da janela, limite atingido, fila pausada, contato sem consentimento | Painel WhatsApp (ritmo seguro), enviar `retomar` |
| Webhook Asaas `401` | Token diferente | Copiar novamente o token da tela de configuração |
| Usuário bloqueado | `django-axes` | `dc exec web python manage.py axes_reset_username email@x` |
| MFA perdido | — | `/admin/otp_totp/totpdevice/` → excluir dispositivo |

## 19. Checklist de go-live

- [ ] Tag publicada pelo CI; `check --deploy` sem erros; HTTPS ok.
- [ ] `.env` completo; `FIELD_ENCRYPTION_KEY` e `BACKUP_PASSPHRASE` no cofre.
- [ ] Dados: seção 8A **ou** 8B concluída e conferida; NFS-e real visível com PDF.
- [ ] Usuários com papéis e MFA.
- [ ] Configuração fiscal com checklist verde e percentuais da competência vigente.
- [ ] Beat listando as tarefas de faturamento, WhatsApp e monitoramento.
- [ ] Primeira agenda no modo **Confirmar** e prévia conferida.
- [ ] Asaas testado no Sandbox (cobrança, pagamento, webhook, baixa) antes da produção.
- [ ] WhatsApp conectado, teste recebido, comandos respondendo; contatos com consentimento.
- [ ] Sistemas monitorados cadastrados; monitor externo do próprio KS CENTRAL.
- [ ] Backup agendado e restauração de teste executada.

## 20. Referência: variáveis de ambiente

| Variável | Obrigatória | Descrição |
|---|---|---|
| `DJANGO_SETTINGS_MODULE` | sim | `config.settings.prod` |
| `DJANGO_SECRET_KEY` | sim | Chave do Django |
| `DJANGO_ALLOWED_HOSTS` / `DJANGO_CSRF_TRUSTED_ORIGINS` | sim | `central.kstec.online` / `https://central.kstec.online` |
| `SITE_URL` | sim | URL pública https (links, avisos, webhook) |
| `DOMINIO`, `ACME_EMAIL` | sim | Caddy |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DATABASE_URL` | sim | Banco |
| `REDIS_URL` | sim | `redis://redis:6379/0` (cache, travas, broker) |
| `FIELD_ENCRYPTION_KEY` | sim | Chave Fernet dos segredos (A1, tokens, Asaas) |
| `EMAIL_URL`, `DEFAULT_FROM_EMAIL` | sim | SMTP |
| `WHATSAPP_SESSAO` | não | Caminho da sessão neonize (no compose: `/app/data/whatsapp/sessao.sqlite3`) |
| `NFSE_AMBIENTE` | sim | Ambiente sugerido na configuração fiscal |
| `SENTRY_DSN` | não | Observabilidade |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | não | IA |
| `STORAGE_BACKEND` (+ `AWS_*`) | não | `local` ou `s3` |
| `MFA_OBRIGATORIO` | não | `True` (padrão) |
| `BACKUP_DIR`, `BACKUP_PASSPHRASE`, `BACKUP_RCLONE_REMOTE` | sim/sim/não | Backups |
| `KS_IMAGE` | não | Definida pelo `deploy.sh` |
| `KSCENTRAL_REDIS`, `KSCENTRAL_EMAIL_REAL` | — | Apenas perfil local |

## 21. Referência: comandos e tarefas agendadas

| Comando (`dc exec web python manage.py …`) | Função |
|---|---|
| `seed_inicial` | Empresa, papéis, categorias, tipos de certidão |
| `importar_tabelas_fiscais <xlsx…>` | LC 116, cTribNac, NBS, correlações |
| `importar_servicos_municipais <arq> --municipio --fonte [--confirmar-codigos]` | Referências municipais |
| `importar_nfse_nacional <xml> --cnpj --canal` | Importa NFS-e autorizada (sem emitir) |
| `importar_nfse_adn [--desde AAAA-MM-DD] [--simular] [--ignorar N]` | Sincroniza do ADN as NFS-e emitidas pela empresa (inclusive no portal), com canceladas |
| `consultar_dps_el <idDPS> --ambiente 1` | Consulta DPS no canal E&L (sem emitir) |
| `diagnosticar_nfse <pfx>` | Valida A1 e acesso às documentações (sem emitir) |
| `gerar_competencias` | Competências faltantes dos contratos |
| `whatsapp_worker [--simulado] [--uma-vez]` | Processo do WhatsApp (já roda como serviço) |

Tarefas do beat (editáveis em `/admin/django_celery_beat/periodictask/`):

| Tarefa | Frequência |
|---|---|
| `faturamento.planejar_ciclos` | diária 00:40 |
| `faturamento.processar_ciclos` | a cada 15 min |
| `faturamento.acompanhar_transmissoes` | a cada 10 min |
| `mensageria.rotinas_whatsapp` (lembretes, resumo, expiração) | a cada 10 min |
| `sla.despachar_verificacoes` | 1 min |
| `sla.limpar_brutos` / `sla.verificar_ssl_todos` | 03:00 / 06:00 |
| `certidoes.alertar_vencimentos` | 07:00 |
| `contratos.alertar_vigencia_saldo` | 07:10 |
| `financeiro.marcar_atrasados` / `gerar_recorrencias` | 00:30 / 00:35 |
| `comercial.expirar_orcamentos` / `followup` | 09:00 / 09:05 |
| `core.lembrete_teste_restauracao` | dia 5, 08:30 |

## 22. Ambiente local nesta máquina

```powershell
cd "C:\Users\KS TEC\sistema_kstec_"
.venv\Scripts\python.exe manage.py migrate --settings=config.settings.local
.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000 --noreload --settings=config.settings.local
# Acesse http://localhost:8000/ (use localhost: em 127.0.0.1 há service worker de outro sistema)
```

- Sem Redis: tarefas síncronas; use **Faturamento → Executar rotina agora** e **WhatsApp → Rodar rotinas**.
- Com Redis local (Memurai, WSL ou `docker run -p 6379:6379 redis:7-alpine`): defina `KSCENTRAL_REDIS=True` no
  `.env`, rode `.\scripts\iniciar_workers.ps1` (Celery worker `-P solo`, beat e WhatsApp; logs em `.\logs`) e reinicie o
  `runserver` para compartilhar o mesmo cache/travas. `-ZapSimulado` testa o WhatsApp sem conectar o celular.
- O `runserver` usa `--noreload`: reinicie após mudar código Python. Identifique o processo pelo caminho antes de
  encerrar — não pare servidores de outros projetos.
