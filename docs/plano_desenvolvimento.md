# KS CENTRAL — Plano de Desenvolvimento Fase a Fase

> **Sistema de Gestão Integrada da KS TEC Soluções de Tecnologia LTDA**
> CNPJ 62.501.281/0001-13 · Valença/BA (IBGE 2932903)
> Stack: Python 3.12 · Django 5.x · PostgreSQL 16 · Redis · Celery
> Documento de instrução para desenvolvimento (humano ou agente de IA). Versão 1.0 — outubro/2026.

---

## Sumário

0. [Como usar este documento](#0-como-usar-este-documento)
1. [Achados da análise dos arquivos (leia antes de codar o fiscal)](#1-achados-da-análise-dos-arquivos)
2. [Visão do produto e módulos](#2-visão-do-produto-e-módulos)
3. [Arquitetura técnica](#3-arquitetura-técnica)
4. [Design System e Experiência do Usuário](#4-design-system-e-experiência-do-usuário)
5. [Modelo de dados completo](#5-modelo-de-dados-completo)
6. [Integração fiscal — NFS-e em duplo canal (código de referência)](#6-integração-fiscal--nfs-e)
7. [Monitoramento e SLA](#7-monitoramento-e-sla)
8. [Relatórios de atividades + IA Gemini](#8-relatórios-de-atividades--ia-gemini)
9. [Planilha de custos, financeiro e relatórios gerenciais](#9-planilha-de-custos-financeiro-e-relatórios)
10. [Certidões e habilitação](#10-certidões-e-habilitação)
11. [Catálogo, orçamentos e vendas avulsas](#11-catálogo-orçamentos-e-vendas-avulsas)
12. [Segurança, LGPD e auditoria](#12-segurança-lgpd-e-auditoria)
13. [Roteiro fase a fase](#13-roteiro-fase-a-fase)
14. [Anexos](#14-anexos)

---

## 0. Como usar este documento

- Cada **fase** (seção 13) tem objetivo, entregáveis, checklist e critérios de aceite. Não avance de fase sem os critérios de aceite verdes.
- As seções 4 a 12 são a **especificação de referência**: a fase aponta para elas.
- Trechos de código são **referência de implementação**, não cópia cega: todo XML fiscal deve ser validado contra o XSD oficial vigente antes de ir para produção.
- Convenções para o agente de desenvolvimento:
  - Código, nomes de modelos e campos em **português sem acento** (`nota_fiscal`, `data_vencimento`), docstrings em português.
  - Toda regra de negócio fica em `services/` (nunca em views ou templates). Views são finas.
  - Todo valor monetário é `DecimalField(max_digits=14, decimal_places=2)`. Nunca `float`.
  - Toda data/hora com timezone `America/Bahia`.
  - Toda alteração em entidade fiscal ou financeira gera registro de auditoria.
  - Testes obrigatórios para `services/` (pytest + pytest-django, cobertura mínima 80% nos apps `fiscal`, `financeiro`, `sla`).

---

## 1. Achados da análise dos arquivos

Foram analisados: `layout_rps_2_04_102.zip`, `importacao_aceites_v3.zip` e `Nota-Fiscal---Acesso-Contribuinte_cópia.pdf` (POP E&L), além do site kstec.online.

### 1.1 ⚠️ Achado crítico: Valença migrou para o Emissor Nacional

A Prefeitura de Valença/BA comunicou que, **a partir da competência janeiro/2026, a emissão de NFS-e passa a ser exclusivamente pelo Emissor Nacional** (Sefin Nacional / padrão DPS). O sistema municipal E&L ficou apenas para consulta, cancelamento e substituição de competências anteriores. Em comunicado posterior, a Secretaria de Fazenda esclareceu que **as guias de ISS das notas emitidas no Emissor Nacional continuam sendo geradas exclusivamente no Sistema Municipal de Notas Fiscais** (E&L), sem mudança de prazos.

**Consequência para a arquitetura:**

| Necessidade | Canal correto | Formato |
|---|---|---|
| Emitir NFS-e da KS TEC (competência ≥ 01/2026) | **API Sefin Nacional** | DPS XML assinado → GZip → Base64 → JSON, mTLS com certificado A1 |
| Cancelar/substituir NFS-e nova | API Sefin Nacional (eventos) | Pedido de registro de evento assinado |
| Emitir pelo canal municipal (teste/alternativa) e consultar/cancelar NFS-e antigas | Webservice E&L (ABRASF 2.04, SOAP) | XML ABRASF 2.04 assinado (RSA-SHA1) |
| Gerar guia (DAM) de ISS | **Portal municipal E&L** (manual) | Fluxo "Nota Fiscal > Declaração" do POP |
| Declarar serviços **tomados** com retenção (DAPS) | API REST E&L "Importação de Aceites" | JSON (arquivo `importacao_aceites_v3`) |
| Importar histórico | Upload dos XMLs exportados do portal E&L | `CompNfse` ABRASF |

> **Antes da Fase 4, confirmar com a Secretaria de Fazenda de Valença:** (a) se a KS TEC está habilitada para emissão via API/sistema próprio no Emissor Nacional; (b) a URL do portal E&L (`{URL_PREFEITURA}`) e se o webservice ABRASF ainda responde; (c) o CNPJ da Prefeitura (exigido no JSON de aceites).

Por isso o módulo fiscal é construído com **padrão Adapter e duplo canal** (seções 6 e 6.14): `ProvedorNacional` (Sefin) e `ProvedorElAbrasf` (webservice municipal E&L) são **ambos emissores completos em produção**, selecionáveis por nota, com travas contra emissão duplicada. O teste real nos dois canais define qual será o padrão. `ElAceitesClient` cobre a DAPS (serviços tomados).

### 1.2 O que os arquivos E&L/ABRASF 2.04 ensinam (ainda útil)

**`layout_rps_2_04_102.zip`** — Manual ABRASF 2.04 + atualizações E&L 1.00 → 1.02 + XSD + exemplos SOAP:

- Comunicação SOAP Document/Literal wrapped; cabeçalho em `nfseCabecMsg` e dados em `nfseDadosMsg`, ambos como **CDATA**; namespace de operação `http://nfse.abrasf.org.br`, namespace de dados `http://www.abrasf.org.br/nfse.xsd`.
- Operações: `RecepcionarLoteRps`, `RecepcionarLoteRpsSincrono`, `GerarNfse`, `CancelarNfse`, `SubstituirNfse`, `ConsultarLoteRps`, `ConsultarNfseRps`, `ConsultarNfseServicoPrestado`, `ConsultarNfseServicoTomado`, `ConsultarNfseFaixa` (máx. 50 notas por consulta).
- Assinatura XMLDSig enveloped, C14N, **RSA-SHA1 / SHA1** (padrão do manual), certificado ICP-Brasil A1 ou A3 com CNPJ do prestador.
- Situação de lote: 1 Não recebido · 2 Não processado · 3 Erro · 4 Sucesso.
- Códigos de cancelamento: 1 Erro na emissão · 2 Serviço não prestado · 4 Duplicidade (3 e 5 são de uso exclusivo do fisco).
- `RegimeEspecialTributacao` ampliado na v1.02: 1 ME municipal · 2 Estimativa · 3 Soc. profissionais · 4 Cooperativa · 5 MEI · 6 ME/EPP · **7 Profissional autônomo · 8 Notário/registrador · 9 Outros**.
- **v1.00/1.01 (Reforma Tributária):** novos campos `CodigoServicoNacional` (6 dígitos, sem máscara, ex.: `010101`) e `CodigoNbs` (9 dígitos, ex.: `115021000`), **NBS obrigatório desde 01/01/2026** (erros EL97, EL98, EL101, EL102).
- Anexos úteis para o catálogo: `ANEXO_B-NBS2-LISTA_SERVICO_NACIONAL` (código de tributação nacional) e `AnexoVIII-CorrelacaoItemNBSIndOpCClassTrib_IBSCBS` (correlação **Item LC 116 → NBS → IndOp → cClassTrib** do IBS/CBS). **Esses dois XLSX devem ser importados como tabelas de referência** (Fase 3).

Correlações extraídas que interessam diretamente à KS TEC:

| Item LC 116 | Descrição | NBS sugeridas (escolher a aderente) | cTribNac |
|---|---|---|---|
| 01.01 | Análise e desenvolvimento de sistemas | 1.1502.20.00 (software customizado), 1.1502.10.00 | 010101 |
| 01.03 | Processamento, armazenamento, hospedagem | 1.1506.21.00 (SaaS), 1.1506.10.00 (sites), 1.1506.22.00 (IaaS) | 010301 |
| 01.05 | Licenciamento/cessão de uso de software | 1.1103.22.00 | 010501 |
| 01.06 | Assessoria e consultoria em TI | 1.1501.10.00 | 010601 |
| 01.07 | Suporte técnico, manutenção de programas | 1.1501.30.00, 1.1508.00.00 | 010701 |
| 01.08 | Planejamento, confecção e manutenção de páginas | 1.1502.30.00 | 010801 |
| 13.05 | Composição gráfica (personalizada) | ver Anexo VIII | 130501 |

> Valores de `cTribNac` acima seguem a máscara item+subitem+desdobro "01". Conferir no Anexo B antes de cadastrar; a escolha final de NBS deve ser validada pelo contador.

**`importacao_aceites_v3.zip`** — API REST E&L para DAPS (serviços **tomados**):

- `POST {URL_PREFEITURA}/api/public/daps/autenticar` → body `{login, senha, inscricaoMunicipal, cnpjPrefeitura}` → **201** retorna chave.
- `POST {URL_PREFEITURA}/api/public/daps/criar` → header `aceites_autenticacao: <chave>` → body lista de notas → **201** devolve o mesmo JSON + `codigoVerificacao` e `tipoRegistro` (`D` = DAPS criada, `N` = nota encontrada e declarada).
- `POST .../daps/cancelar?codigo_verificacao=` (só para `tipoRegistro = D`).
- `POST .../daps/status_por_codigo_verificacao?codigo_verificacao=` → 200 / 404.
- Domínios: `regimeTributacao` N/S/M · `tipoNota` N/E/R · `tipoRecolhimento` R (retido) / N.
- Uso na KS TEC: quando a KS TEC **contrata** serviço com retenção de ISS (ex.: freelancer, terceirizado), ela, como tomadora, declara via DAPS. Recurso **opcional** (Fase 5+).

**POP "Nota Fiscal — Acesso Contribuinte" (E&L)** — confirma os fluxos manuais do portal que o KS CENTRAL deve **espelhar como checklist**, não automatizar:

- Declaração mensal → Encerrar declaração → status "Débito" → Impressão de boleto (DAM / PIX / QR Code) → status "Pago".
- Exportação de notas em XML limitada a **90 dias por arquivo** (o importador de histórico deve aceitar vários arquivos).
- Carta de correção, cancelamento com prazo vencido (análise do fiscal), substituição.

### 1.3 Identidade visual extraída de kstec.online

- Logo: `https://kstec.online/assets/ks-tec-logo.png` (1284×394, PNG transparente). **Cor sólida da logo: `#0016E1`** (azul elétrico profundo, amostrado do arquivo).
- Tipografia: **Manrope** (400–800) para UI e **JetBrains Mono** (400–500) para números, códigos e chaves fiscais.
- Paleta do site (`styles.css :root`): navy `#061534 / #0A1E3F / #122a55 / #1c3a6e`, azul primário `#1E5BFF` (hover `#1747d6`, claro `#4f7bff`), ciano `#22D3EE / #67E3F2`, dourado `#F5B642`, tinta `#0B1729`, muted `#5b6478 / #8892a4`, linhas `#E6EAF1 / #D6DCE7`, fundos `#FFFFFF / #F4F6FA / #EEF2F8`.
- Raios 10/14/20/28 px; sombras suaves azuladas; botões pill (`999px`) em CTAs.

---

## 2. Visão do produto e módulos

**KS CENTRAL** é o "cockpit" da KS TEC: cada contrato vira um centro de custo e de resultado, com suas notas, sistemas monitorados, tarefas, relatórios mensais, planilha de custos e certidões exigidas para receber.

### 2.1 Mapa de módulos

| # | Módulo | App Django | Resumo |
|---|---|---|---|
| 1 | Painel | `painel` | KPIs, alertas, agenda fiscal e de certidões, saúde dos sistemas |
| 2 | Cadastros | `cadastros` | Clientes/órgãos, fornecedores, pessoas de contato, endereços |
| 3 | Contratos | `contratos` | Contratos, aditivos, empenhos, itens, sistemas vinculados, fiscal do contrato |
| 4 | Catálogo | `catalogo` | Serviços, produtos, itens gráficos com matriz de preço, códigos fiscais |
| 5 | Fiscal | `fiscal` | NFS-e (Emissor Nacional), histórico E&L, guias ISS, DAPS, certificados |
| 6 | Financeiro | `financeiro` | Contas a receber/pagar, lançamentos, caixa, conciliação, DRE por contrato |
| 7 | Comercial | `comercial` | Orçamentos, aprovação por link, vendas avulsas → NF + recebível |
| 8 | Operação | `operacao` | Tarefas por contrato, apontamento de horas, evidências |
| 9 | Relatórios de atividades | `relatorios` | Geração mensal a partir das tarefas, refinamento com Gemini, PDF/DOCX |
| 10 | Custos | `custos` | Planilha de custos por contrato (diretos, indiretos, tributos, BDI) |
| 11 | Monitoramento/SLA | `sla` | Checagem HTTP periódica, incidentes, relatórios de disponibilidade |
| 12 | Certidões | `certidoes` | Validades, alertas, "kit habilitação" |
| 13 | IA | `ia` | Cliente Gemini, templates de prompt, log de uso e custo |
| 14 | Núcleo | `core` | Empresa, usuários, permissões, auditoria, anexos, parâmetros, notificações |

### 2.2 Ampliações propostas (além do pedido)

1. **Agenda de obrigações**: calendário único com vencimento de certidões, DAM de ISS, DAS, parcelas, fim de vigência contratual, renovação de domínio/SSL dos sistemas.
2. **Ciclo do recebimento público**: cada NF de contrato público acompanha `Empenho → Liquidação → Ordem Bancária`, com prazo médio de recebimento por órgão (indicador de inadimplência real de prefeituras).
3. **Pacote mensal de medição**: com um clique, gera para a competência a NFS-e + relatório de atividades + relatório de SLA + certidões vigentes, em um ZIP pronto para protocolar no órgão.
4. **Importador de histórico**: importa XMLs exportados do portal E&L (2025 e anteriores) para que DRE e relatórios tenham série histórica.
5. **Alerta de vigência e saldo contratual**: avisa a 90/60/30 dias do fim da vigência e quando o saldo do contrato cair abaixo de 20%.
6. **Monitoramento de SSL e domínio**: além do HTTP, verifica a validade do certificado TLS de cada sistema.
7. **Página pública de status** (opcional) por contrato: `status.kstec.online/<slug>` para o cliente ver disponibilidade.
8. **Busca global (Ctrl+K)**: notas, contratos, clientes, tarefas.

---

## 3. Arquitetura técnica

### 3.1 Stack

| Camada | Escolha | Motivo |
|---|---|---|
| Backend | Django 5.x (LTS mais recente), Python 3.12 | Padrão da KS TEC |
| Banco | PostgreSQL 16 | `JSONB`, `DecimalField` preciso, índices parciais |
| Fila/agenda | Celery 5 + Redis + `django-celery-beat` | Monitoramento SLA, alertas, transmissão fiscal assíncrona |
| Front | Templates Django + **HTMX** + **Alpine.js** + CSS com design tokens (Tailwind opcional via `django-tailwind`) | Interatividade sem SPA, manutenção simples |
| Gráficos | Chart.js (via CDN pinado) | Dashboards |
| PDF | WeasyPrint | Relatórios, orçamentos, kit de medição |
| DOCX | `docxtpl` | Relatório de atividades editável pelo órgão |
| XLSX | `openpyxl` | Planilha de custos com fórmulas reais |
| XML fiscal | `lxml`, `signxml` (ou `xmlsec`), `zeep` (SOAP E&L) | Montagem, assinatura, validação XSD |
| HTTP | `httpx` (mTLS, timeouts, HTTP/2) | Sefin Nacional, E&L, monitoramento |
| Certificado | `cryptography` (PKCS#12) | Leitura do A1 `.pfx` |
| IA | `google-genai` (SDK oficial Gemini) | Refinamento de textos |
| Auditoria | `django-simple-history` | Histórico por registro |
| Arquivos | `django-storages` (S3 compatível / Nextcloud via WebDAV) | Anexos, XMLs, PDFs |
| Observabilidade | Sentry + logs JSON (`structlog`) | Rastreio de erros fiscais |
| Testes | pytest, pytest-django, factory_boy, `respx` (mock httpx), `freezegun` | |
| Deploy | Docker Compose em VPS Hetzner: `web` (gunicorn), `worker`, `beat`, `db`, `redis`, `caddy` (TLS automático) | |

### 3.2 Estrutura de pastas

```
kscentral/
├── config/                    # settings (base, dev, prod), urls, celery.py, asgi/wsgi
├── apps/
│   ├── core/                  # Empresa, Usuario, Auditoria, Anexo, Parametro, Notificacao
│   ├── cadastros/
│   ├── contratos/
│   ├── catalogo/
│   ├── fiscal/
│   │   ├── models.py
│   │   ├── services/
│   │   │   ├── emissao.py     # orquestra: valida → numera → monta → assina → transmite
│   │   │   ├── numeracao.py
│   │   │   ├── calculo.py     # ISS, retenções, valor líquido
│   │   │   └── importador_el.py
│   │   ├── providers/
│   │   │   ├── base.py        # interface ProvedorNFSe
│   │   │   ├── nacional.py    # Sefin Nacional (DPS)
│   │   │   ├── el_abrasf.py   # E&L ABRASF 2.04 (SOAP)
│   │   │   └── el_aceites.py  # E&L DAPS (REST)
│   │   ├── xml/
│   │   │   ├── assinatura.py
│   │   │   ├── dps_builder.py
│   │   │   ├── abrasf_builder.py
│   │   │   └── schemas/       # XSDs oficiais versionados
│   │   └── tasks.py
│   ├── financeiro/
│   ├── comercial/
│   ├── operacao/
│   ├── relatorios/
│   ├── custos/
│   ├── sla/
│   ├── certidoes/
│   ├── ia/
│   └── painel/
├── templates/
│   ├── base.html  _sidebar.html  _topbar.html
│   ├── components/            # botões, cards, tabela, badge, modal, empty_state, kpi…
│   └── <app>/…
├── static/
│   ├── css/tokens.css  app.css
│   ├── js/app.js  (Alpine stores, atalhos, toasts)
│   └── img/ks-tec-logo.png  ks-tec-simbolo.svg
├── docker/  compose.yml  Caddyfile
└── tests/
```

### 3.3 Princípios

- **Multiempresa preparado, mono-empresa no uso**: todos os modelos de negócio têm FK `empresa` (permite no futuro vender o KS CENTRAL como produto a outras empresas).
- **Máquinas de estado explícitas** (`django-fsm` ou enum + service) para Nota Fiscal, Orçamento, Lançamento, Incidente, Relatório.
- **Idempotência** em toda chamada externa: cada transmissão tem `chave_idempotencia` e é registrada em `LogIntegracao` antes de sair.
- **Segredos** (senha do PFX, senha E&L, chave Gemini) criptografados em banco com `cryptography.Fernet` (`FIELD_ENCRYPTION_KEY` no `.env`), nunca em texto puro.

---

## 4. Design System e Experiência do Usuário

### 4.1 Conceito

"**Painel de controle institucional**": sóbrio como sistema público, preciso como ferramenta financeira, com o azul elétrico da marca usado só onde há ação ou dado importante. Mesmo DNA do site kstec.online (navy + branco + azul + ciano), adaptado para uso diário intenso.

### 4.2 Tokens (`static/css/tokens.css`)

```css
:root {
  /* Marca */
  --brand:        #0016E1;   /* cor exata da logo — símbolo, foco, links ativos */
  --primary:      #1E5BFF;   /* botões primários (site) */
  --primary-600:  #1747d6;
  --primary-400:  #4f7bff;
  --primary-50:   #EEF3FF;
  --accent:       #22D3EE;   /* ciano — destaques de dado, gráficos secundários */
  --accent-300:   #67E3F2;
  --gold:         #F5B642;   /* premium / atenção suave */

  /* Navy (sidebar, cabeçalhos de relatório) */
  --navy-900: #061534; --navy-800: #0A1E3F; --navy-700: #122a55; --navy-600: #1c3a6e;

  /* Neutros */
  --ink: #0B1729; --ink-2: #1f2a3d; --muted: #5b6478; --muted-2: #8892a4;
  --line: #E6EAF1; --line-2: #D6DCE7;
  --bg: #FFFFFF; --bg-soft: #F4F6FA; --bg-soft-2: #EEF2F8;

  /* Semânticas */
  --success: #16A34A; --success-bg: #E8F7EE;
  --warning: #D97706; --warning-bg: #FFF6E5;
  --danger:  #DC2626; --danger-bg:  #FDECEC;
  --info:    var(--primary); --info-bg: var(--primary-50);

  /* Forma */
  --r-sm: 10px; --r-md: 14px; --r-lg: 20px; --r-xl: 28px; --r-pill: 999px;
  --shadow-1: 0 1px 2px rgba(11,23,41,.04), 0 4px 14px rgba(11,23,41,.06);
  --shadow-2: 0 6px 18px rgba(11,23,41,.07), 0 20px 40px rgba(11,23,41,.10);
  --shadow-blue: 0 12px 30px -10px rgba(30,91,255,.55);

  /* Tipografia */
  --font-ui:   "Manrope", system-ui, -apple-system, "Segoe UI", sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, "SFMono-Regular", monospace;
  --fs-xs: 12px; --fs-sm: 13px; --fs-base: 14px; --fs-md: 16px;
  --fs-lg: 20px; --fs-xl: 24px; --fs-2xl: 32px;

  /* Layout */
  --sidebar-w: 264px; --sidebar-w-collapsed: 76px; --topbar-h: 64px;
  --content-max: 1360px;
}

/* Tema escuro (opcional, Fase 9) */
:root[data-theme="dark"] {
  --bg: #061534; --bg-soft: #0A1E3F; --bg-soft-2: #122a55;
  --ink: #EAF0FB; --ink-2: #C9D3E6; --muted: #97A6C5; --muted-2: #7E8BA6;
  --line: #1c3a6e; --line-2: #24467F;
}
```

Regras de uso:
- Números monetários, chaves de acesso, CNPJ, códigos de verificação: **JetBrains Mono** com `font-variant-numeric: tabular-nums`, alinhados à direita em tabelas.
- Azul `--primary` apenas para **uma** ação primária por tela. Ações secundárias: botão contorno. Destrutivas: `--danger` só no modal de confirmação.
- Contraste mínimo WCAG AA (4.5:1). `--muted` sobre branco passa; `--muted-2` só para texto ≥ 16px ou ícones.

### 4.3 Layout

```
┌──────────────┬─────────────────────────────────────────────────────────┐
│ [logo]       │ Topbar: breadcrumb · busca Ctrl+K · + Novo ▾ · 🔔 · avatar│
│ SIDEBAR navy ├─────────────────────────────────────────────────────────┤
│ Painel       │ Cabeçalho da página: título · subtítulo · ação primária │
│ Contratos    │ Filtros em linha (chips) · abas                          │
│ Fiscal       │                                                         │
│ Financeiro   │ Conteúdo (cards brancos, raio 14, shadow-1, fundo        │
│ Comercial    │ --bg-soft)                                              │
│ Operação     │                                                         │
│ Relatórios   │                                                         │
│ Monitoramento│                                                         │
│ Certidões    │                                                         │
│ ──────────   │                                                         │
│ Configurações│                                                         │
└──────────────┴─────────────────────────────────────────────────────────┘
```

- Sidebar `--navy-900`, item ativo com barra lateral de 3px `--accent` e fundo `rgba(255,255,255,.06)`. Logo versão branca no topo (gerar SVG monocromático branco do símbolo); recolhida mostra só o símbolo hexagonal.
- Mobile (< 768px): sidebar vira drawer; ação primária vira botão flutuante; tabelas viram listas de cards.
- Botão **"+ Novo"** global: Nota fiscal, Orçamento, Lançamento, Tarefa, Certidão.

### 4.4 Componentes (`templates/components/`)

| Componente | Especificação |
|---|---|
| `kpi_card` | Rótulo `--fs-sm --muted`, valor `--fs-2xl` mono, variação com seta e cor semântica, sparkline opcional |
| `status_badge` | Pill, fundo `*-bg`, texto semântico, ponto colorido à esquerda. Mapas de status por entidade definidos em `core/status.py` |
| `data_table` | Cabeçalho fixo, ordenação, seleção em lote, paginação HTMX, coluna de ações com menu "⋯", linha clicável abre drawer de detalhe |
| `drawer` | Painel lateral direito (480px) para detalhe rápido sem sair da lista |
| `modal_confirm` | Título, consequência descrita em uma frase, botão destrutivo exige digitar o número do documento em cancelamentos fiscais |
| `stepper` | Assistentes multi-etapa (emissão de NF, orçamento, relatório) |
| `empty_state` | Ilustração simples (símbolo KS em linha), frase do que fazer, botão de ação |
| `toast` | Canto superior direito, 4s, com "Desfazer" quando aplicável |
| `timeline` | Histórico de eventos (nota, contrato, incidente) |
| `money_input` | Máscara BRL, aceita colar "1.234,56" |
| `doc_input` | CPF/CNPJ com máscara, validação de dígito e **consulta automática de razão social** (BrasilAPI) |
| `uptime_bar` | 90 barrinhas verticais (dias), verde/âmbar/vermelho, tooltip com % do dia |
| `diff_view` | Comparação lado a lado texto original × texto refinado pela IA, com aceitar/rejeitar por parágrafo |

### 4.5 Padrões de experiência

1. **Tudo começa pelo contrato**: a página do contrato é um hub com abas `Resumo · Notas · Financeiro · Tarefas · Relatórios · Custos · Sistemas/SLA · Documentos · Histórico`.
2. **Assistente de emissão de NFS-e em 3 passos**: (1) Tomador + serviço (pré-preenchido pelo contrato), (2) Valores com cálculo ao vivo de ISS, retenções e líquido, (3) **Pré-visualização do DANFSe** + checklist de validação (certidão vigente? competência aberta? NBS preenchido?). Botão "Transmitir" só habilita com checklist verde.
3. **Erros fiscais traduzidos**: tabela `fiscal/erros.py` mapeia códigos (E999, RNG6159, EL97, EL101…) para mensagem em português claro + campo a corrigir (o formulário rola até ele).
4. **Ações em lote**: gerar notas da competência para todos os contratos ativos (fica em rascunho para revisão).
5. **Feedback de estado longo**: transmissão e geração de PDF rodam no Celery; UI mostra progresso por polling HTMX (`hx-trigger="every 2s"`) e notifica ao concluir.
6. **Atalhos**: `Ctrl+K` busca, `N` novo, `G C` contratos, `G F` fiscal, `?` lista de atalhos.
7. **Formatação brasileira** em tudo: `R$ 1.234,56`, `08/10/2026`, competência `10/2026`.
8. **Nunca perder trabalho**: rascunhos autosalvos (HTMX `hx-trigger="change delay:1s"`) em NF, orçamento e relatório.

### 4.6 Painel (home)

Linha 1 — KPIs: Faturado no mês · A receber (vencido em vermelho) · Resultado do mês · Disponibilidade média dos sistemas (30 dias).
Linha 2 — "Precisa da sua atenção" (lista priorizada): certidões vencendo, NF rejeitadas, DAM a emitir, sistemas fora do ar, relatórios mensais pendentes, orçamentos aguardando resposta.
Linha 3 — Gráfico receita × despesa (12 meses) · Receita por contrato (barras horizontais).
Linha 4 — Agenda dos próximos 15 dias · Status dos sistemas (grade com `uptime_bar`).

---

## 5. Modelo de dados completo

Convenção: todo modelo herda de `core.ModeloBase` → `id (UUID v7)`, `empresa (FK)`, `criado_em`, `atualizado_em`, `criado_por (FK Usuario)`, `ativo (bool)`, `history = HistoricalRecords()`. Abaixo só os campos específicos. `?` = opcional.

### 5.1 `core`

**Empresa** — `razao_social`, `nome_fantasia`, `cnpj (unique)`, `inscricao_municipal`, `inscricao_estadual?`, `regime_tributario (enum: SIMPLES, LUCRO_PRESUMIDO, LUCRO_REAL, MEI)`, `optante_simples (bool)`, `regime_especial_tributacao (int 0–9)`, `natureza_juridica`, `cnae_principal`, `cnaes_secundarios (JSONB)`, `endereco (FK Endereco)`, `email`, `telefone`, `site`, `logo (Image)`, `cor_primaria`, `municipio_ibge (default 2932903)`, `responsavel_tecnico`.

**Usuario** (AbstractUser) — `nome`, `email (login)`, `cpf?`, `cargo`, `telefone?`, `avatar?`, `tema (claro/escuro)`, `mfa_ativo`. Papéis via `Group`: **Administrador**, **Financeiro**, **Fiscal**, **Operação** (técnicos), **Leitura** (contador externo).

**Endereco** — `cep`, `logradouro`, `tipo_logradouro`, `numero`, `complemento?`, `bairro`, `municipio_ibge`, `municipio_nome`, `uf`, `pais_bacen (default 1058)`.

**Anexo** (genérico) — `content_type`, `object_id`, `arquivo`, `nome`, `tipo (enum: XML, PDF, IMAGEM, PLANILHA, OUTRO)`, `tamanho`, `hash_sha256`, `descricao?`.

**Parametro** — `chave (unique por empresa)`, `valor (JSONB)`, `descricao`. Ex.: `sla.intervalo_minutos`, `certidoes.dias_alerta = [30,15,7,0]`.

**Notificacao** — `usuario`, `titulo`, `mensagem`, `nivel`, `link`, `lida_em?`, `canal (APP, EMAIL, WHATSAPP)`.

**Segredo** — `nome`, `valor_criptografado (bytes)`, `escopo (FISCAL, IA, INTEGRACAO)`, `rotacionado_em`.

**LogIntegracao** — `servico (SEFIN, EL_ABRASF, EL_ACEITES, GEMINI, BRASILAPI, SLA)`, `operacao`, `chave_idempotencia`, `request (texto, segredos mascarados)`, `response`, `status_http`, `duracao_ms`, `sucesso`, `objeto (GenericFK)`.

### 5.2 `cadastros`

**Pessoa** (clientes, órgãos, fornecedores — um único cadastro com papéis) — `tipo (F/J)`, `cpf_cnpj (unique por empresa)`, `razao_social`, `nome_fantasia?`, `inscricao_municipal?`, `inscricao_estadual?`, `e_orgao_publico (bool)`, `esfera (MUNICIPAL, ESTADUAL, FEDERAL)?`, `endereco (FK)`, `email`, `email_nf?` (destino da NF), `telefone?`, `eh_cliente`, `eh_fornecedor`, `optante_simples?`, `observacoes?`.

**Contato** — `pessoa (FK)`, `nome`, `cargo` (ex.: "Fiscal do contrato", "Gestor", "Financeiro"), `email`, `telefone`, `recebe_relatorios (bool)`.

### 5.3 `contratos`

**Contrato** — `numero`, `objeto (text)`, `cliente (FK Pessoa)`, `modalidade (DISPENSA, PREGAO, INEXIGIBILIDADE, CONCORRENCIA, PRIVADO)`, `processo_administrativo?`, `fundamento_legal?` (ex.: "Lei 14.133/2021, art. 75, II"), `data_assinatura`, `vigencia_inicio`, `vigencia_fim`, `valor_global`, `valor_mensal?`, `forma_faturamento (MENSAL, POR_ENTREGA, UNICO)`, `dia_faturamento?`, `indice_reajuste? (IPCA, IGPM…)`, `data_base_reajuste?`, `status (RASCUNHO, VIGENTE, SUSPENSO, ENCERRADO, RESCINDIDO)`, `gestor_contrato (FK Contato)?`, `fiscal_contrato (FK Contato)?`, `perfil_fiscal (FK fiscal.PerfilFiscal)`, `servico_padrao (FK catalogo.ItemCatalogo)`, `discriminacao_padrao (text)` com placeholders `{competencia}`, `{contrato}`, `{empenho}`, `exige_relatorio_atividades (bool)`, `exige_relatorio_sla (bool)`, `certidoes_exigidas (M2M certidoes.TipoCertidao)`, `cor (hex, para gráficos)`.
Propriedades calculadas: `saldo = valor_global + soma(aditivos de valor) − soma(NF autorizadas)`, `percentual_executado`, `dias_para_fim`.

**Aditivo** — `contrato`, `numero`, `tipo (PRAZO, VALOR, PRAZO_VALOR, REAJUSTE, OBJETO)`, `data`, `nova_vigencia_fim?`, `valor_acrescimo?`, `percentual?`, `justificativa`.

**ItemContrato** — `contrato`, `item_catalogo (FK)`, `descricao`, `unidade`, `quantidade`, `valor_unitario`, `valor_total`.

**Empenho** — `contrato`, `numero`, `data`, `valor`, `dotacao_orcamentaria?`, `fonte_recurso?`, `saldo (calc)`.

**Competencia** (controle mensal do contrato) — `contrato`, `ano_mes (date, dia 1)`, `status (ABERTA, EM_FATURAMENTO, FATURADA, PAGA)`, `nota_fiscal (FK)?`, `relatorio_atividades (FK)?`, `relatorio_sla (FK)?`, `pacote_medicao (FK Anexo)?`. Unique `(contrato, ano_mes)`.

**SistemaVinculado** → definido em `sla.Sistema` com FK `contrato`.

### 5.4 `catalogo`

**CodigoServicoLC116** (tabela de referência importada) — `item (ex.: "01.07")`, `descricao`.
**CodigoTributacaoNacional** (Anexo B) — `codigo (6 dígitos)`, `item`, `subitem`, `desdobro`, `descricao`.
**CodigoNBS** (Anexo B, aba NBS) — `codigo (9 dígitos, sem máscara)`, `codigo_mascarado`, `descricao`.
**CorrelacaoNBS** (Anexo VIII) — `item_lc116`, `nbs`, `ps_onerosa`, `adq_exterior`, `ind_op`, `local_incidencia_ibs`, `c_class_trib`, `nome_c_class_trib`.

**CategoriaCatalogo** — `nome`, `tipo (SERVICO_TI, SERVICO_GRAFICO, PRODUTO_GRAFICO, AUDIOVISUAL, SOCIAL_MEDIA, OUTRO)`, `icone`.

**ItemCatalogo** — `codigo_interno (SKU)`, `nome`, `descricao`, `categoria`, `natureza (SERVICO, PRODUTO)`, `unidade (UN, HORA, MES, MILHEIRO, M2…)`, `preco_base`, `custo_base?`, `margem_alvo_pct?`, `item_lc116 (FK)?`, `codigo_tributacao_nacional (FK)?`, `codigo_tributacao_municipal?`, `nbs (FK)?`, `cnae?`, `aliquota_iss_padrao?`, `ncm?` (produtos), `prazo_entrega_dias?`, `permite_venda_avulsa (bool)`, `imagem?`.
Validação: se `natureza = SERVICO` → `item_lc116`, `codigo_tributacao_nacional` e `nbs` obrigatórios para emitir NF.

**VariacaoGrafica** (configurador de itens de gráfica) — `item (FK)`, `atributo (FORMATO, PAPEL, GRAMATURA, CORES, ACABAMENTO, LAMINACAO, CORTE)`, `opcao` (ex.: "A4", "Couché 150g", "4x4", "Verniz localizado"), `acrescimo_tipo (FIXO, PERCENTUAL, POR_UNIDADE)`, `acrescimo_valor`.

**FaixaPreco** — `item`, `quantidade_min`, `quantidade_max?`, `preco_unitario` (ex.: 100 un = 0,90; 500 un = 0,55; 1000 un = 0,38).

### 5.5 `fiscal`

**CertificadoDigital** — `apelido`, `tipo (A1)`, `arquivo_pfx (criptografado)`, `senha (FK Segredo)`, `titular_cnpj`, `emissor`, `numero_serie`, `valido_de`, `valido_ate`, `ativo`. Ao salvar: abrir o PFX com `cryptography`, extrair metadados, recusar se vencido ou CNPJ ≠ empresa. Alertas 30/15/7 dias antes do vencimento.

**ConfiguracaoFiscal** — `canais_habilitados`, `canal_padrao (NACIONAL, EL_ABRASF)`, `fallback_automatico (default False)`, `el_permite_competencia_atual (bool)` (ver 6.14), `ambiente (PRODUCAO, PRODUCAO_RESTRITA)`, `url_sefin`, `url_adn`, `url_el?`, `cnpj_prefeitura?`, `login_el? / senha_el (FK Segredo)?`, `serie_dps (default "1")`, `proximo_numero_dps`, `serie_rps_el?`, `proximo_numero_rps_el?`, `certificado (FK)`, `email_copia_nf?`, `texto_padrao_observacao?`.

**PerfilFiscal** (regras reutilizáveis por contrato/cliente) — `nome` (ex.: "Prefeitura — ISS retido + IR"), `iss_retido (bool)`, `responsavel_retencao (TOMADOR, INTERMEDIARIO)?`, `exigibilidade_iss (1–7)`, `aliquota_iss`, `reter_ir (bool)`, `aliquota_ir`, `reter_inss (bool)`, `aliquota_inss`, `reter_pis/cofins/csll (bool)`, `aliquotas_pcc`, `observacao_legal?`. **Alíquotas configuráveis — validar com o contador; não fixar no código.**

**NotaFiscal** — 
- Identificação: `provedor (NACIONAL, EL_ABRASF, IMPORTADA)` = canal que autorizou, `rps_serie?`, `rps_numero?` (canal E&L), `localizada_adn?`, `verificada_adn_em?`, `ambiente`, `tipo (NFSE)`, `serie_dps`, `numero_dps`, `id_dps (45 chars)`, `chave_acesso? (50)`, `numero_nfse?`, `codigo_verificacao?`, `protocolo?`, `data_emissao`, `competencia (date)`, `local_emissao_ibge`, `local_prestacao_ibge`.
- Partes: `prestador_snapshot (JSONB)`, `tomador (FK Pessoa)`, `tomador_snapshot (JSONB)` — snapshot congela os dados no momento da emissão.
- Origem: `contrato (FK)?`, `competencia_contrato (FK)?`, `venda (FK comercial.Venda)?`, `empenho (FK)?`.
- Serviço: `item_catalogo (FK)`, `item_lc116`, `codigo_tributacao_nacional`, `codigo_tributacao_municipal?`, `nbs`, `cnae?`, `discriminacao (text ≤ 2000)`, `informacoes_complementares?`.
- Valores: `valor_servicos`, `valor_deducoes`, `desconto_incondicionado`, `desconto_condicionado`, `base_calculo`, `aliquota_iss`, `valor_iss`, `iss_retido (bool)`, `valor_iss_retido`, `valor_ir`, `valor_inss`, `valor_pis`, `valor_cofins`, `valor_csll`, `outras_retencoes`, `valor_liquido`, `ibs_cbs (JSONB)?` (grupo IBS/CBS quando exigido).
- Estado: `status (RASCUNHO, VALIDADA, NA_FILA, TRANSMITINDO, AUTORIZADA, REJEITADA, CANCELAMENTO_SOLICITADO, CANCELADA, SUBSTITUIDA, ERRO_COMUNICACAO)`, `motivo_rejeicao (JSONB lista de {codigo, descricao, complemento})`, `xml_dps (Anexo)`, `xml_nfse (Anexo)`, `pdf_danfse (Anexo)`, `substituida_por (FK self)?`, `enviada_ao_tomador_em?`.
- Constraint: unique `(empresa, ambiente, serie_dps, numero_dps)`; unique parcial `chave_acesso` quando não nulo.

**EventoNota** — `nota`, `tipo (CANCELAMENTO e101101, SUBSTITUICAO, CARTA_CORRECAO_EL, …)`, `codigo_motivo`, `justificativa`, `xml_pedido`, `xml_retorno`, `status`, `data_registro`.

**GuiaISS** (controle do DAM gerado manualmente no portal municipal) — `competencia`, `notas (M2M NotaFiscal)`, `valor_iss_calculado`, `valor_guia`, `numero_dam?`, `vencimento`, `pdf (Anexo)?`, `linha_digitavel?`, `pix_copia_cola?`, `status (A_DECLARAR, DECLARADA, ENCERRADA, PAGA)`, `lancamento (FK financeiro.Lancamento)?`. Só gera guia para notas **não retidas** (ISS retido é recolhido pelo tomador).

**Daps** (serviços tomados, opcional) — `fornecedor (FK Pessoa)`, `numero_nota`, `data_emissao`, `data_fato_gerador`, `valor`, `valor_deducao`, `aliquota`, `codigo_servico`, `discriminacao`, `regime_tributacao (N/S/M)`, `tipo_nota (N/E/R)`, `tipo_recolhimento (R/N)`, `codigo_ibge_prestacao`, `codigo_verificacao?`, `tipo_registro (D/N)?`, `status`.

**SequenciaNumeracao** — `serie`, `tipo (DPS, RPS_EL)`, `ultimo_numero`. Incremento via `select_for_update()`.

**TentativaTransmissao** — ver 6.14.2 (uma linha por envio, por canal; base das travas anti-duplicidade).

### 5.6 `financeiro`

**ContaBancaria** — `nome`, `banco_codigo`, `agencia`, `conta`, `tipo (CORRENTE, POUPANCA, CAIXA, CARTAO)`, `chave_pix?`, `saldo_inicial`, `data_saldo_inicial`.
**CategoriaFinanceira** (árvore) — `nome`, `tipo (RECEITA, DESPESA)`, `pai (FK self)?`, `grupo_dre (RECEITA_BRUTA, DEDUCOES, CUSTO_SERVICO, DESPESA_OPERACIONAL, DESPESA_FINANCEIRA, IMPOSTOS, INVESTIMENTO, NAO_OPERACIONAL)`.
Plano inicial (seed): Receitas: Contratos públicos · Contratos privados · Vendas avulsas · Gráfica · Audiovisual. Despesas: Infraestrutura (VPS, domínios, SSL, storage) · Software/licenças/APIs (incl. Gemini) · Pessoal/terceiros · Impostos (DAS, ISS, retenções) · Deslocamento · Material gráfico · Marketing · Administrativas · Tarifas bancárias.
**CentroCusto** — `nome`, `contrato (FK)?` (um centro por contrato criado automaticamente + "Administrativo").
**Lancamento** — `tipo (RECEITA, DESPESA, TRANSFERENCIA)`, `descricao`, `pessoa (FK)?`, `categoria`, `centro_custo`, `conta_bancaria`, `valor`, `data_competencia`, `data_vencimento`, `data_pagamento?`, `valor_pago?`, `juros/multa/desconto`, `forma_pagamento (PIX, BOLETO, TED, CARTAO, DINHEIRO, OB)`, `status (PREVISTO, PENDENTE, PAGO, ATRASADO, CANCELADO)`, `nota_fiscal (FK)?`, `venda (FK)?`, `recorrencia (FK Recorrencia)?`, `parcela_n?/de?`, `comprovante (Anexo)?`, `ordem_bancaria?` (contratos públicos), `data_liquidacao?`, `conciliado (bool)`.
**Recorrencia** — `frequencia (MENSAL, ANUAL…)`, `dia`, `inicio`, `fim?`, `modelo (JSONB)`. Gera lançamentos previstos 12 meses à frente.
**ExtratoImportado / ItemExtrato** — import de OFX/CSV; `match` com lançamentos por valor+data±3 dias.

### 5.7 `comercial`

**Orcamento** — `numero (ORC-2026-0001)`, `cliente (FK Pessoa)` ou `cliente_avulso (nome, doc, contato)`, `data`, `validade`, `status (RASCUNHO, ENVIADO, VISUALIZADO, APROVADO, RECUSADO, EXPIRADO, CONVERTIDO)`, `condicoes_pagamento`, `prazo_entrega`, `observacoes`, `desconto_tipo/valor`, `total`, `token_publico (UUID)`, `aprovado_em?`, `aprovado_por_nome?`, `ip_aprovacao?`, `pdf (Anexo)`.
**ItemOrcamento** — `orcamento`, `item_catalogo`, `descricao`, `variacoes (JSONB)`, `quantidade`, `preco_unitario (calculado por faixa + variações, editável)`, `desconto?`, `total`.
**Venda** — `orcamento (FK)?`, `cliente`, `itens`, `total`, `status (ABERTA, EM_PRODUCAO, ENTREGUE, FATURADA, CANCELADA)`, `gera_nf (bool)`, `parcelas`.
**ItemVenda** — espelho de ItemOrcamento.

### 5.8 `operacao`

**Tarefa** — `contrato (FK)?`, `sistema (FK sla.Sistema)?`, `titulo`, `descricao`, `tipo (DESENVOLVIMENTO, CORRECAO, SUPORTE, MANUTENCAO, IMPLANTACAO, TREINAMENTO, REUNIAO, CONTEUDO, INFRA)`, `prioridade`, `status (A_FAZER, EM_ANDAMENTO, EM_REVISAO, CONCLUIDA, CANCELADA)`, `responsavel (FK Usuario)`, `solicitante (FK Contato)?`, `protocolo_cliente?`, `data_abertura`, `prazo?`, `concluida_em?`, `horas_estimadas?`, `entrar_no_relatorio (bool, default True)`, `resumo_para_relatorio (text)` — frase objetiva do que foi entregue.
**Apontamento** — `tarefa`, `usuario`, `data`, `horas (Decimal)`, `descricao`.
**Evidencia** — `tarefa`, `arquivo (imagem/PDF)`, `legenda`, `incluir_no_relatorio (bool)`.

### 5.9 `relatorios`

**ModeloRelatorio** — `nome`, `tipo (ATIVIDADES, SLA, FINANCEIRO, CUSTOS)`, `secoes (JSONB ordenado)`, `template_docx (arquivo)`, `template_html`.
**RelatorioAtividades** — `contrato`, `competencia`, `periodo_inicio/fim`, `status (RASCUNHO, EM_REVISAO, APROVADO, ENVIADO)`, `introducao`, `consideracoes_finais`, `responsavel_tecnico`, `versao`, `pdf/docx (Anexo)`, `enviado_em?`, `hash_documento`.
**SecaoRelatorio** — `relatorio`, `ordem`, `titulo`, `texto_original`, `texto_refinado?`, `texto_final`, `origem (MANUAL, TAREFAS, IA)`, `tarefas (M2M)`, `aceito_ia (bool)`.

### 5.10 `custos`

**PlanilhaCusto** — `contrato (FK)?` ou `orcamento (FK)?`, `versao`, `data_base`, `status (RASCUNHO, VIGENTE, ARQUIVADA)`, `bdi_pct (calc)`, `margem_pct`, `preco_mensal_calculado`, `observacoes`.
**GrupoCusto** — `planilha`, `tipo (MAO_DE_OBRA, INFRAESTRUTURA, LICENCAS, INSUMOS, DESLOCAMENTO, INDIRETOS, TRIBUTOS, LUCRO)`, `ordem`.
**ItemCusto** — `grupo`, `descricao`, `unidade`, `quantidade`, `valor_unitario`, `periodicidade (MENSAL, ANUAL, UNICO)`, `valor_mensal (calc)`, `fonte` (ex.: "Fatura Hetzner"), `rateio_pct` (quando o custo é compartilhado entre contratos).
**ComposicaoBDI** — `planilha`, `administracao_central`, `seguro_garantia`, `risco`, `despesas_financeiras`, `lucro`, `tributos (ISS, PIS, COFINS, IRPJ, CSLL ou DAS)` → BDI = fórmula da seção 9.1.

### 5.11 `sla`

**Sistema** — `contrato (FK)?`, `nome`, `url`, `metodo (GET/HEAD)`, `status_esperado (default 200)`, `palavra_chave? `(deve aparecer no HTML), `timeout_s (10)`, `intervalo_min (5)`, `verificar_ssl (bool)`, `headers (JSONB)?`, `url_health? `(API futura), `token_health (FK Segredo)?`, `meta_disponibilidade_pct (99.5)`, `horario_cobertura (24x7 ou JSON de janelas)`, `status_atual (OPERACIONAL, DEGRADADO, FORA, MANUTENCAO, DESCONHECIDO)`, `ssl_expira_em?`, `ultima_verificacao_em?`, `publico_status_page (bool)`.
**Verificacao** — `sistema`, `executada_em (indexada)`, `sucesso`, `status_http?`, `tempo_resposta_ms?`, `erro?`, `origem (CELERY_VPS, SEGUNDA_SONDA)`, `detalhes_health (JSONB)?`. Particionar por mês (ou reter 90 dias brutos + agregados).
**AgregadoDiario** — `sistema`, `dia`, `total_checks`, `checks_ok`, `minutos_indisponivel`, `minutos_manutencao`, `tempo_medio_ms`, `p95_ms`, `disponibilidade_pct`.
**Incidente** — `sistema`, `inicio`, `fim?`, `duracao_min`, `severidade (TOTAL, PARCIAL, LENTIDAO)`, `causa?`, `acoes_tomadas?`, `tarefa (FK operacao.Tarefa)?`, `comunicado_cliente_em?`.
**JanelaManutencao** — `sistema`, `inicio`, `fim`, `motivo`, `comunicada_ao_cliente (bool)` — minutos dentro da janela não contam contra o SLA.
**RelatorioSLA** — `contrato`, `competencia`, `sistemas (M2M)`, `resultado (JSONB)`, `pdf`, `status`.

### 5.12 `certidoes`

**TipoCertidao** — `nome`, `orgao_emissor`, `esfera`, `url_emissao`, `validade_padrao_dias`, `obrigatoria_habilitacao (bool)`, `instrucoes`.
Seed: CND Federal conjunta (RFB/PGFN) · CRF FGTS (Caixa) · CNDT (TST) · Certidão de Regularidade Fiscal Estadual (SEFAZ-BA) · Certidão Negativa de Débitos Municipais (Valença) · Certidão de Falência e Recuperação Judicial (TJBA) · Certidão Simplificada (JUCEB) · Consulta Consolidada TCU / CEIS / CNEP · Alvará de funcionamento · Inscrição Municipal (Cadastro).
**Certidao** — `tipo`, `numero/codigo_controle`, `data_emissao`, `data_validade`, `arquivo (PDF)`, `situacao (NEGATIVA, POSITIVA_COM_EFEITO_NEGATIVA, POSITIVA)`, `codigo_autenticidade?`, `url_validacao?`, `observacao?`. Status derivado: `VALIDA`, `VENCENDO (≤ 15d)`, `VENCIDA`.
**KitHabilitacao** — `nome` (ex.: "Dispensa 012/2026 — Prefeitura X"), `certidoes (M2M)`, `documentos_extra (M2M Anexo)`, `zip (Anexo)`, `gerado_em`.

### 5.13 `ia`

**PromptTemplate** — `slug`, `nome`, `finalidade`, `system_instruction`, `template_usuario` (com variáveis), `modelo`, `temperatura`, `max_tokens`, `ativo`, `versao`.
**ChamadaIA** — `template`, `usuario`, `objeto (GenericFK)`, `entrada (texto)`, `saida`, `modelo`, `tokens_entrada`, `tokens_saida`, `custo_estimado`, `latencia_ms`, `sucesso`, `erro?`.

---

## 6. Integração fiscal — NFS-e

### 6.1 Fluxo geral de emissão

```
[Contrato/Venda] → gerar rascunho NF → validar (regras locais + XSD) → numerar DPS (lock)
   → montar XML → assinar (A1) → GZip+Base64 → POST Sefin (mTLS)
      ├─ 201 → AUTORIZADA: salvar chave, XML NFS-e, baixar DANFSe, criar Lançamento a receber,
      │        marcar Competência FATURADA, e-mail ao tomador, se ISS não retido → GuiaISS A_DECLARAR
      ├─ 4xx com erros → REJEITADA: traduzir erros, voltar para edição (número DPS NÃO é reutilizado
      │        se o fisco o registrou; ver 6.6)
      └─ timeout/5xx → ERRO_COMUNICACAO: antes de retransmitir, CONSULTAR por idDps (idempotência)
```

### 6.2 Interface comum (`fiscal/providers/base.py`)

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ResultadoFiscal:
    sucesso: bool
    pendente: bool = False                 # lote assíncrono ainda em processamento
    chave_acesso: str | None = None
    numero_nfse: str | None = None
    codigo_verificacao: str | None = None
    protocolo: str | None = None
    xml_enviado: bytes | None = None
    xml_retorno: bytes | None = None
    erros: list[dict] = field(default_factory=list)   # [{codigo, descricao, complemento}]
    alertas: list[dict] = field(default_factory=list)


class ProvedorNFSe(ABC):
    """Contrato que todo provedor fiscal implementa. Views e services só conhecem esta interface."""

    def __init__(self, config, certificado):
        self.config = config
        self.certificado = certificado

    @abstractmethod
    def emitir(self, nota) -> ResultadoFiscal: ...

    @abstractmethod
    def consultar(self, nota) -> ResultadoFiscal: ...

    @abstractmethod
    def cancelar(self, nota, codigo_motivo: str, justificativa: str) -> ResultadoFiscal: ...

    def substituir(self, nota_original, nota_nova, codigo_motivo: str) -> ResultadoFiscal:
        raise NotImplementedError

    def obter_pdf(self, nota) -> bytes | None:
        return None


def get_provedor(config, provedor: str | None = None) -> ProvedorNFSe:
    from .nacional import ProvedorNacional
    from .el_abrasf import ProvedorElAbrasf
    mapa = {"NACIONAL": ProvedorNacional, "EL_ABRASF": ProvedorElAbrasf}
    return mapa[provedor or config.canal_padrao](config, config.certificado)
```

### 6.3 Certificado A1 (`fiscal/certificado.py`)

```python
import os, tempfile
from contextlib import contextmanager
from cryptography.hazmat.primitives.serialization import (
    pkcs12, Encoding, PrivateFormat, NoEncryption,
)


def carregar_pfx(pfx_bytes: bytes, senha: str):
    chave, cert, cadeia = pkcs12.load_key_and_certificates(pfx_bytes, senha.encode())
    key_pem = chave.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    cert_pem = cert.public_bytes(Encoding.PEM)
    cadeia_pem = b"".join(c.public_bytes(Encoding.PEM) for c in (cadeia or []))
    return key_pem, cert_pem, cadeia_pem, cert


@contextmanager
def certificado_em_arquivos(certificado_model):
    """httpx/ssl exigem arquivos para mTLS. Gera PEMs temporários 0600 e apaga ao sair."""
    key_pem, cert_pem, cadeia_pem, _ = carregar_pfx(
        certificado_model.ler_pfx(), certificado_model.ler_senha()
    )
    d = tempfile.mkdtemp(prefix="kscert_")
    cert_path, key_path = os.path.join(d, "cert.pem"), os.path.join(d, "key.pem")
    try:
        for path, data in ((cert_path, cert_pem + cadeia_pem), (key_path, key_pem)):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
        yield cert_path, key_path, key_pem, cert_pem
    finally:
        for p in (cert_path, key_path):
            if os.path.exists(p):
                os.remove(p)
        os.rmdir(d)
```

### 6.4 Assinatura XMLDSig (`fiscal/xml/assinatura.py`)

```python
from lxml import etree
from signxml import XMLSigner, methods, SignatureMethod, DigestAlgorithm, CanonicalizationMethod

DSIG_NS = "http://www.w3.org/2000/09/xmldsig#"


def assinar(raiz: etree._Element, id_referencia: str, key_pem: bytes, cert_pem: bytes,
            algoritmo: str = "sha256") -> etree._Element:
    """Assinatura enveloped. A <Signature> é anexada como último filho de `raiz`
    (ex.: <DPS> contendo <infDPS Id="...">), referenciando #id_referencia.

    - Padrão Nacional: conferir no manual/XSD vigente o algoritmo exigido (sha256 é o esperado).
    - ABRASF/E&L 2.04: o manual especifica rsa-sha1 + sha1. Se a versão do `signxml`
      recusar SHA1, usar `python-xmlsec` apenas no adaptador E&L.
    """
    sha1 = algoritmo == "sha1"
    signer = XMLSigner(
        method=methods.enveloped,
        signature_algorithm=SignatureMethod.RSA_SHA1 if sha1 else SignatureMethod.RSA_SHA256,
        digest_algorithm=DigestAlgorithm.SHA1 if sha1 else DigestAlgorithm.SHA256,
        c14n_algorithm=CanonicalizationMethod.CANONICAL_XML_1_0,
    )
    signer.namespaces = {None: DSIG_NS}          # sem prefixo "ds:" (exigência comum dos validadores)
    return signer.sign(raiz, key=key_pem, cert=cert_pem, reference_uri=f"#{id_referencia}")


def validar_xsd(xml: etree._Element, caminho_xsd: str) -> list[str]:
    schema = etree.XMLSchema(etree.parse(caminho_xsd))
    return [] if schema.validate(xml) else [str(e) for e in schema.error_log]
```

### 6.5 Montagem da DPS — Padrão Nacional (`fiscal/xml/dps_builder.py`)

> ⚠️ **Esqueleto de referência.** Baixar os XSDs oficiais da versão vigente na Biblioteca Técnica do portal nfse.gov.br, salvar em `fiscal/xml/schemas/nacional/` e ajustar nomes/ordem de tags conforme o XSD. O build só passa se `validar_xsd()` retornar lista vazia.

```python
from decimal import Decimal
from lxml import etree

NS = "http://www.sped.fazenda.gov.br/nfse"
VERSAO = "1.01"   # conferir versão vigente


def montar_id_dps(cod_mun_emissor: str, cnpj: str, serie: str, numero: int) -> str:
    """'DPS' + cLocEmi(7) + tipo inscrição(1: 1=CPF, 2=CNPJ) + inscrição(14) + série(5) + nDPS(15)
    = 45 caracteres. Conferir regra no manual vigente."""
    return f"DPS{cod_mun_emissor}2{cnpj.zfill(14)}{serie.zfill(5)}{str(numero).zfill(15)}"


def _e(pai, tag, texto=None):
    el = etree.SubElement(pai, f"{{{NS}}}{tag}")
    if texto is not None:
        el.text = str(texto)
    return el


def _dec(v: Decimal) -> str:
    return f"{v.quantize(Decimal('0.01'))}"


def montar_dps(nota, config) -> tuple[etree._Element, str]:
    emp = nota.empresa
    id_dps = montar_id_dps(emp.municipio_ibge, emp.cnpj, nota.serie_dps, nota.numero_dps)

    dps = etree.Element(f"{{{NS}}}DPS", nsmap={None: NS}, versao=VERSAO)
    inf = _e(dps, "infDPS"); inf.set("Id", id_dps)

    _e(inf, "tpAmb", 1 if config.ambiente == "PRODUCAO" else 2)
    _e(inf, "dhEmi", nota.data_emissao.isoformat(timespec="seconds"))
    _e(inf, "verAplic", "KSCENTRAL_1.0")
    _e(inf, "serie", nota.serie_dps)
    _e(inf, "nDPS", nota.numero_dps)
    _e(inf, "dCompet", nota.competencia.isoformat())
    _e(inf, "tpEmit", 1)                                   # 1 = prestador
    _e(inf, "cLocEmi", emp.municipio_ibge)                 # 2932903 Valença/BA

    prest = _e(inf, "prest")
    _e(prest, "CNPJ", emp.cnpj)
    if emp.inscricao_municipal:
        _e(prest, "IM", emp.inscricao_municipal)            # exatamente como no cadastro municipal
    reg = _e(prest, "regTrib")
    _e(reg, "opSimpNac", emp.cod_op_simples_nacional)      # 1 não optante / 2 MEI / 3 ME-EPP (conferir)
    _e(reg, "regEspTrib", emp.regime_especial_tributacao or 0)

    t = nota.tomador_snapshot
    toma = _e(inf, "toma")
    _e(toma, "CNPJ" if len(t["cpf_cnpj"]) == 14 else "CPF", t["cpf_cnpj"])
    _e(toma, "xNome", t["razao_social"][:300])
    end = _e(toma, "end"); end_nac = _e(end, "endNac")
    _e(end_nac, "cMun", t["municipio_ibge"]); _e(end_nac, "CEP", t["cep"])
    _e(end, "xLgr", t["logradouro"]); _e(end, "nro", t.get("numero") or "S/N")
    _e(end, "xBairro", t["bairro"])
    if t.get("email"):
        _e(toma, "email", t["email"])

    serv = _e(inf, "serv")
    loc = _e(serv, "locPrest"); _e(loc, "cLocPrestacao", nota.local_prestacao_ibge)
    cs = _e(serv, "cServ")
    _e(cs, "cTribNac", nota.codigo_tributacao_nacional)    # 6 dígitos, ex.: 010701
    if nota.codigo_tributacao_municipal:
        _e(cs, "cTribMun", nota.codigo_tributacao_municipal)
    _e(cs, "xDescServ", nota.discriminacao[:2000])
    _e(cs, "cNBS", nota.nbs)                               # 9 dígitos, obrigatório desde 01/2026

    val = _e(inf, "valores")
    vsp = _e(val, "vServPrest"); _e(vsp, "vServ", _dec(nota.valor_servicos))
    trib = _e(val, "trib")
    tmun = _e(trib, "tribMun")
    _e(tmun, "tribISSQN", 1)                               # 1 = operação tributável
    _e(tmun, "tpRetISSQN", 2 if nota.iss_retido else 1)    # conferir domínio no manual
    # Retenções federais (grupo tribFed) e IBS/CBS (grupo IBSCBS) — incluir conforme XSD vigente.
    tot = _e(trib, "totTrib"); _e(tot, "indTotTrib", 0)

    return dps, id_dps
```

### 6.6 Provedor Nacional (`fiscal/providers/nacional.py`)

```python
import base64, gzip, httpx
from lxml import etree
from .base import ProvedorNFSe, ResultadoFiscal
from ..certificado import certificado_em_arquivos
from ..xml.assinatura import assinar, validar_xsd
from ..xml.dps_builder import montar_dps

URLS = {
    "PRODUCAO":          {"sefin": "https://sefin.nfse.gov.br/SefinNacional",
                          "adn":   "https://adn.nfse.gov.br"},
    "PRODUCAO_RESTRITA": {"sefin": "https://sefin.producaorestrita.nfse.gov.br/SefinNacional",
                          "adn":   "https://adn.producaorestrita.nfse.gov.br"},
}
XSD_DPS = "apps/fiscal/xml/schemas/nacional/DPS_v1.01.xsd"   # ajustar ao arquivo oficial


def gz_b64(data: bytes) -> str:
    return base64.b64encode(gzip.compress(data)).decode()


def un_gz_b64(s: str) -> bytes:
    return gzip.decompress(base64.b64decode(s))


class ProvedorNacional(ProvedorNFSe):
    def _urls(self):
        return URLS[self.config.ambiente]

    def _client(self, cert_path, key_path) -> httpx.Client:
        return httpx.Client(cert=(cert_path, key_path), timeout=httpx.Timeout(60, connect=15),
                            headers={"Accept": "application/json"})

    def emitir(self, nota) -> ResultadoFiscal:
        dps, id_dps = montar_dps(nota, self.config)
        with certificado_em_arquivos(self.certificado) as (cert_p, key_p, key_pem, cert_pem):
            assinado = assinar(dps, id_dps, key_pem, cert_pem, "sha256")
            erros_xsd = validar_xsd(assinado, XSD_DPS)
            if erros_xsd:
                return ResultadoFiscal(False, erros=[{"codigo": "XSD", "descricao": e} for e in erros_xsd])
            xml = etree.tostring(assinado, encoding="UTF-8", xml_declaration=True)
            nota.id_dps = id_dps
            with self._client(cert_p, key_p) as c:
                r = c.post(f"{self._urls()['sefin']}/nfse", json={"dpsXmlGZipB64": gz_b64(xml)})

        corpo = r.json() if r.content else {}
        if r.status_code == 201:
            xml_nfse = un_gz_b64(corpo["nfseXmlGZipB64"]) if corpo.get("nfseXmlGZipB64") else None
            return ResultadoFiscal(True, chave_acesso=corpo.get("chaveAcesso"),
                                   xml_enviado=xml, xml_retorno=xml_nfse,
                                   alertas=_normalizar(corpo.get("alertas")))
        return ResultadoFiscal(False, xml_enviado=xml,
                               erros=_normalizar(corpo.get("erros") or corpo.get("erro")))

    def consultar(self, nota) -> ResultadoFiscal:
        """Se tiver chave → GET /nfse/{chave}; se só tiver idDps → GET /dps/{idDps} (recupera a chave).
        Usar SEMPRE antes de retransmitir após timeout."""
        with certificado_em_arquivos(self.certificado) as (cert_p, key_p, *_):
            with self._client(cert_p, key_p) as c:
                if nota.chave_acesso:
                    r = c.get(f"{self._urls()['sefin']}/nfse/{nota.chave_acesso}")
                else:
                    r = c.get(f"{self._urls()['sefin']}/dps/{nota.id_dps}")
        corpo = r.json() if r.content else {}
        if r.status_code == 200:
            return ResultadoFiscal(True, chave_acesso=corpo.get("chaveAcesso") or nota.chave_acesso,
                                   xml_retorno=un_gz_b64(corpo["nfseXmlGZipB64"])
                                   if corpo.get("nfseXmlGZipB64") else None)
        return ResultadoFiscal(False, erros=_normalizar(corpo.get("erros") or corpo.get("erro")))

    def cancelar(self, nota, codigo_motivo, justificativa) -> ResultadoFiscal:
        """Evento e101101 (cancelamento). Montar <pedRegEvento><infPedReg Id="PRE..."> conforme XSD
        de eventos vigente, assinar infPedReg e enviar para /nfse/{chave}/eventos."""
        from ..xml.evento_builder import montar_pedido_cancelamento
        ped, id_ped = montar_pedido_cancelamento(nota, codigo_motivo, justificativa, self.config)
        with certificado_em_arquivos(self.certificado) as (cert_p, key_p, key_pem, cert_pem):
            xml = etree.tostring(assinar(ped, id_ped, key_pem, cert_pem), encoding="UTF-8",
                                 xml_declaration=True)
            with self._client(cert_p, key_p) as c:
                r = c.post(f"{self._urls()['sefin']}/nfse/{nota.chave_acesso}/eventos",
                           json={"pedidoRegistroEventoXmlGZipB64": gz_b64(xml)})
        corpo = r.json() if r.content else {}
        ok = r.status_code in (200, 201)
        return ResultadoFiscal(ok, xml_enviado=xml, erros=[] if ok else _normalizar(
            corpo.get("erros") or corpo.get("erro")))

    def obter_pdf(self, nota) -> bytes | None:
        """DANFSe oficial do ADN. Há relatos de 404 intermitente: em caso de falha,
        gerar representação própria via WeasyPrint a partir do XML (marcada como tal)."""
        with certificado_em_arquivos(self.certificado) as (cert_p, key_p, *_):
            with self._client(cert_p, key_p) as c:
                r = c.get(f"{self._urls()['adn']}/danfse/{nota.chave_acesso}")
        return r.content if r.status_code == 200 else None


def _normalizar(itens) -> list[dict]:
    """A Sefin devolve erros em 'erro' ou 'erros', com 'Codigo'/'codigo' e 'Descricao'/'descricao'."""
    if not itens:
        return []
    if isinstance(itens, dict):
        itens = [itens]
    return [{"codigo": i.get("Codigo") or i.get("codigo"),
             "descricao": i.get("Descricao") or i.get("descricao"),
             "complemento": i.get("Complemento") or i.get("complemento")} for i in itens]
```

> Conferir no Swagger oficial (`/SefinNacional/swagger`) os nomes exatos dos campos de resposta (`chaveAcesso`, `nfseXmlGZipB64`, `alertas`) e do corpo de eventos antes de fechar a Fase 4. Em produção restrita, a habilitação do CNPJ para uso de API/sistema próprio pode ser exigida (erro genérico E999 é sintoma comum).

### 6.7 Orquestração (`fiscal/services/emissao.py` + `tasks.py`)

```python
from django.db import transaction
from django.utils import timezone

@transaction.atomic
def reservar_numero(config, tipo: str, serie: str) -> int:
    seq = (SequenciaNumeracao.objects.select_for_update()
           .get(empresa=config.empresa, tipo=tipo, serie=serie))
    seq.ultimo_numero += 1
    seq.save(update_fields=["ultimo_numero"])
    return seq.ultimo_numero


def preparar_emissao(nota):
    erros = validar_regras_locais(nota)        # NBS, cTribNac, tomador completo, competência aberta,
    if erros:                                  # certificado válido, certidões do contrato vigentes (aviso)
        raise ValidacaoFiscal(erros)
    transmitir(nota)                          # 6.14.3: escolhe canal, aplica travas e numera


# tasks.py
@shared_task(bind=True, autoretry_for=(httpx.TransportError,), retry_backoff=30, max_retries=5)
def transmitir_nota(self, nota_id, canal):
    nota = NotaFiscal.objects.select_for_update(skip_locked=True).get(pk=nota_id)
    prov = get_provedor(nota.config_fiscal, canal)   # registra TentativaTransmissao(canal=canal)

    if nota.status == "ERRO_COMUNICACAO" and nota.id_dps:     # idempotência
        r = prov.consultar(nota)
        if r.sucesso:
            return concluir_autorizacao(nota, r)

    nota.status = "TRANSMITINDO"; nota.save(update_fields=["status"])
    try:
        r = prov.emitir(nota)
    except httpx.TransportError:
        nota.status = "ERRO_COMUNICACAO"; nota.save(update_fields=["status"])
        raise
    registrar_log("SEFIN", "emitir", nota, r)
    return concluir_autorizacao(nota, r) if r.sucesso else registrar_rejeicao(nota, r)


def concluir_autorizacao(nota, r):
    nota.chave_acesso = r.chave_acesso
    nota.status = "AUTORIZADA"
    salvar_xmls(nota, r)
    nota.save()
    baixar_danfse.delay(str(nota.pk))
    criar_conta_a_receber(nota)            # financeiro.Lancamento(status=PENDENTE, valor=valor_liquido)
    atualizar_competencia(nota)
    if not nota.iss_retido:
        vincular_guia_iss(nota)            # GuiaISS da competência, status A_DECLARAR
    enviar_nf_ao_tomador.delay(str(nota.pk))
```

**Regra de numeração:** número de DPS rejeitada por erro de schema/regra (antes de gerar NFS-e) pode ser reaproveitado na correção, pois o identificador é a DPS; **nunca** reaproveitar número de DPS que gerou NFS-e. Na dúvida, consultar `/dps/{idDps}`.

### 6.8 Cálculo (`fiscal/services/calculo.py`)

```python
from decimal import Decimal, ROUND_HALF_UP
D2 = Decimal("0.01")

def r2(v): return Decimal(v).quantize(D2, rounding=ROUND_HALF_UP)

def calcular(nota, perfil):
    base = nota.valor_servicos - nota.valor_deducoes - nota.desconto_incondicionado
    nota.base_calculo = r2(base)
    nota.aliquota_iss = perfil.aliquota_iss if not nota.empresa.optante_simples else nota.aliquota_iss
    nota.valor_iss = r2(base * nota.aliquota_iss / 100)          # ex. ABRASF: 1232,25 × 5% = 61,61
    nota.iss_retido = perfil.iss_retido
    nota.valor_iss_retido = nota.valor_iss if perfil.iss_retido else Decimal("0")
    vs = nota.valor_servicos
    nota.valor_ir     = r2(vs * perfil.aliquota_ir / 100)     if perfil.reter_ir     else Decimal("0")
    nota.valor_inss   = r2(vs * perfil.aliquota_inss / 100)   if perfil.reter_inss   else Decimal("0")
    nota.valor_pis    = r2(vs * perfil.aliquota_pis / 100)    if perfil.reter_pis    else Decimal("0")
    nota.valor_cofins = r2(vs * perfil.aliquota_cofins / 100) if perfil.reter_cofins else Decimal("0")
    nota.valor_csll   = r2(vs * perfil.aliquota_csll / 100)   if perfil.reter_csll   else Decimal("0")
    retencoes = (nota.valor_ir + nota.valor_inss + nota.valor_pis + nota.valor_cofins
                 + nota.valor_csll + nota.outras_retencoes + nota.valor_iss_retido)
    nota.valor_liquido = r2(vs - retencoes - nota.desconto_incondicionado - nota.desconto_condicionado)
    return nota
```

Regras de negócio derivadas do POP E&L:
- **Desconto incondicionado** reduz a base de cálculo; **condicionado** não reduz (só o líquido).
- Optante do Simples: alíquota informada pelo usuário (faixa do mês); MEI: alíquota zero.
- ISS **retido** = recolhido pelo tomador (não gera GuiaISS para a KS TEC); **não retido** = KS TEC declara e paga via DAM no portal municipal.

### 6.9 Provedor E&L ABRASF 2.04 — emissão completa (`fiscal/providers/el_abrasf.py`)

Canal **de primeira classe**, com a mesma interface do Nacional: emitir (`GerarNfse` síncrono), consultar (`ConsultarNfseRps`), cancelar (`CancelarNfse`). Também atende o legado (competências até 12/2025) e outros municípios em E&L. Segue o formato dos exemplos do ZIP: SOAP com cabeçalho e dados em CDATA, assinatura RSA-SHA1.

**Builder (`fiscal/xml/abrasf_builder.py`)** — ordem de tags conforme `nfse_v2-04.xsd` (v1.02):

```python
from decimal import Decimal
from lxml import etree

NS = "http://www.abrasf.org.br/nfse.xsd"


def _e(pai, tag, texto=None):
    el = etree.SubElement(pai, f"{{{NS}}}{tag}")
    if texto is not None:
        el.text = str(texto)
    return el


def _v(x: Decimal) -> str:
    return f"{x.quantize(Decimal('0.01'))}"


def _cpf_cnpj(pai, doc: str):
    cc = _e(pai, "CpfCnpj")
    _e(cc, "Cnpj" if len(doc) == 14 else "Cpf", doc)


def montar_declaracao(pai, nota) -> str:
    """Monta <Rps> (tcDeclaracaoPrestacaoServico) dentro de `pai`. Retorna o Id a assinar."""
    emp, t = nota.empresa, nota.tomador_snapshot
    id_inf = f"rps{nota.rps_serie}{nota.rps_numero}"
    rps = _e(pai, "Rps")
    inf = _e(rps, "InfDeclaracaoPrestacaoServico"); inf.set("Id", id_inf)

    r = _e(inf, "Rps"); r.set("Id", f"r{id_inf}")
    ident = _e(r, "IdentificacaoRps")
    _e(ident, "Numero", nota.rps_numero); _e(ident, "Serie", nota.rps_serie); _e(ident, "Tipo", 1)
    _e(r, "DataEmissao", nota.data_emissao.date().isoformat())
    _e(r, "Status", 1)

    _e(inf, "Competencia", nota.competencia.isoformat())

    s = _e(inf, "Servico")
    v = _e(s, "Valores")
    _e(v, "ValorServicos", _v(nota.valor_servicos))
    _e(v, "ValorDeducoes", _v(nota.valor_deducoes))
    _e(v, "ValorPis", _v(nota.valor_pis)); _e(v, "ValorCofins", _v(nota.valor_cofins))
    _e(v, "ValorInss", _v(nota.valor_inss)); _e(v, "ValorIr", _v(nota.valor_ir))
    _e(v, "ValorCsll", _v(nota.valor_csll)); _e(v, "OutrasRetencoes", _v(nota.outras_retencoes))
    _e(v, "ValorIss", _v(nota.valor_iss)); _e(v, "Aliquota", f"{nota.aliquota_iss.normalize()}")
    _e(v, "DescontoIncondicionado", _v(nota.desconto_incondicionado))
    _e(v, "DescontoCondicionado", _v(nota.desconto_condicionado))
    _e(s, "IssRetido", 1 if nota.iss_retido else 2)
    if nota.iss_retido:
        _e(s, "ResponsavelRetencao", 1)                       # 1 = tomador
    _e(s, "ItemListaServico", nota.item_lc116)                # "01.07"
    if nota.cnae:
        _e(s, "CodigoCnae", nota.cnae)
    if nota.codigo_tributacao_municipal:
        _e(s, "CodigoTributacaoMunicipio", nota.codigo_tributacao_municipal)
    _e(s, "CodigoServicoNacional", nota.codigo_tributacao_nacional)   # obrigatório (EL97/EL98)
    _e(s, "CodigoNbs", nota.nbs)                                      # obrigatório (EL101/EL102)
    _e(s, "Discriminacao", nota.discriminacao[:2000])
    _e(s, "CodigoMunicipio", nota.local_prestacao_ibge)
    _e(s, "ExigibilidadeISS", nota.exigibilidade_iss or 1)
    _e(s, "MunicipioIncidencia", nota.local_prestacao_ibge)

    p = _e(inf, "Prestador")
    _cpf_cnpj(p, emp.cnpj)
    _e(p, "InscricaoMunicipal", emp.inscricao_municipal)      # exatamente como na prefeitura

    tom = _e(inf, "TomadorServico")
    it = _e(tom, "IdentificacaoTomador"); _cpf_cnpj(it, t["cpf_cnpj"])
    if t.get("inscricao_municipal"):
        _e(it, "InscricaoMunicipal", t["inscricao_municipal"])
    _e(tom, "RazaoSocial", t["razao_social"][:150])
    end = _e(tom, "Endereco")
    _e(end, "Endereco", t["logradouro"]); _e(end, "Numero", t.get("numero") or "S/N")
    if t.get("complemento"):
        _e(end, "Complemento", t["complemento"])
    _e(end, "Bairro", t["bairro"]); _e(end, "CodigoMunicipio", t["municipio_ibge"])
    _e(end, "Uf", t["uf"]); _e(end, "Cep", t["cep"])
    if t.get("email"):
        _e(_e(tom, "Contato"), "Email", t["email"])

    if emp.regime_especial_tributacao:
        _e(inf, "RegimeEspecialTributacao", emp.regime_especial_tributacao)
    _e(inf, "OptanteSimplesNacional", 1 if emp.optante_simples else 2)
    _e(inf, "IncentivoFiscal", 2)
    if nota.informacoes_complementares:
        _e(inf, "InformacoesComplementares", nota.informacoes_complementares[:2000])
    return rps, id_inf


def montar_gerar_nfse(nota):
    raiz = etree.Element(f"{{{NS}}}GerarNfseEnvio", nsmap={None: NS})
    rps, id_inf = montar_declaracao(raiz, nota)
    return raiz, rps, id_inf


def montar_consulta_rps(nota):
    raiz = etree.Element(f"{{{NS}}}ConsultarNfseRpsEnvio", nsmap={None: NS})
    ident = _e(raiz, "IdentificacaoRps")
    _e(ident, "Numero", nota.rps_numero); _e(ident, "Serie", nota.rps_serie); _e(ident, "Tipo", 1)
    p = _e(raiz, "Prestador"); _cpf_cnpj(p, nota.empresa.cnpj)
    _e(p, "InscricaoMunicipal", nota.empresa.inscricao_municipal)
    return raiz


def montar_cancelamento(nota, codigo: int):
    """codigo: 1 erro na emissão · 2 serviço não prestado · 4 duplicidade."""
    raiz = etree.Element(f"{{{NS}}}CancelarNfseEnvio", nsmap={None: NS})
    pedido = _e(raiz, "Pedido")
    id_ped = f"canc{nota.numero_nfse}"
    inf = _e(pedido, "InfPedidoCancelamento"); inf.set("Id", id_ped)
    idn = _e(inf, "IdentificacaoNfse")
    _e(idn, "Numero", nota.numero_nfse); _cpf_cnpj(idn, nota.empresa.cnpj)
    _e(idn, "InscricaoMunicipal", nota.empresa.inscricao_municipal)
    _e(idn, "CodigoMunicipio", nota.empresa.municipio_ibge)
    _e(inf, "CodigoCancelamento", codigo)
    return raiz, pedido, id_ped
```

**Provedor:**

```python
import httpx
from lxml import etree
from .base import ProvedorNFSe, ResultadoFiscal
from ..certificado import certificado_em_arquivos
from ..xml.assinatura import assinar, validar_xsd
from ..xml import abrasf_builder as ab

XSD_ABRASF = "apps/fiscal/xml/schemas/abrasf/nfse_v2-04.xsd"   # do layout_rps_2_04_102.zip
CABEC = ('<cabecalho xmlns="http://www.abrasf.org.br/nfse.xsd">'
         '<versaoDados>2.04</versaoDados></cabecalho>')
ENVELOPE = ('<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
            'xmlns:nfse="http://nfse.abrasf.org.br"><soapenv:Header/><soapenv:Body>'
            '<nfse:{op}><nfse:{op}Request>'
            '<nfseCabecMsg><![CDATA[{cabec}]]></nfseCabecMsg>'
            '<nfseDadosMsg><![CDATA[{dados}]]></nfseDadosMsg>'
            '</nfse:{op}Request></nfse:{op}></soapenv:Body></soapenv:Envelope>')
NS = {"a": "http://www.abrasf.org.br/nfse.xsd"}


class ProvedorElAbrasf(ProvedorNFSe):

    def _chamar(self, operacao: str, dados: etree._Element) -> tuple[bytes, etree._Element]:
        xml = etree.tostring(dados, encoding="UTF-8", xml_declaration=True)
        envelope = ENVELOPE.format(op=operacao, cabec=CABEC, dados=xml.decode("utf-8"))
        with certificado_em_arquivos(self.certificado) as (cert_p, key_p, *_):
            r = httpx.post(self.config.url_el, content=envelope.encode("utf-8"),
                           headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""},
                           cert=(cert_p, key_p), timeout=httpx.Timeout(60, connect=15))
        r.raise_for_status()
        output = etree.fromstring(r.content).find(".//outputXML")   # retorno em CDATA
        return xml, etree.fromstring(output.text.encode("utf-8"))

    def emitir(self, nota) -> ResultadoFiscal:
        raiz, rps, id_inf = ab.montar_gerar_nfse(nota)
        with certificado_em_arquivos(self.certificado) as (_, _, key_pem, cert_pem):
            assinar(rps, id_inf, key_pem, cert_pem, "sha1")     # Signature vai dentro de <Rps>
        erros = validar_xsd(raiz, XSD_ABRASF)
        if erros:
            return ResultadoFiscal(False, erros=[{"codigo": "XSD", "descricao": e} for e in erros])
        enviado, resp = self._chamar("GerarNfse", raiz)
        return self._ler_nfse(resp, enviado)

    def consultar(self, nota) -> ResultadoFiscal:
        enviado, resp = self._chamar("ConsultarNfseRps", ab.montar_consulta_rps(nota))
        return self._ler_nfse(resp, enviado)

    def cancelar(self, nota, codigo_motivo, justificativa) -> ResultadoFiscal:
        raiz, pedido, id_ped = ab.montar_cancelamento(nota, int(codigo_motivo))
        with certificado_em_arquivos(self.certificado) as (_, _, key_pem, cert_pem):
            assinar(pedido, id_ped, key_pem, cert_pem, "sha1")
        enviado, resp = self._chamar("CancelarNfse", raiz)
        ok = resp.find(".//a:RetCancelamento", NS) is not None
        return ResultadoFiscal(ok, xml_enviado=enviado, xml_retorno=etree.tostring(resp),
                               erros=[] if ok else self.ler_erros(resp))

    def _ler_nfse(self, resp, enviado) -> ResultadoFiscal:
        inf = resp.find(".//a:CompNfse/a:Nfse/a:InfNfse", NS)
        if inf is None:
            return ResultadoFiscal(False, xml_enviado=enviado, xml_retorno=etree.tostring(resp),
                                   erros=self.ler_erros(resp))
        return ResultadoFiscal(True, numero_nfse=inf.findtext("a:Numero", namespaces=NS),
                               codigo_verificacao=inf.findtext("a:CodigoVerificacao", namespaces=NS),
                               xml_enviado=enviado, xml_retorno=etree.tostring(resp))

    @staticmethod
    def ler_erros(resp) -> list[dict]:
        return [{"codigo": m.findtext("a:Codigo", namespaces=NS),
                 "descricao": m.findtext("a:Mensagem", namespaces=NS),
                 "complemento": m.findtext("a:Correcao", namespaces=NS)}
                for m in resp.iterfind(".//a:MensagemRetorno", NS)]
```

Notas de implementação do canal E&L:
- **URL do webservice** (`config.url_el`): não consta nos arquivos; obter com a prefeitura/E&L. Se houver WSDL, conferir nome das operações e se o `SOAPAction` é exigido.
- **Sem ambiente de homologação** conhecido para Valença: todo teste E&L é em produção (ver protocolo 6.14.4).
- **Assinatura SHA1:** se o `signxml` recusar, usar `python-xmlsec` neste provedor. Validar a primeira assinatura com `xmlsec1 --verify`.
- **PDF:** o E&L não devolve PDF pela API; gerar representação própria a partir do XML com link "Autenticar documento" do portal (código de verificação).
- **Numeração RPS** independente da DPS (sequência `RPS_EL`).

Mapeamento ABRASF 2.04 → DPS Nacional (para o builder e para o importador):

| ABRASF 2.04 (E&L) | DPS Nacional | Observação |
|---|---|---|
| `IdentificacaoRps/Numero, Serie` | `nDPS`, `serie` | |
| `Competencia` | `dCompet` | |
| `Valores/ValorServicos` | `valores/vServPrest/vServ` | |
| `IssRetido` (1 sim/2 não) | `tribMun/tpRetISSQN` | domínios diferentes — mapear |
| `ItemListaServico` (01.07) | — | substituído por `cTribNac` |
| `CodigoServicoNacional` (010701) | `cServ/cTribNac` | |
| `CodigoNbs` | `cServ/cNBS` | |
| `CodigoTributacaoMunicipio` | `cServ/cTribMun` | |
| `Discriminacao` | `cServ/xDescServ` | |
| `CodigoMunicipio` / `MunicipioIncidencia` | `locPrest/cLocPrestacao` | |
| `ExigibilidadeISS` | `tribMun/tribISSQN` | mapear domínios |
| `RegimeEspecialTributacao` | `prest/regTrib/regEspTrib` | |
| `OptanteSimplesNacional` | `prest/regTrib/opSimpNac` | |
| `TomadorServico/*` | `toma/*` | |

### 6.10 Cliente E&L Aceites/DAPS (`fiscal/providers/el_aceites.py`)

```python
import httpx

class ElAceitesClient:
    """API REST E&L de importação de aceites (DAPS) — serviços TOMADOS pela KS TEC."""

    def __init__(self, base_url, login, senha, inscricao_municipal, cnpj_prefeitura):
        self.base = base_url.rstrip("/")
        self.cred = {"login": login, "senha": senha,
                     "inscricaoMunicipal": inscricao_municipal,      # exatamente como na prefeitura
                     "cnpjPrefeitura": "".join(filter(str.isdigit, cnpj_prefeitura))}
        self._chave = None

    def autenticar(self) -> str:
        r = httpx.post(f"{self.base}/api/public/daps/autenticar", json=self.cred, timeout=30)
        if r.status_code != 201:
            raise ErroEl(r.status_code, r.text)
        # O manual diz apenas "retornará a chave": tratar texto puro ou JSON.
        try:
            corpo = r.json()
            self._chave = corpo if isinstance(corpo, str) else next(iter(corpo.values()))
        except ValueError:
            self._chave = r.text.strip().strip('"')
        return self._chave

    def _h(self):
        return {"Content-Type": "application/json", "aceites_autenticacao": self._chave or self.autenticar()}

    def criar(self, daps: list[dict]) -> list[dict]:
        """Retorna o mesmo JSON + codigoVerificacao e tipoRegistro (D=DAPS criada, N=nota encontrada)."""
        r = httpx.post(f"{self.base}/api/public/daps/criar", json=daps, headers=self._h(), timeout=60)
        if r.status_code != 201:
            raise ErroEl(r.status_code, r.text)
        return r.json()

    def cancelar(self, codigo_verificacao: str):
        r = httpx.post(f"{self.base}/api/public/daps/cancelar",
                       params={"codigo_verificacao": codigo_verificacao}, headers=self._h(), timeout=30)
        if r.status_code != 200:
            raise ErroEl(r.status_code, r.text)

    def status(self, codigo_verificacao: str) -> dict | None:
        r = httpx.post(f"{self.base}/api/public/daps/status_por_codigo_verificacao",
                       params={"codigo_verificacao": codigo_verificacao}, headers=self._h(), timeout=30)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()


def daps_para_json(d) -> dict:
    """Serializa fiscal.Daps no layout do arquivo criar_aceite.json."""
    f = d.fornecedor
    return {
        "numeroNota": int(d.numero_nota),
        "dataEmissao": d.data_emissao.isoformat(),
        "dataFatoGerador": d.data_fato_gerador.isoformat(),
        "valor": float(d.valor), "valorDeducao": float(d.valor_deducao), "aliquota": float(d.aliquota),
        "tomador": {"tipo": "J", "cpfCnpj": d.empresa.cnpj,
                    "inscricaoMunicipal": d.empresa.inscricao_municipal},
        "prestador": {
            "tipo": f.tipo, "cpfCnpj": f.cpf_cnpj, "inscricaoMunicipal": f.inscricao_municipal or None,
            "nome": f.razao_social, "cep": f.endereco.cep, "codigoIbge": int(f.endereco.municipio_ibge),
            "nomeBairro": f.endereco.bairro, "nomeTipoLogradouro": f.endereco.tipo_logradouro,
            "nomeLogradouro": f.endereco.logradouro, "numero": f.endereco.numero,
            "email": f.email,
        },
        "regimeTributacao": d.regime_tributacao, "tipoNota": d.tipo_nota,
        "tipoRecolhimento": d.tipo_recolhimento, "codigoServico": d.codigo_servico,
        "discriminacaoServico": d.discriminacao, "codigoIbgePrestacao": int(d.codigo_ibge_prestacao),
    }
```

### 6.11 Importador de histórico E&L (`fiscal/services/importador_el.py`)

- Aceita múltiplos XMLs (o portal limita a exportação a 90 dias por arquivo) ou um ZIP.
- Percorre `//a:CompNfse/a:Nfse/a:InfNfse`, extrai `Numero`, `CodigoVerificacao`, `DataEmissao`, `ValoresNfse/*`, `DeclaracaoPrestacaoServico/InfDeclaracaoPrestacaoServico/*`, tomador.
- Cria `NotaFiscal(provedor="IMPORTADA", status="AUTORIZADA")`, faz *match* de tomador por CNPJ e tenta vincular ao contrato pelo tomador + período de vigência (sugestão confirmada pelo usuário em tela de revisão).
- Idempotente por `(numero_nfse, codigo_verificacao)`.

### 6.12 Guia de ISS (fluxo assistido, não automatizado)

Como a guia continua sendo gerada no portal municipal:
1. No dia 1 de cada mês, task cria `GuiaISS(status=A_DECLARAR)` com as notas não retidas da competência anterior e o valor calculado.
2. Tarefa no painel: "Declarar competência MM/AAAA no portal municipal" com passo a passo do POP (Nota Fiscal > Declaração > selecionar notas > Declarar > Encerrar > Impressão Boleto).
3. Usuário anexa o PDF do DAM e informa vencimento/valor → sistema compara com o calculado (alerta se diferença > R$ 0,05) e cria `Lancamento` de despesa "ISS próprio".
4. Pagamento do lançamento marca a guia como `PAGA`.

### 6.13 Erros traduzidos (`fiscal/erros.py`, semente)

| Código | Origem | Mensagem ao usuário | Campo |
|---|---|---|---|
| EL97 | E&L | Código de serviço nacional ausente ou inválido. Confira o cadastro do item no catálogo. | `codigo_tributacao_nacional` |
| EL98 | E&L | O código nacional não corresponde ao serviço municipal escolhido. | `codigo_tributacao_nacional` |
| EL101 | E&L | Código NBS ausente ou inválido (obrigatório desde 01/2026). | `nbs` |
| EL102 | E&L | O NBS não corresponde ao serviço nacional informado. Veja a correlação no catálogo. | `nbs` |
| RNG6159 | Sefin | A mensagem enviada não foi reconhecida (provável erro no JSON/GZip/Base64). | — (técnico) |
| E999 | Sefin | Erro não catalogado no ambiente nacional. Verifique habilitação do CNPJ para emissão via API e a assinatura. | — (técnico) |
| XSD | Local | Estrutura do XML inválida: {detalhe}. | conforme XPath |

### 6.14 Estratégia de duplo canal (Nacional × E&L)

O sistema emite pelos **dois canais em produção**, escolhidos por nota, para que a KS TEC teste e use o que funcionar. O risco central é **emitir a mesma prestação duas vezes** (uma em cada canal). Tudo nesta seção existe para impedir isso.

#### 6.14.1 Regras de ouro

1. **Uma NotaFiscal = uma prestação = no máximo uma NFS-e válida**, em qualquer canal. O canal é um atributo da tentativa, não da nota.
2. **Troca de canal só com resultado definitivo.** Pode tentar o outro canal apenas se a tentativa anterior terminou em `REJEITADA` com erros retornados pelo fisco (prova de que nada foi gerado).
3. **Timeout nunca libera troca.** Em `ERRO_COMUNICACAO`, consultar o canal original (`GET /dps/{idDps}` no Nacional; `ConsultarNfseRps` no E&L). Se a consulta também falhar, a troca exige ação manual: "Verifiquei no portal e a nota NÃO foi gerada" + justificativa, registrada em auditoria.
4. **Fallback automático desligado por padrão.** Se ligado (`ConfiguracaoFiscal.fallback_automatico`), só dispara para códigos de erro listados em `fiscal.erros_permitem_fallback` (ex.: canal desativado, contribuinte não habilitado no canal), nunca para erros de dados (NBS, tomador, valores), que falhariam também no outro canal.
5. **Antes de transmitir em qualquer canal**, verificar se já existe NFS-e autorizada para o mesmo `(tomador, competência, contrato, valor)` em qualquer canal; se existir, bloquear com aviso de possível duplicidade.
6. **Nota autorizada em um canal é cancelada no mesmo canal.** Cancelamento e substituição sempre pelo canal de origem.

#### 6.14.2 Modelo de dados (complementos)

- `ConfiguracaoFiscal`: `canais_habilitados (multiselect NACIONAL, EL_ABRASF)`, `canal_padrao`, `fallback_automatico (bool, default False)`, `url_el`, `el_permite_competencia_atual (bool)` — interruptor explícito que libera o E&L para competências ≥ 01/2026.
- `NotaFiscal`: `provedor` passa a indicar o **canal que autorizou**; novos campos `rps_serie`, `rps_numero`, `localizada_adn (bool)?`, `verificada_adn_em?`.
- **TentativaTransmissao** (novo) — `nota (FK)`, `canal`, `numero_tentativa`, `iniciada_em`, `concluida_em?`, `resultado (AUTORIZADA, REJEITADA, ERRO_COMUNICACAO, INCONCLUSIVA)`, `erros (JSONB)`, `xml_enviado (Anexo)`, `xml_retorno (Anexo)?`, `duracao_ms`, `liberacao_manual_por (FK Usuario)?`, `justificativa_liberacao?`.

#### 6.14.3 Orquestração

```python
# fiscal/services/canais.py
class TrocaDeCanalBloqueada(Exception): ...

def pode_tentar_canal(nota, canal: str) -> tuple[bool, str]:
    ultima = nota.tentativas.order_by("-iniciada_em").first()
    if nota.status == "AUTORIZADA":
        return False, f"Nota já autorizada no canal {nota.provedor}."
    if existe_duplicidade_provavel(nota):
        return False, "Já existe NFS-e autorizada para este tomador/competência/valor."
    if canal == "EL_ABRASF" and nota.competencia.year >= 2026 \
            and not nota.config_fiscal.el_permite_competencia_atual:
        return False, "Canal E&L não liberado para competências de 2026 (ver Configuração Fiscal)."
    if ultima is None or ultima.canal == canal:
        return True, ""
    if ultima.resultado == "REJEITADA" and ultima.erros:
        return True, ""
    if ultima.liberacao_manual_por_id:
        return True, ""
    return False, (f"A última tentativa no canal {ultima.canal} terminou como {ultima.resultado}. "
                   "Consulte o canal original ou registre a verificação manual antes de trocar.")


def transmitir(nota, canal: str | None = None, usuario=None):
    canal = canal or nota.config_fiscal.canal_padrao
    ok, motivo = pode_tentar_canal(nota, canal)
    if not ok:
        raise TrocaDeCanalBloqueada(motivo)
    if canal == "NACIONAL" and not nota.numero_dps:
        nota.numero_dps = reservar_numero(nota.config_fiscal, "DPS", nota.serie_dps)
    if canal == "EL_ABRASF" and not nota.rps_numero:
        nota.rps_numero = reservar_numero(nota.config_fiscal, "RPS_EL", nota.rps_serie)
    nota.status = "NA_FILA"; nota.save()
    transmitir_nota.delay(str(nota.pk), canal)       # task de 6.7, agora recebe o canal


# Dentro da task, após REJEITADA:
def talvez_fallback(nota, tentativa):
    cfg = nota.config_fiscal
    outro = "EL_ABRASF" if tentativa.canal == "NACIONAL" else "NACIONAL"
    codigos = set(Parametro.get("fiscal.erros_permitem_fallback", []))
    if (cfg.fallback_automatico and outro in cfg.canais_habilitados
            and any(e["codigo"] in codigos for e in tentativa.erros)):
        transmitir(nota, outro)
```

#### 6.14.4 Verificações pós-emissão

- **Nota emitida pelo E&L:** task D+1 consulta a distribuição de DF-e do ADN (API do contribuinte, por NSU) para confirmar que a nota foi compartilhada com o ambiente nacional. Não localizada em 48h → alerta "Nota E&L nº X não encontrada no ADN" e flag `localizada_adn = False`. Esse é o teste objetivo de que o canal municipal está funcionando como intermediário.
- **Nota emitida pelo Nacional:** verificar, no fluxo da GuiaISS, se ela aparece no portal municipal para declaração/DAM (checklist manual com campo "apareceu no portal: sim/não").
- O painel fiscal mostra, por canal: tentativas, taxa de autorização, tempo médio, notas não localizadas no ADN.

#### 6.14.5 Interface

- Passo 3 do assistente de emissão: seletor **Canal** (`Nacional` | `Municipal E&L`) com o padrão pré-selecionado e um selo do estado do canal (último sucesso, taxa de autorização).
- Se o E&L estiver selecionado para competência ≥ 01/2026, faixa âmbar: "O comunicado da Prefeitura indica emissão exclusiva pelo Emissor Nacional desde 01/2026. Use este canal apenas para teste ou com confirmação formal."
- Na nota rejeitada: botão **"Tentar pelo outro canal"**, habilitado apenas quando `pode_tentar_canal()` permitir; caso contrário, mostra o motivo e o botão "Registrar verificação manual".
- Linha do tempo da nota lista todas as tentativas, por canal, com XML enviado/recebido.

#### 6.14.6 Protocolo de teste em produção

Como o E&L de Valença não tem homologação conhecida, o teste é feito em produção, de forma controlada:

1. Nacional primeiro em **produção restrita** (sem valor fiscal) até emitir, consultar e cancelar.
2. Escolher um **tomador colaborador** (cliente privado avisado previamente) e um serviço real de baixo valor.
3. Emitir **uma** nota pelo E&L. Registrar resposta, número, código de verificação.
4. Conferir: aparece no portal municipal? Aparece no ADN em até 48h (6.14.4)? DANFSe/consulta pública funciona?
5. Se o resultado for duvidoso, **cancelar no mesmo dia** pelo E&L com código 1 (erro na emissão) e emitir pelo Nacional.
6. Repetir com uma nota pelo Nacional em produção, conferindo se aparece no portal municipal para gerar o DAM.
7. Registrar tudo no **Diário de testes fiscais** (`Anexo` vinculado à ConfiguracaoFiscal) e só então definir o `canal_padrao`.

> Guardar a resposta formal da Secretaria de Fazenda sobre o canal válido. Se uma nota emitida pelo E&L em 2026 for considerada inválida, essa resposta e o diário de testes são a documentação de boa-fé.

---

## 7. Monitoramento e SLA

### 7.1 Verificação (Celery beat a cada minuto despacha os sistemas "vencidos")

```python
# sla/tasks.py
import ssl, socket, time, httpx
from datetime import datetime, timezone as tz
from urllib.parse import urlparse

@shared_task
def despachar_verificacoes():
    agora = timezone.now()
    for s in Sistema.objects.filter(ativo=True):
        if not s.ultima_verificacao_em or (agora - s.ultima_verificacao_em).total_seconds() >= s.intervalo_min * 60:
            verificar_sistema.delay(str(s.pk))

@shared_task(soft_time_limit=40)
def verificar_sistema(sistema_id):
    s = Sistema.objects.get(pk=sistema_id)
    if JanelaManutencao.objects.filter(sistema=s, inicio__lte=timezone.now(), fim__gte=timezone.now()).exists():
        return registrar(s, sucesso=True, manutencao=True)
    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=s.timeout_s, follow_redirects=True,
                          headers={"User-Agent": "KS-CENTRAL-Monitor/1.0", **(s.headers or {})}) as c:
            r = c.request(s.metodo, s.url)
        ms = int((time.perf_counter() - t0) * 1000)
        ok = r.status_code == s.status_esperado and (not s.palavra_chave or s.palavra_chave in r.text)
        erro = None if ok else f"HTTP {r.status_code}" + ("" if s.palavra_chave in r.text else " / palavra-chave ausente")
        health = consultar_health(s) if s.url_health else None
        registrar(s, ok, r.status_code, ms, erro, health)
    except httpx.HTTPError as e:
        registrar(s, False, None, None, type(e).__name__)
    if s.verificar_ssl:
        s.ssl_expira_em = validade_ssl(urlparse(s.url).hostname)

def validade_ssl(host, porta=443):
    ctx = ssl.create_default_context()
    with socket.create_connection((host, porta), timeout=10) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as ss:
            cert = ss.getpeercert()
    return datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=tz.utc)
```

Regras de incidente (evita falso positivo):
- Abre `Incidente` após **2 falhas consecutivas**; antes de abrir, faz **re-checagem imediata** (30s depois). Opcional: segunda sonda externa (outra VPS ou função serverless) para confirmar que a falha não é da rede da própria VPS.
- Fecha o incidente após 2 sucessos consecutivos; `duracao_min = fim − inicio`.
- `tempo_resposta > 3× p95 dos últimos 7 dias` por 3 checagens → incidente `LENTIDAO` (não conta como indisponível, aparece no relatório).
- Notifica (app + e-mail; WhatsApp opcional) na abertura e no fechamento. Alerta de SSL a 30/15/7 dias.

### 7.2 Cálculo de disponibilidade

```
minutos_periodo      = minutos do período dentro do horario_cobertura
minutos_manutencao   = interseção com JanelaManutencao comunicada
minutos_indisponivel = soma da duração de incidentes TOTAL (fora de manutenção)
                     + 50% da duração de incidentes PARCIAL (parametrizável)

disponibilidade (%)  = (minutos_periodo − minutos_manutencao − minutos_indisponivel)
                       / (minutos_periodo − minutos_manutencao) × 100
```
Referência: 99,5% em 30 dias ≈ 3h36min de indisponibilidade tolerada; 99,9% ≈ 43min.

Agregação: task diária 00:15 gera `AgregadoDiario`; verificações brutas com mais de 90 dias são apagadas (o agregado fica para sempre).

### 7.3 Contrato da futura API de saúde (`/api/health`)

Para os sistemas da própria KS TEC (PRISMA, SIGAL, etc.), padronizar um endpoint protegido por token:

```json
GET /api/health   Authorization: Bearer <token>
{
  "status": "ok",                    // ok | degraded | down
  "versao": "2.3.1",
  "timestamp": "2026-10-08T10:00:00-03:00",
  "componentes": {
    "banco":   {"status": "ok", "latencia_ms": 4},
    "fila":    {"status": "ok", "pendentes": 0},
    "disco":   {"status": "ok", "uso_pct": 61},
    "storage": {"status": "ok"},
    "ia":      {"status": "degraded", "detalhe": "timeout Gemini"}
  },
  "metricas": {"usuarios_ativos_24h": 37, "requisicoes_1h": 1820, "erros_5xx_1h": 0}
}
```
Fornecer um app Django reutilizável `ks_health` (pacote interno) para instalar nos sistemas da KS TEC.

### 7.4 Relatório de SLA (PDF mensal por contrato)

Capa com logo · período · tabela por sistema (disponibilidade, meta, atingiu?, tempo médio, p95, nº incidentes) · gráfico de barras diário · lista de incidentes (início, fim, duração, causa, ação) · janelas de manutenção comunicadas · validade SSL · nota metodológica (intervalo de checagem, critério de incidente, fórmula) · assinatura do responsável técnico.

---

## 8. Relatórios de atividades + IA Gemini

### 8.1 Fluxo

1. Ao longo do mês, a equipe registra **Tarefas** por contrato com `resumo_para_relatorio` e evidências.
2. Dia 1 (ou sob demanda), "Gerar relatório da competência": cria `RelatorioAtividades` com seções:
   1. Identificação (contrato, objeto, órgão, período, responsável técnico)
   2. Introdução
   3. Atividades realizadas — agrupadas por **tipo** de tarefa, cada item com data, descrição, status e protocolo do cliente
   4. Indicadores do período (nº de chamados, tempo médio de atendimento, horas, disponibilidade — puxa do SLA)
   5. Evidências (imagens com legenda)
   6. Pendências e próximos passos (tarefas abertas)
   7. Considerações finais
3. Botão **"Refinar com IA"** por seção ou no relatório inteiro → abre `diff_view` original × refinado; usuário aceita/rejeita por parágrafo; nada é aplicado sem aceite.
4. Aprovar → gera PDF (WeasyPrint) e DOCX (docxtpl), com hash SHA-256 no rodapé; anexa à `Competencia`.

### 8.2 Cliente Gemini (`ia/services/gemini.py`)

```python
from django.conf import settings
from google import genai
from google.genai import types


class ClienteGemini:
    def __init__(self):
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)

    def gerar(self, template: "PromptTemplate", variaveis: dict, objeto=None, usuario=None) -> str:
        prompt = template.template_usuario.format(**variaveis)
        inicio = time.perf_counter()
        try:
            resp = self.client.models.generate_content(
                model=template.modelo or settings.GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=template.system_instruction,
                    temperature=float(template.temperatura),
                    max_output_tokens=template.max_tokens,
                ),
            )
            texto = resp.text or ""
            uso = resp.usage_metadata
            ChamadaIA.objects.create(template=template, usuario=usuario, objeto=objeto,
                                     entrada=prompt, saida=texto, modelo=template.modelo,
                                     tokens_entrada=uso.prompt_token_count,
                                     tokens_saida=uso.candidates_token_count,
                                     latencia_ms=int((time.perf_counter() - inicio) * 1000), sucesso=True)
            return texto
        except Exception as e:
            ChamadaIA.objects.create(template=template, usuario=usuario, objeto=objeto, entrada=prompt,
                                     sucesso=False, erro=str(e)[:2000])
            raise
```

`GEMINI_MODEL` vem do `.env` (usar o modelo Flash vigente para custo baixo; trocar sem deploy pelo `PromptTemplate`).

### 8.3 Prompt de refinamento (seed `relatorio.refinar_secao`)

**System instruction:**
```
Você é redator técnico da KS TEC Soluções de Tecnologia, empresa que presta serviços de TI a
órgãos públicos. Reescreva o texto em português formal administrativo, claro e objetivo,
adequado a relatório de execução contratual apresentado ao fiscal do contrato
(Lei nº 14.133/2021).

Regras obrigatórias:
1. NÃO invente fatos, números, datas, nomes, sistemas ou resultados que não estejam no texto.
2. Preserve todos os números, datas, protocolos e nomes próprios exatamente como estão.
3. Pode reorganizar em parágrafos, corrigir gramática, eliminar repetições e explicitar o
   benefício da atividade para a administração SOMENTE quando estiver implícito no texto.
4. Use voz ativa e terceira pessoa ("A KS TEC realizou..."). Sem adjetivos promocionais.
5. Se houver informação insuficiente, mantenha o texto curto; não complete lacunas.
6. Responda apenas com o texto final, sem comentários.
```
**Template do usuário:**
```
Contrato: {contrato} — Objeto: {objeto}
Período: {periodo}
Seção: {titulo_secao}
Texto original:
"""
{texto}
"""
```
Variante `relatorio.complementar`: gera introdução e considerações finais a partir da lista de tarefas (mesmas regras). Variante `orcamento.descricao`: melhora descrição comercial de itens.

**Proteções:**
- Validador pós-IA: extrai números/datas do original e do refinado; se algum número sumir ou aparecer número novo, marca a seção com aviso "Verifique: valores alterados".
- Não enviar dados pessoais desnecessários (CPF, telefone de cidadão) ao Gemini: função `anonimizar()` antes do envio (LGPD).
- Limite mensal de custo de IA (`Parametro ia.limite_mensal_brl`) com alerta a 80%.

---

## 9. Planilha de custos, financeiro e relatórios

### 9.1 Planilha de custos por contrato

Estrutura (aba única na tela, exportável para XLSX com fórmulas vivas):

| Grupo | Exemplos de itens |
|---|---|
| A. Mão de obra | Horas de desenvolvimento, suporte, deslocamento técnico (valor-hora × horas/mês) |
| B. Infraestrutura | VPS Hetzner (rateio), storage, backup, domínio, SSL, e-mail |
| C. Licenças e APIs | Gemini, mapas, SMS/WhatsApp, bibliotecas pagas |
| D. Insumos | Material gráfico, mídia |
| E. Custos indiretos | Contador, ferramentas internas, telefonia (rateio) |
| F. BDI | AC, seguro/garantia, risco, despesas financeiras, lucro |
| G. Tributos sobre faturamento | DAS (Simples) ou ISS + PIS + COFINS + IRPJ + CSLL |

Fórmula do BDI (modelo usual do TCU, Acórdão 2622/2013):

```
BDI = [ (1 + AC + S + R + G) × (1 + DF) × (1 + L) / (1 − I) ] − 1
AC administração central · S seguro · R risco · G garantia · DF despesas financeiras
L lucro · I tributos sobre o faturamento
Preço mensal = Custo direto mensal × (1 + BDI)
```

Funções: comparar **planilha × realizado** (lançamentos do centro de custo do contrato) mês a mês; simular reajuste; duplicar planilha para nova proposta; exportar no formato de proposta para licitação.

### 9.2 Financeiro

- Contas a receber nascem da NF autorizada (valor líquido, vencimento = data emissão + prazo do contrato). Contratos públicos registram **empenho, liquidação e ordem bancária**.
- Contas a pagar com recorrências (VPS, domínios, contador, DAS).
- Conciliação: import OFX/CSV, match automático e manual.
- Transferências entre contas não afetam DRE.
- Regime de **competência** para DRE e de **caixa** para fluxo de caixa (ambos disponíveis).

### 9.3 Relatórios financeiros (todos com filtro período/contrato/cliente, export PDF e XLSX)

1. **DRE gerencial** (empresa e por contrato): receita bruta → deduções (tributos) → receita líquida → custos diretos → margem de contribuição → despesas operacionais → resultado.
2. **Fluxo de caixa** realizado + projetado 90 dias.
3. **Rentabilidade por contrato**: receita, custo apropriado, margem %, horas consumidas, receita/hora.
4. **Contas a receber por órgão** com aging (0–30, 31–60, 61–90, > 90 dias) e prazo médio de recebimento.
5. **Faturamento × planilha de custos** (desvio).
6. **Impostos do período**: ISS próprio, ISS retido por tomadores, retenções federais sofridas, DAS.
7. **Livro de notas emitidas** (substitui o livro fiscal do portal para uso interno).
8. **Execução contratual**: valor global, aditivos, faturado, saldo, % executado, vigência.

---

## 10. Certidões e habilitação

- Cadastro com PDF, emissão, validade e situação. Upload de PDF tenta extrair **data de validade e código de controle** por regex (texto do PDF) para pré-preencher.
- Painel "Situação de habilitação": semáforo por certidão + indicador geral **APTA / ATENÇÃO / INAPTA**.
- Alertas: 30, 15, 7 dias e no vencimento (app + e-mail). Botão "Emitir nova" abre `url_emissao` do tipo.
- **Kit de habilitação**: selecionar certidões + documentos extras (contrato social, CNPJ, atestados de capacidade técnica) → ZIP + PDF índice com sumário e validades. Bloqueia certidão vencida no kit (com aviso).
- Vínculo com contratos: se uma certidão exigida pelo contrato estiver vencida, o checklist da emissão de NF alerta (pagamentos públicos costumam exigir regularidade fiscal).
- Automação de emissão: **fase futura** e só onde não houver captcha/termos que proíbam; a maioria dos portais exige interação humana.

---

## 11. Catálogo, orçamentos e vendas avulsas

### 11.1 Catálogo
- Serviços de TI com códigos fiscais completos (LC 116 + cTribNac + NBS + alíquota).
- Itens gráficos com **configurador**: escolhe formato, papel, cores, acabamento → preço = faixa de quantidade + acréscimos das variações.
- Importação das tabelas de referência dos anexos E&L (comando `manage.py importar_tabelas_fiscais <xlsx>`), com busca por texto ("hospedagem", "suporte") sugerindo NBS correlatas.

### 11.2 Orçamento
1. Stepper: Cliente (ou avulso) → Itens (configurador com preço ao vivo) → Condições → Revisão/PDF.
2. Envio por e-mail/WhatsApp com **link público** (`/o/<token>`) mostrando o orçamento com a marca KS TEC e botões **Aprovar / Solicitar ajuste**. Registra visualização, IP e nome de quem aprovou.
3. Orçamento aprovado → **Converter em venda** (um clique).
4. Expiração automática na data de validade; lembrete de follow-up 3 dias após envio sem resposta.

### 11.3 Venda avulsa → NF
- Venda gera rascunho de NFS-e com os itens de **serviço** (a NFS-e tem um serviço por documento: agrupar itens do mesmo código de serviço na discriminação, ou emitir uma nota por código) e o recebível (à vista ou parcelado).
- ⚠️ **Atenção fiscal:** impressos **personalizados sob encomenda** tendem a ser serviço (ISS, item 13.05); **venda de mercadoria** (produto pronto, revenda) é fato gerador de ICMS e exige **NF-e estadual (SEFAZ-BA)**, não NFS-e — e CNAE compatível. O sistema deve impedir emitir NFS-e para item com `natureza = PRODUTO` e sinalizar "requer NF-e". Integração NF-e fica como fase futura; validar o enquadramento com o contador.

---

## 12. Segurança, LGPD e auditoria

- Login por e-mail + senha forte + **MFA TOTP** obrigatório para papéis Administrador, Financeiro e Fiscal (`django-otp`).
- Permissões por papel + objeto (técnico só vê contratos em que está alocado).
- `django-axes` (bloqueio de força bruta), sessões de 8h, HTTPS obrigatório, HSTS, CSP restritiva.
- Segredos criptografados (Fernet); o PFX nunca é gravado descriptografado em disco fora do contexto temporário (6.3).
- Auditoria: `simple_history` em todos os modelos + `LogIntegracao` + log de acesso a documentos fiscais.
- LGPD: registro de finalidade dos dados de contatos, anonimização antes da IA, exportação/remoção de dados de pessoa física sob solicitação, retenção fiscal de 5 anos para documentos fiscais (não apagáveis nesse prazo).
- Backups: `pg_dump` diário criptografado + mídia → storage externo (Nextcloud/S3), retenção 30 diários + 12 mensais; **teste de restauração mensal** (tarefa automática no painel).

---

## 13. Roteiro fase a fase

Estimativas para 1 desenvolvedor full-stack em ritmo regular. Cada fase termina com deploy em homologação e demonstração.

| Fase | Nome | Duração | Depende de |
|---|---|---|---|
| 0 | Fundação e infraestrutura | 1 semana | — |
| 1 | Núcleo, design system e cadastros | 2 semanas | 0 |
| 2 | Contratos e certidões | 2 semanas | 1 |
| 3 | Catálogo, tabelas fiscais e orçamentos | 2 semanas | 1 |
| 4 | Fiscal — NFS-e em duplo canal (Nacional + E&L) | 4 semanas | 2, 3 |
| 5 | Financeiro | 2–3 semanas | 4 |
| 6 | Operação, relatórios de atividades e IA | 2 semanas | 2 |
| 7 | Monitoramento e SLA | 2 semanas | 2 |
| 8 | Custos, relatórios gerenciais e pacote de medição | 2 semanas | 5, 6, 7 |
| 9 | Endurecimento e lançamento | 2 semanas | todas |

### Fase 0 — Fundação e infraestrutura
**Objetivo:** projeto rodando localmente e em homologação com pipeline.
- [ ] Repositório, `pyproject.toml` (ruff, black, mypy opcional), pre-commit.
- [ ] `config/settings/{base,dev,prod}.py` com `django-environ`; timezone `America/Bahia`, `LANGUAGE_CODE = "pt-br"`, `USE_THOUSAND_SEPARATOR`.
- [ ] Docker Compose: `web`, `worker`, `beat`, `db`, `redis`, `caddy`. Healthchecks.
- [ ] Celery configurado, `django-celery-beat`, Sentry, logs JSON.
- [ ] CI (GitHub Actions): lint + testes + build da imagem; deploy por tag em VPS Hetzner.
- [ ] Backups automáticos e script de restauração.
**Aceite:** `docker compose up` sobe tudo; `/health` responde; CI verde; backup e restauração testados.

### Fase 1 — Núcleo, design system e cadastros
**Objetivo:** esqueleto navegável com a cara da KS TEC.
- [ ] `core`: ModeloBase, Empresa, Usuario (login por e-mail), grupos/papéis, Endereco, Anexo, Parametro, Segredo, Notificacao, LogIntegracao, auditoria.
- [ ] MFA TOTP, axes, política de senha.
- [ ] `tokens.css`, layout (sidebar navy, topbar), todos os componentes da seção 4.4 em uma página `/_componentes` (catálogo vivo).
- [ ] Logo: baixar `ks-tec-logo.png`; produzir versão branca e símbolo isolado em SVG para sidebar recolhida e favicon.
- [ ] Busca global Ctrl+K (pessoas, por enquanto), toasts, atalhos.
- [ ] `cadastros`: Pessoa + Contato com consulta de CNPJ (BrasilAPI) e CEP (ViaCEP), máscara e validação de dígitos.
- [ ] Seed da Empresa KS TEC (CNPJ 62.501.281/0001-13, Valença/BA 2932903).
**Aceite:** criar cliente digitando só o CNPJ; layout responsivo testado em 375px, 768px e 1440px; Lighthouse acessibilidade ≥ 90.

### Fase 2 — Contratos e certidões
- [ ] Contrato, Aditivo, ItemContrato, Empenho, Competencia (geração automática das competências da vigência).
- [ ] Hub do contrato com abas (as abas de fases futuras aparecem com `empty_state`).
- [ ] Indicadores: saldo, % executado, dias para o fim; alertas de vigência (90/60/30) e saldo < 20%.
- [ ] Certidões: TipoCertidao (seed), Certidao com upload e extração de validade, semáforo, alertas, Kit de habilitação (ZIP + índice PDF).
- [ ] Agenda de obrigações (primeira versão: vigências + certidões).
**Aceite:** cadastrar contrato real com aditivo e ver saldo correto; certidão vencendo em 10 dias aparece no painel e gera e-mail; kit ZIP gerado.

### Fase 3 — Catálogo, tabelas fiscais e orçamentos
- [ ] Comando `importar_tabelas_fiscais` lendo os XLSX `ANEXO_B-NBS2-LISTA_SERVICO_NACIONAL` (abas `LISTA.SERV.NAC.` e `LISTA.NBS_v2.0`) e `AnexoVIII-CorrelacaoItemNBS…` (aba `tabela geral`, com *forward-fill* da coluna Item LC 116, que vem mesclada).
- [ ] ItemCatalogo com sugestão de NBS a partir do item LC 116; cadastro inicial dos serviços KS TEC (desenvolvimento, SaaS/hospedagem, suporte, sites, consultoria, licenciamento, social media, audiovisual, gráfica).
- [ ] Configurador gráfico (variações + faixas).
- [ ] Orçamentos: stepper, PDF com identidade visual, link público de aprovação, expiração, follow-up, conversão em venda.
**Aceite:** orçamento de 500 cartões com variações calcula preço correto; cliente aprova pelo link no celular; venda criada.

### Fase 4 — Fiscal: NFS-e em duplo canal
**Pré-requisitos externos (bloqueantes):** certificado A1 da KS TEC; URL do webservice E&L de Valença; confirmação com a Prefeitura/Sefin da habilitação para emissão via API; XSDs oficiais vigentes baixados; definição com o contador do regime (Simples ou não), alíquota e perfis de retenção.
- [ ] CertificadoDigital (upload PFX, validação, alerta de vencimento), ConfiguracaoFiscal, PerfilFiscal, SequenciaNumeracao.
- [ ] `calculo.py` com testes cobrindo: ISS normal, retido, Simples, MEI, descontos, retenções federais, arredondamento.
- [ ] `dps_builder.py` + validação XSD + `assinatura.py` (testes com certificado de teste autoassinado; verificação com `xmlsec1`).
- [ ] `ProvedorNacional`: emitir, consultar, cancelar, DANFSe (com fallback de PDF próprio).
- [ ] `abrasf_builder.py` + `ProvedorElAbrasf`: emitir (`GerarNfse`), consultar (`ConsultarNfseRps`), cancelar (`CancelarNfse`), validação contra `nfse_v2-04.xsd`, assinatura SHA1 verificada com `xmlsec1`.
- [ ] Duplo canal (6.14): `TentativaTransmissao`, `pode_tentar_canal()`, trava de duplicidade, liberação manual auditada, fallback opcional, seletor de canal no assistente, verificação de compartilhamento no ADN, painel por canal.
- [ ] Orquestração Celery com idempotência (6.7), log de integração, tradução de erros.
- [ ] Assistente de emissão em 3 passos com pré-visualização e checklist; emissão em lote da competência (rascunhos).
- [ ] Envio automático da NF (PDF + XML) ao `email_nf` do tomador.
- [ ] GuiaISS (fluxo assistido 6.12).
- [ ] Importador de histórico E&L (6.11).
**Testes:** unitários com `respx` simulando, nos dois canais, sucesso, rejeição com erros, timeout seguido de consulta bem-sucedida (não pode duplicar nota) e tentativa de troca de canal após timeout (deve ser bloqueada).
**Aceite:** Nacional emite, consulta e cancela em **produção restrita**; XMLs dos dois canais validados contra XSD; importador de histórico E&L funcionando; protocolo 6.14.6 executado em produção com uma nota por canal e resultados registrados no diário de testes; `canal_padrao` definido com base nele.

### Fase 5 — Financeiro
- [ ] ContaBancaria, CategoriaFinanceira (seed do plano), CentroCusto automático por contrato, Lancamento, Recorrencia.
- [ ] Recebível automático a partir da NF; baixa com empenho/liquidação/OB.
- [ ] Contas a pagar recorrentes; vencidos destacados; agenda integrada.
- [ ] Importação OFX/CSV e conciliação.
- [ ] Relatórios: fluxo de caixa, DRE gerencial, aging de recebíveis.
- [ ] (Opcional) DAPS via `ElAceitesClient` para serviços tomados com retenção.
**Aceite:** ciclo completo NF → recebível → baixa por extrato conciliado; DRE do mês bate com os lançamentos.

### Fase 6 — Operação, relatórios de atividades e IA
- [ ] Tarefas (kanban por contrato + lista), apontamento de horas, evidências.
- [ ] `ia`: ClienteGemini, PromptTemplate (seeds 8.3), ChamadaIA, limite de custo, `anonimizar()`, validador de números.
- [ ] RelatorioAtividades: geração a partir das tarefas, edição por seção, refinar com IA com `diff_view`, aprovação, PDF + DOCX com hash.
**Aceite:** relatório de um mês real gerado em < 5 min de trabalho humano; IA nunca altera números sem aviso (teste automatizado com casos adversariais).

### Fase 7 — Monitoramento e SLA
- [ ] Sistema, Verificacao, AgregadoDiario, Incidente, JanelaManutencao.
- [ ] Tasks de checagem, re-checagem, SSL, agregação e limpeza.
- [ ] Tela de monitoramento (grade de sistemas com `uptime_bar`, detalhe com gráfico de latência).
- [ ] Notificações de incidente; RelatorioSLA em PDF.
- [ ] Pacote `ks_health` e contrato `/api/health` (7.3); instalar em um sistema piloto (ex.: PRISMA ou SIGAL).
- [ ] (Opcional) página pública de status por contrato.
**Aceite:** derrubar um sistema de teste gera incidente em ≤ 2 intervalos e notificação; relatório mensal mostra disponibilidade conforme fórmula 7.2 (teste com dados sintéticos de resultado conhecido).

### Fase 8 — Custos, relatórios gerenciais e pacote de medição
- [ ] PlanilhaCusto com BDI, rateio, export XLSX com fórmulas, comparação planejado × realizado.
- [ ] Rentabilidade por contrato, relatório de impostos, livro de notas, execução contratual.
- [ ] Painel completo (seção 4.6).
- [ ] **Pacote mensal de medição**: NF + relatório de atividades + SLA + certidões vigentes → ZIP com índice, por competência.
**Aceite:** gerar o pacote de um contrato com um clique; XLSX abre no Excel/LibreOffice com fórmulas funcionando.

### Fase 9 — Endurecimento, legado E&L e lançamento
- [ ] Revisar o diário de testes fiscais e desativar a emissão no canal que não se mostrou válido (mantendo-o para consulta/cancelamento).
- [ ] Testes de carga leves (monitoramento com 50 sistemas, 1 checagem/min).
- [ ] Revisão de segurança (OWASP Top 10), CSP, permissões por objeto.
- [ ] Tema escuro, ajustes de acessibilidade, manual do usuário (POP interno no mesmo estilo dos POPs E&L).
- [ ] Migração de dados reais, treinamento, go-live.
**Aceite:** checklist de segurança verde; restauração de backup cronometrada; 30 dias em produção sem incidente crítico.

---

## 14. Anexos

### 14.1 Variáveis de ambiente (`.env.example`)

```bash
DJANGO_SECRET_KEY=
DJANGO_ALLOWED_HOSTS=central.kstec.online
DATABASE_URL=postgres://kscentral:***@db:5432/kscentral
REDIS_URL=redis://redis:6379/0
FIELD_ENCRYPTION_KEY=          # Fernet.generate_key()
SENTRY_DSN=
EMAIL_URL=smtp+tls://kaua@kstec.online:***@smtp.servidor:587
DEFAULT_FROM_EMAIL="KS TEC <nao-responda@kstec.online>"
GEMINI_API_KEY=
GEMINI_MODEL=                  # modelo Flash vigente do Gemini
STORAGE_BACKEND=s3             # ou webdav (Nextcloud)
AWS_S3_ENDPOINT_URL=
AWS_STORAGE_BUCKET_NAME=kscentral
NFSE_AMBIENTE=PRODUCAO_RESTRITA
TZ=America/Bahia
```

### 14.2 Comandos de gestão

| Comando | Função |
|---|---|
| `seed_inicial` | Empresa KS TEC, papéis, categorias financeiras, tipos de certidão, prompts de IA |
| `importar_tabelas_fiscais <arquivos.xlsx>` | LC 116, cTribNac, NBS, correlação IBS/CBS |
| `importar_nfse_el <xml|zip>` | Histórico do portal E&L |
| `gerar_competencias` | Cria competências faltantes dos contratos vigentes |
| `testar_sefin` | Faz chamada autenticada (mTLS) em produção restrita e reporta |
| `recalcular_sla <ano-mes>` | Reprocessa agregados e relatórios |

### 14.3 Tarefas agendadas (Celery beat)

| Tarefa | Frequência |
|---|---|
| `sla.despachar_verificacoes` | 1 min |
| `sla.agregar_dia` / `sla.limpar_brutos` | diária 00:15 / 03:00 |
| `sla.verificar_ssl_todos` | diária 06:00 |
| `certidoes.alertar_vencimentos` | diária 07:00 |
| `fiscal.alertar_certificado` | diária 07:05 |
| `fiscal.criar_guias_iss` | dia 1, 08:00 |
| `contratos.alertar_vigencia_saldo` | diária 07:10 |
| `financeiro.marcar_atrasados` / `gerar_recorrencias` | diária 00:30 |
| `comercial.expirar_orcamentos` / `followup` | diária 09:00 |
| `relatorios.lembrete_competencia` | dia 1, 09:00 |
| `ia.verificar_limite_custo` | diária |
| `core.lembrete_teste_restauracao` | mensal |

### 14.4 Mapas de status → cor do badge

| Entidade | Verde | Azul | Âmbar | Vermelho | Cinza |
|---|---|---|---|---|---|
| NotaFiscal | AUTORIZADA | NA_FILA, TRANSMITINDO | VALIDADA, CANCELAMENTO_SOLICITADO, ERRO_COMUNICACAO | REJEITADA | RASCUNHO, CANCELADA, SUBSTITUIDA |
| Lancamento | PAGO | PREVISTO | PENDENTE | ATRASADO | CANCELADO |
| Certidao | VALIDA | — | VENCENDO | VENCIDA | — |
| Sistema | OPERACIONAL | MANUTENCAO | DEGRADADO | FORA | DESCONHECIDO |
| Orcamento | APROVADO, CONVERTIDO | ENVIADO, VISUALIZADO | — | RECUSADO | RASCUNHO, EXPIRADO |

### 14.5 Pendências a confirmar fora do código

| # | Item | Com quem | Bloqueia |
|---|---|---|---|
| 1 | Habilitação da KS TEC para emitir NFS-e via API no Emissor Nacional | Sefaz Valença / portal nfse.gov.br | Fase 4 |
| 2 | Regime tributário, alíquota de ISS, perfis de retenção por tipo de órgão | Contador | Fase 4 |
| 3 | NBS e cTribNac definitivos de cada serviço do catálogo | Contador | Fase 3/4 |
| 4 | URL do webservice E&L de Valença, CNPJ da Prefeitura, se o E&L aceita emissão de competências 2026 com repasse ao ADN | Prefeitura / E&L | Fase 4 (canal E&L) / DAPS |
| 5 | Exigências de IBS/CBS nos documentos em 2026/2027 (grupo `IBSCBS` da DPS) | Contador + Notas Técnicas nacionais | Fase 4 |
| 6 | Enquadramento de vendas gráficas (ISS 13.05 × ICMS/NF-e) e CNAEs | Contador | Fase 3 (vendas de produto) |
| 7 | Certificado A1 válido (e-CNPJ ICP-Brasil) | Autoridade certificadora | Fase 4 |

### 14.6 Glossário

**ADN** Ambiente de Dados Nacional da NFS-e · **BDI** Benefícios e Despesas Indiretas · **cClassTrib** classificação tributária IBS/CBS · **cTribNac** código de tributação nacional do ISSQN · **DAM** Documento de Arrecadação Municipal · **DANFSe** documento auxiliar (PDF) da NFS-e · **DAPS** Documento Auxiliar de Prestação de Serviços (E&L, serviço tomado) · **DPS** Declaração de Prestação de Serviço (padrão nacional) · **E&L** fornecedor do sistema municipal de Valença · **NBS** Nomenclatura Brasileira de Serviços · **OB** Ordem Bancária · **RPS** Recibo Provisório de Serviços (padrão ABRASF) · **Sefin Nacional** API de emissão do padrão nacional · **SLA** acordo de nível de serviço.

---
*KS TEC — Tecnologia, gestão e inovação para transformar processos.*
