# KS CENTRAL — o que foi feito no deploy, e como atualizar

**Sistema:** KS CENTRAL (gestão da KS TEC) · **Endereço:** https://gestao.kstec.online
**Implantado em:** 09/10/2026 · **Servidor:** `65.108.46.17` (Hetzner, compartilhado)

Documento de passagem. Serve para qualquer agente ou pessoa que pegue a
operação deste sistema sem contexto anterior.

> Este arquivo **não contém segredo nenhum** e não deve passar a conter.
> Senhas e chaves ficam onde a seção 2 indica — aqui só o caminho delas.

---

## 1. A regra que vale mais que o resto

**Este servidor não é só do KS CENTRAL.** Ele hospeda, na mesma máquina:

| Produto | O que é |
|---|---|
| **Nuvem.center** | SaaS de nuvem de arquivos. Inclui `bomjesusdalapa`, a Prefeitura de Bom Jesus da Lapa, cujo endereço `/s/FPnJNyXSk3KrsS4` é **prestação de contas compartilhada com a Polícia Federal** |
| **CONMAC** | Cliente com ~313 GB de acervo |
| **AgroCampo** | Loja Django de outro cliente |
| **Ello+** | SaaS para produtoras musicais |
| **KS CENTRAL** | Este sistema |

Três consequências práticas:

1. **Nada que derrube serviço entre 08:00 e 19:00.** Regra permanente do dono.
   Fora desse horário, à vontade.
2. **Nunca mexer nas portas 80/443.** São do Traefik, que atende todos os
   produtos acima. Ver seção 4.
3. **Em 09/10/2026 o disco encheu e derrubou TODOS os clientes por 65 minutos**,
   incluindo o link da PF. Antes de qualquer coisa que ocupe espaço, confira
   `df -h /`. Ver seção 10.

---

## 2. Acesso

### Servidor

```bash
ssh -i "C:/Users/KS TEC/Downloads/agrocampo_zip2/agrocampo/deploy/chaves/nuvem-center-prod" root@65.108.46.17
```

| | |
|---|---|
| IP | `65.108.46.17` |
| Usuário | `root` |
| Chave privada | `C:\Users\KS TEC\Downloads\agrocampo_zip2\agrocampo\deploy\chaves\nuvem-center-prod` |

É a chave **root do servidor inteiro**, não só deste produto. No Windows o
OpenSSH recusa a chave se outros usuários puderem lê-la. Se der
`UNPROTECTED PRIVATE KEY FILE`, copie para uma pasta temporária e restrinja:

```powershell
icacls <arquivo> /inheritance:r /grant:r "%USERNAME%:(R)"
```

### Onde estão as credenciais (só o caminho)

| O quê | Onde |
|---|---|
| Variáveis de produção do KS CENTRAL | `/opt/kscentral/.env` (modo 600, no servidor) |
| `FIELD_ENCRYPTION_KEY` original | `C:\Users\KS TEC\sistema_kstec_\.env` (máquina de desenvolvimento) |
| Certificado A1 (arquivo) | `C:\Users\KS TEC\sistema_kstec_\KS TEC SOLUÇÕES ATÉ 08.2027 (1).pfx` |
| Senha do A1 e token E&L | Cifrados no banco; leia com `decifrar_texto()` / `.ler()` — ver seção 8 |
| Acesso administrativo do sistema | `kaua@kstec.online` |

> **A `FIELD_ENCRYPTION_KEY` é a peça mais crítica deste deploy.** Ela cifra o
> certificado A1, a senha do A1, o token municipal, a chave do Asaas e o token
> do webhook. Trocá-la torna tudo isso ilegível, sem recuperação. Ela já está
> no `.env` do servidor, copiada da máquina de desenvolvimento. **Guarde uma
> cópia fora do servidor**, num cofre de senhas.

---

## 3. Onde o sistema mora

```
NA MÁQUINA DE DESENVOLVIMENTO (Windows)
C:\Users\KS TEC\sistema_kstec_\        projeto, branch `desenvolvimento-local`
├── .env                               FIELD_ENCRYPTION_KEY (nunca versionar)
├── local.sqlite3                      banco local, fonte da migração
├── media\                             anexos e certidões
└── KS TEC SOLUÇÕES ATÉ 08.2027 (1).pfx

NO SERVIDOR
/opt/kscentral/                        código (árvore de trabalho, não clone git)
├── .env                               modo 600 — segredos de produção
├── docker-compose.servidor.yml        ← USE ESTE, não docker/compose.yml
├── docker/Dockerfile                  imagem
├── backups/                           destino do scripts/backup.sh (vazio ainda)
└── apps/ config/ static/ ...

/opt/nuvem-center/docker/traefik/dynamic/kscentral.yml    a rota HTTPS
```

| Recurso | Nome |
|---|---|
| Imagem | `kscentral/app:latest` (811 MB, **construída no servidor**, não vem do GHCR) |
| Contêineres | `kscentral-web`, `-worker`, `-beat`, `-whatsapp`, `-db`, `-redis` |
| Redes | `kscentral_interna` (privada) + `nuvem_net` (só o `web`) |
| Volumes | `kscentral_pgdata` (79 M), `kscentral_media` (2,6 M), `kscentral_redisdata`, `kscentral_whatsapp` |
| Certificado TLS | Let's Encrypt, válido até **07/01/2027**, renovado pelo Traefik |

---

## 4. O que mudou em relação ao `deploy.md` oficial

O manual do sistema (`deploy.md`, seção 3) pressupõe uma VPS dedicada com
**Caddy** publicando 80/443. Aqui isso não funciona, e a adaptação é a
principal coisa que um agente futuro precisa entender.

### O Caddy saiu

As portas 80/443 são do **Traefik**, que atende a prefeitura, o CONMAC, o
AgroCampo e o Ello. Subir o Caddy não daria "conflito de configuração":
daria porta ocupada, e o KS CENTRAL não subiria — ou pior, se alguém parasse
o Traefik para liberar a porta, derrubaria todos os outros produtos.

No lugar: **um arquivo novo** em `/opt/nuvem-center/docker/traefik/dynamic/`,
que o Traefik carrega sozinho (`watch: true`), **sem restart**. Mesmo padrão
do `agrocampo.yml`, `conmac-gestao.yml` e `ello.yml`.

### O que se perdeu com o Caddy

O `Caddyfile` fazia três coisas: TLS (o Traefik faz), cabeçalhos de segurança
(o Traefik faz) e servir `/media/publico/*` como arquivo estático. **Esta
terceira não está coberta.**

Hoje não quebra nada: `media/publico` não existe e nada no código escreve lá
— o caminho só aparece em `ROTAS_LIVRES` do middleware. Os 47 arquivos de
mídia são anexos e certidões, **privados**, servidos pelo Django com
verificação de permissão. Os estáticos normais continuam no WhiteNoise.

> Se algum dia algo passar a gravar em `/media/publico`, vai dar **404** — de
> forma visível, não em silêncio. A solução seria WhiteNoise com raiz própria
> ou um servidor estático dedicado. **Não** monte o volume inteiro de mídia
> no WhiteNoise: isso tornaria os anexos privados públicos.

### Outras diferenças

| Item | No manual | Aqui |
|---|---|---|
| Domínio | `central.kstec.online` | **`gestao.kstec.online`** |
| Pasta | `/srv/kscentral` | **`/opt/kscentral`** |
| Imagem | `ghcr.io/kauasantossacramento/kscentral:<tag>` | construída localmente |
| Compose | `docker/compose.yml` | **`docker-compose.servidor.yml`** |
| Usuário | `ks` (não-root) | `root` (padrão deste servidor) |

### Tetos de recurso

Acrescentados para que o KS CENTRAL não vire lentidão para os vizinhos:

| Serviço | CPU | Memória | Uso real medido |
|---|---|---|---|
| web | 2.0 | 1536 M | 292 MB |
| worker | 1.5 | 1536 M | 198 MB |
| beat | 0.5 | 512 M | 103 MB |
| whatsapp | 0.5 | 512 M | 95 MB |
| db | 1.0 | 1024 M | 59 MB |
| redis | 0.5 | 256 M | 10 MB |

Somados: **~757 MB** de 62 GB do host.

---

## 5. Os dados que vieram da máquina local

Caminho **8B** do manual (migração), não 8A (banco novo). `seed_inicial`
**não** foi executado.

```
3.302 registros    (dumpdata, sem contenttypes/permissions/sessions/axes/beat)
   16 notas fiscais (11 autorizadas, 5 canceladas — todas importadas do ADN)
   47 arquivos de mídia (anexos e certidões)
  242 códigos LC 116
```

Hashes SHA-256 conferidos nos dois lados antes e depois da transferência. Os
arquivos de transferência (`dados.json`, `media.tar`) foram **removidos com
`shred`** do servidor — continham CPF de tomador e documentos fiscais.

### Conferência que prova que a chave de cifra está certa

```
A1 ........... decifrou, 5.092 bytes · CNPJ 62501281000113 · válido até 17/08/2027
senha do A1 .. decifrou, 8 caracteres
token E&L .... decifrou, 36 caracteres
ISS 2% · Simples 6% · vigência 01–31/10/2026 · ambiente 1 · canal MUNICIPAL_EL
```

**Se um dia esses campos vierem como `InvalidToken`, a `FIELD_ENCRYPTION_KEY`
foi trocada.** Restaure a original; não há outro caminho.

---

## 6. Correções que precisei fazer no código

Ambas estão aplicadas no servidor **e** na máquina de desenvolvimento.
**Ainda não foram commitadas** no repositório `kauasantossacramento/Kstec`.

### 6.1 `chart-4.4.7.umd.min.js` derrubava o contêiner

`static/vendor/chart-4.4.7.umd.min.js` terminava com
`//# sourceMappingURL=chart.umd.js.map`, e esse `.map` não é distribuído. O
`CompressedManifestStaticFilesStorage` do WhiteNoise tenta reescrever a
referência e falha:

```
whitenoise.storage.MissingFileError: The file 'vendor/chart.umd.js.map' could not be found
```

O contêiner entrava em `Restarting` sem parar. **Isso falharia em qualquer
deploy de produção** — localmente passa porque `settings.local` e
`settings.dev` não usam o storage com manifesto. Removi a referência, que sem
o arquivo é inútil.

### 6.2 Migração pendente em `faturamento`

Havia mudança de modelo sem migração (`discriminacao`, só `help_text`).
Gerei `apps/faturamento/migrations/0002_alter_agendafaturamento_discriminacao_and_more.py`
e apliquei. **É no-op no banco** (`-- (no-op)` nas duas operações).

### 6.3 Finais de linha

A máquina de desenvolvimento tem `core.autocrlf=true`, então `docker/entrypoint.sh`
chega com CRLF e o contêiner não sobe (`#!/bin/sh^M`). **222 arquivos**
precisaram de conversão. Se for reenviar código do Windows, converta:

```bash
find /opt/kscentral -type f \( -name "*.sh" -o -name "*.py" -o -name "*.yml" \
  -o -name "Dockerfile" \) -exec sed -i 's/\r$//' {} +
```

---

## 7. Como atualizar

### 7.1 Pelo Git (o caminho do manual, quando o CI estiver em uso)

O `deploy.md` descreve: commit → PR → merge → **tag** → o CI publica
`ghcr.io/kauasantossacramento/kscentral:<tag>` e o workflow **Deploy** entra
na VPS. **Esse caminho não está configurado para este servidor** — não há
segredos `VPS_HOST`/`VPS_USER`/`VPS_SSH_KEY` apontando para cá, e a imagem é
construída localmente. Se quiser usá-lo, configure os segredos do ambiente
`producao` no GitHub.

### 7.2 Enviando da máquina de desenvolvimento (o caminho usado hoje)

É o que funciona agora. Da máquina Windows, no Git Bash:

```bash
CHAVE="C:/Users/KS TEC/Downloads/agrocampo_zip2/agrocampo/deploy/chaves/nuvem-center-prod"
PROJ="/c/Users/KS TEC/sistema_kstec_"

# 1. Empacotar a árvore de trabalho, SEM segredos nem dados
cd "$PROJ"
tar -cf /tmp/ks.tar \
  --exclude=.git --exclude=.venv --exclude=.tools --exclude=media \
  --exclude=.env --exclude='*.sqlite3' --exclude='*.pfx' \
  --exclude=__pycache__ --exclude='*.pyc' --exclude=staticfiles \
  --exclude=logs --exclude=backups --exclude="docs/*.pdf" .

# 2. Conferir que nada sensível entrou
tar -tf /tmp/ks.tar | grep -iE '^\./\.env$|\.sqlite3|\.pfx' && echo "ABORTE" || echo "limpo"

# 3. Enviar e extrair (o .env do servidor NÃO é tocado)
scp -i "$CHAVE" /tmp/ks.tar root@65.108.46.17:/tmp/ks.tar
ssh -i "$CHAVE" root@65.108.46.17 'bash -s' <<'FIM'
cd /opt/kscentral
docker tag kscentral/app:latest kscentral/app:anterior   # para rollback
tar -xf /tmp/ks.tar && rm -f /tmp/ks.tar
# CRLF -> LF, senão o entrypoint não roda
find . -type f \( -name "*.sh" -o -name "*.py" -o -name "*.yml" -o -name "*.yaml" \
  -o -name "*.txt" -o -name "*.toml" -o -name "*.html" -o -name "*.json" \
  -o -name "Dockerfile" \) -exec sed -i 's/\r$//' {} +
chmod +x docker/entrypoint.sh scripts/*.sh 2>/dev/null
docker build -f docker/Dockerfile -t kscentral/app:latest .
docker compose -f docker-compose.servidor.yml up -d
FIM
```

O `web` aplica `migrate` e `collectstatic` sozinho no start
(`RUN_MIGRATIONS=1` no entrypoint). **Só o `web`** aplica migrações — é
proposital, para worker e beat não correrem juntos.

### 7.3 Conferir que deu certo

```bash
ssh -i "$CHAVE" root@65.108.46.17 'bash -s' <<'FIM'
docker ps --filter name=kscentral --format "  {{.Names}} {{.Status}}"
docker logs kscentral-web 2>&1 | grep -iE "error|traceback|not yet reflected|Listening" | tail -5
curl -s -o /dev/null -w "  gestao.kstec.online: %{http_code} em %{time_total}s\n" https://gestao.kstec.online/health
# e os vizinhos, que não podem ter sido afetados:
for h in bomjesusdalapa.nuvem.center conmac.nuvem.center agrocampo.online ello.nuvem.center; do
  printf "  %-30s %s\n" "$h" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 https://$h/)"
done
curl -s -o /dev/null -w "  LINK DA PF: %{http_code}\n" https://bomjesusdalapa.nuvem.center/s/FPnJNyXSk3KrsS4
FIM
```

`web` e `worker` devem ficar **healthy**; `beat` e `whatsapp` não têm
healthcheck (`disable: true`) e aparecem só como `Up` — é esperado.

### 7.4 Rollback

```bash
cd /opt/kscentral
docker tag kscentral/app:anterior kscentral/app:latest
docker compose -f docker-compose.servidor.yml up -d
```

Se a versão nova aplicou migração incompatível, restaure o banco **antes** de
voltar a imagem:

```bash
docker exec kscentral-db pg_dump -U kscentral kscentral | gzip > /opt/kscentral/backups/antes.sql.gz
```

---

## 8. Emissão fiscal — o que já foi testado

### O teste que foi feito, e por quê

Foi emitida uma nota de **R$ 1,00 em homologação**, não em produção. A razão:
uma NFS-e em produção **não se descarta**, só se cancela, e o cancelamento é
ato fiscal público.

O sistema tem ferramenta própria para isso —
`apps/fiscal/services/homologacao.py`: *"DPS de teste de R$ 1,00,
exclusivamente em produção restrita… não alteram o cadastro da empresa"*.

```bash
# No contêiner. A senha do A1 e o token saem do banco, nunca de log.
cd /app
creds=$(python -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.prod'); django.setup()
from apps.core.cripto import decifrar_texto
from apps.fiscal.models import CertificadoDigital, ConfiguracaoFiscal
print(decifrar_texto(CertificadoDigital.objects.filter(ativo=True).first().senha_criptografada))
print(ConfiguracaoFiscal.objects.select_related('token_municipal').first().token_municipal.ler())")
export KSCENTRAL_A1_SENHA="$(echo "$creds" | sed -n 1p)"
export KSCENTRAL_EL_TOKEN="$(echo "$creds" | sed -n 2p)"
python manage.py testar_emissao_el <caminho-do-pfx> --tomador 54575214515 --enviar-homologacao
```

> O comando lê o A1 **do arquivo**, não do banco. Envie o `.pfx`, use, e
> **remova com `shred`** depois. Foi o que fiz: não sobrou nenhum `.pfx` no
> servidor.

Resultado: **HTTP 201** no endpoint municipal, consulta **200**,
`versaoAplicativo: NfseNacional_EL_1.0.0`. Campos conferidos: `cTribNac=010101`
(análise e desenvolvimento de sistemas), `cIntContrib=101`, `cNBS=115021000`,
`vServ=1.00`, `pAliq=2.00`, `pTotTribSN=6.00`, assinatura presente.

Salvaguardas que o próprio comando aplica: **série 89999** (não a série 1 de
produção), descrição declarando "SEM VALOR FISCAL", e parâmetros tributários
sintéticos. O banco de produção **não foi tocado** — continua com 16 notas e a
sequência intacta.

### O bloqueio para emitir em produção

`validar_emissao` (em `apps/fiscal/services/emissao.py`) **recusa** transmitir
quando `iss_retido=True`:

> *"Este adaptador ainda não transmite retenções ou descontos; mantenha a nota
> como rascunho."*

E o **perfil padrão da empresa é "KS TEC — ISS 2% retido pelo tomador"**.
Existe o perfil "sem retenção", que passa — mas aí a nota sai com tributação
diferente da praticada.

Além disso: **as 16 notas do banco foram todas importadas do ADN**, não
emitidas pelo KS CENTRAL. Uma emissão em produção seria a primeira do sistema.
Faça com o dono acompanhando.

### Comandos que NÃO emitem

| Comando | Função |
|---|---|
| `diagnosticar_nfse <pfx>` | Valida A1 e acesso |
| `consultar_dps_el <idDPS> --ambiente 1` | Consulta DPS |
| `testar_emissao_el <pfx> --tomador <cpf>` | Monta e assina, sem transmitir |

---

## 9. Pendências

| Item | Situação | Impacto |
|---|---|---|
| **SMTP** | `EMAIL_URL=consolemail://` | E-mails vão para o log do contêiner. Avisos de trial, cobrança e boas-vindas não saem. Trocar para `smtp+tls://...` quando houver credencial (codifique `@` como `%40`) |
| **Backup** | `scripts/backup.sh` existe, **não agendado** | Sem backup automático. Ver `deploy.md` §15 |
| **Asaas** | Não configurado | Webhook seria `https://gestao.kstec.online/cobrancas/webhook/` |
| **WhatsApp** | Sobe em modo **SIMULADO** | Não envia nada. Ver `deploy.md` §12 |
| **Sentry** | `SENTRY_DSN=` vazio | Sem observabilidade externa |
| **Commit das correções** | Seção 6 | Aplicadas no servidor e local, **não commitadas** |
| **Endereço da empresa** | `"A definir, S/N — Centro, Valença/BA"` | **Não vai para o DPS** (o bloco do prestador leva só CNPJ e IM), mas aparece nas telas. Corrigir em Fiscal → Configuração |
| **MFA** | `MFA_OBRIGATORIO=True` | Configurado no primeiro acesso |

---

## 9A. Atualização preparada em 09/10/2026 (tarde)

Pronta na máquina de desenvolvimento, **não publicada** até a janela permitida (após 19:00) ou autorização do dono:

- **Emissão com ISS retido** (`tpRetISSQN=2`, `regApTribSN=2`, sem `pAliq`, tomador com IM e endereço), espelhando
  o DPS das NFS-e autorizadas 2600000000007–011. Validado contra o XSD; **nenhuma transmissão feita**. A primeira
  emissão real deve ser acompanhada pelo dono. Retenção só para tomador do mesmo município (Valença).
- **Contas de e-mail na tela** (Configurações → E-mails): `gestao@` para alertas, `financeiro@` para notas e documentos,
  senha cifrada (`Segredo`), botão de teste. `EMAIL_CONTAS_SMTP=False` nos perfis local/teste.
- **Alertas do monitoramento por e-mail**: destinatários gerais e por sistema, texto editável com prévia
  (Monitoramento → Alertas).
- **Central de documentos** (menu Relatórios): relatórios de atividades, planilhas de custos, relatórios de SLA
  (novo, gerado do monitoramento) e documentos assinados enviados (`DocumentoContrato`). Documento enviado atende a
  exigência do pacote contratual da mesma competência.
- **Custos** (menu Custos): por contrato com rateio dos centros globais (`CentroCusto.ratear`), por centro e categoria,
  exportação XLSX.
- **Cliente sem CNPJ** (emissão bloqueada até informar) e **e-mails de envio por cliente** (`emails_documentos`),
  com pré-preenchimento dos destinatários no envio da nota.
- **Assistente Gemini no WhatsApp** (chave cifrada em Configurações → WhatsApp). Consultas na hora; despesa e emissão
  só com SIM + código.
- **WhatsApp**: o worker recria a sessão sozinho ao mudar a configuração, ao clicar "Gerar novo QR" ou quando o QR expira.
- Migração `faturamento/0002` trazida do servidor para o repositório (não gerar outra).
- Carga: `scripts/carga_contratos_20261009.py` (CONMAC, INVICTA, Bom Jesus da Lapa, 12 documentos assinados,
  contas SMTP com senha via variável de ambiente). Exclua `docs/*.pdf` do pacote tar: contêm CPF.

### Publicado em 09/10/2026 (com autorização do dono, fora da janela)

Três publicações; backups antes de cada uma em `/opt/kscentral/backups/` (`antes-atualizacao-…`, `antes-correcao-pg-…`,
`antes-normalizacao-…`, mais `media-antes-…`). Vizinhos e link da PF conferidos após cada uma (200/302 como antes).

- **SMTP:** o Hetzner bloqueia a porta **465**; as contas usam **587/STARTTLS** e foram testadas (aceitas pela Hostinger).
- **Correção PostgreSQL:** `select_for_update()` com `select_related` em FK opcional falhava ("FOR UPDATE cannot be applied
  to the nullable side of an outer join") — atingia emissão, PDF e entregas. Agora `select_for_update(of=("self",))`.
  SQLite (testes locais) não detecta isso: o CI em PostgreSQL é necessário.
- **E&L normaliza a discriminação:** quebras de linha viram espaço na NFS-e autorizada. O DPS passa a sair normalizado
  e a conferência ignora diferenças só de espaçamento.
- **Primeiras emissões reais pelo KS CENTRAL** (vigência dos percentuais estendida para 01/06–31/10/2026, fonte
  registrada): NFS-e **2600000000013–016** (INVICTA 06–09/2026, R$ 5.000) e **2600000000017** (CONMAC 09/2026, R$ 3.500),
  serviço 01.01 / 101, ISS 2% não retido, DANFSe gerado, PDF+XML enviados a kaua@kstec.online. Recebíveis com vencimento
  10/10/2026. Agendas INVICTA e CONMAC agora em modo **Confirmar** com serviço 01.01.

### Pendências novas

| Item | Situação |
|---|---|
| WhatsApp não pareia | 09/10 15h: QR gerado, celular recusou, log `Login event: timeout`. Verificar versão do neonize/whatsmeow, testar pareamento por código de telefone (`PairPhone`) e instalar ffmpeg na imagem |
| PDFs assinados de 7–10 MB | Pacote de e-mail tem teto de 15 MB: comprimir antes de anexar |
| CONMAC | Minuta em PDF diz R$ 4.500 e prazo indeterminado; cadastrado R$ 3.500, 12 meses, conforme o dono |
| INVICTA | Vigência de 12 meses assumida; competências jun–set pendentes |
| Bom Jesus da Lapa | 1ª competência assumida out/2026 (assinatura 22/09); ISS sem retenção (tomador de outro município) |
| Agendas dos 3 novos | Modo rascunho até o contador confirmar código de serviço e tributação |

## 10. Antes de mexer: confira o servidor

O disco encheu em 09/10/2026 e derrubou todos os clientes. A segunda cópia
dos arquivos do Nuvem.center foi movida para a Storage Box no mesmo dia, o que
liberou 341 GB — mas o CONMAC continua crescendo pela migração do Google Drive.

```bash
ssh -i "$CHAVE" root@65.108.46.17 'bash -s' <<'FIM'
df -h / /mnt/storage                       # raiz abaixo de 85% é o seguro
free -h | sed -n 2p
uptime
docker ps -a --format '{{.Names}} {{.Status}}' | grep -viE 'healthy|Up ' || echo "todos ok"
curl -s -o /dev/null -w "LINK DA PF: %{http_code} em %{time_total}s\n" \
  https://bomjesusdalapa.nuvem.center/s/FPnJNyXSk3KrsS4
FIM
```

Documentos irmãos neste repositório, para entender o servidor:
`docs/GUIA-DO-SERVIDOR.md`, `docs/ESTRUTURA-BJL-E-BACKUP-REDUNDANTE.md`,
`docs/AJUSTES-PENDENTES-E-INCIDENTE-09-10.md`.

---

## 11. A regra que resume o resto

Metade dos defeitos deste servidor foram **comandos que terminaram com
sucesso e não fizeram nada**: backup que diz "Falhas 0" e empacota nada,
cópia que diz "OK — 2263 arquivos" com 1516 faltando, contêiner *healthy*
respondendo 503.

Depois de mudar qualquer coisa, **meça o resultado** — e com uma medida que
não venha da mesma fonte que você está testando.
