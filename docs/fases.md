# Andamento por fase

Registro do que foi entregue em cada fase do roteiro (plano, seção 13) e do que depende de ação externa.

> Revisão local: as marcações abaixo descrevem implementação anterior, sem comprovar
> todos os aceites externos. Consulte `testes_locais.md` para pendências e execução no Windows.

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
- Consulta CNPJ ampliada: situação cadastral, abertura, CNAE/descrição, natureza jurídica e porte persistidos; opção pelo Simples mantém desconhecido distinto de não optante. Botão de consulta também disponível nos dados da empresa, com tratamento de indisponibilidade e respostas inválidas.
- `seed_inicial` cria a empresa KS TEC (CNPJ 62.501.281/0001-13, Valença/BA 2932903), papéis e parâmetros.
- Logo oficial PNG aplicada em orçamentos e PDFs; versões SVG com imagem incorporada para logo branca, símbolo isolado e favicon — ver `static/img/README.md`.

## Fase 2 — Contratos e certidões ✅

- `contratos`: Contrato, Aditivo, ItemContrato, Empenho, Competencia (geração automática pela vigência, inclusive aditivos de prazo; comando `gerar_competencias`).
- Hub do contrato com abas `Resumo · Notas · Financeiro · Tarefas · Relatórios · Custos · Sistemas/SLA · Documentos · Histórico` (abas de módulos futuros exibem `empty_state`; cada app registra sua aba em `apps/contratos/abas.py`).
- Indicadores: valor atualizado, faturado, saldo, % executado, dias para o fim; alertas de vigência (90/60/30) e saldo < 20% (task diária + notificação por e-mail).
- Técnicos (papel Operação) só veem contratos em que estão alocados.
- `certidoes`: TipoCertidao (seed com 10 tipos), Certidao com upload de PDF e extração de validade/código/situação, semáforo APTA/ATENÇÃO/INAPTA, alertas 30/15/7/0 dias, Kit de habilitação (ZIP + índice PDF; vencidas ficam fora com aviso).
- Agenda de obrigações (`/agenda/`) e "Precisa da sua atenção" no painel, alimentados por provedores registrados por cada app (`apps/core/agenda.py`).

## Fase 3 — Catálogo, tabelas fiscais e orçamentos ✅

- Tabelas de referência: `CodigoServicoLC116`, `CodigoTributacaoNacional`, `CodigoNBS`, `CorrelacaoNBS` (IBS/CBS). Comando `importar_tabelas_fiscais <xlsx...>` reconhece as abas `LISTA.SERV.NAC.`, `LISTA.NBS_v2.0` e `tabela geral` por palavras-chave, com *forward-fill* do item LC 116 mesclado. O seed traz um conjunto mínimo (descrições de NBS marcadas como provisórias).
- `ItemCatalogo` com códigos fiscais, sugestão automática de NBS/cTribNac ao escolher o item da LC 116, validação "apto para NFS-e" e bloqueio de produto (requer NF-e estadual).
- Configurador gráfico: faixas de preço por quantidade + variações (por unidade, percentual, fixo rateado). Ex.: 500 cartões couché 300g + verniz + faca especial = R$ 0,82/un, R$ 410,00.
- Orçamentos: numeração `ORC-AAAA-NNNN`, etapas Cliente → Itens (preço ao vivo via HTMX) → Condições → Revisão/envio, PDF com identidade visual, envio por e-mail/WhatsApp, link público `/o/<token>/` com Aprovar (nome + IP + data) e Solicitar ajuste, expiração automática, follow-up após 3 dias, conversão em venda com um clique.

## Fase 4 — Fiscal (iniciada)

- Perfis de retenção configuráveis, rascunhos de NFS-e e telas integradas à navegação.
- Cálculos `Decimal` com arredondamento HALF_UP, descontos, deduções, ISS retido,
  Simples com alíquota explícita, MEI e retenções federais.
- Persistência em services, histórico auditável, bloqueio de mercadoria e vínculos entre empresas.
- Dados do tomador, serviço e perfil copiados em cada versão do rascunho; histórico
  preserva as versões anteriores quando os cadastros mudam. Edição com bloqueio transacional.
- Testes unitários e fluxos HTTP. Emissão real por comando implementada e validada
  pelo canal municipal; tela de notas autorizadas, configuração protegida,
  recebível automático, DANFSe PDF e envio avulso/contratual implementados.
  Veja [pdf_e_entrega_nfse.md](pdf_e_entrega_nfse.md).

## Fase 5 — Financeiro (iniciada)

- Contas bancárias, 14 categorias iniciais, centros administrativos e centro automático por contrato.
- Contas a pagar/receber com competência, vencimento, baixa integral, juros, multa,
  desconto, ordem bancária e liquidação; cancelamento exige motivo. Baixas duplicadas
  e edição de lançamentos pagos/cancelados são bloqueadas. Histórico por operação.
- Recorrências mensais/anuais com previsões para 12 meses; dias 29–31 ajustados ao
  último dia do mês. Geração transacional com chave única por competência, sem duplicação.
- DRE gerencial por competência/contrato, resultado não operacional com sinal,
  investimentos separados, caixa realizado/projetado, saldos e recebíveis por faixas de atraso.
- Agenda, alertas, indicadores e aba Financeiro do contrato. Dados financeiros
  restritos aos papéis Administrador, Financeiro, Fiscal e Leitura; escrita ao Financeiro/Administrador.
- Recebível automático e conciliação manual OFX/CSV implementados e testados.
- Pendentes: vínculo a venda/empenho, transferências entre contas, categorias
  em árvore e DAPS opcional.
  O aceite completo NF → recebível → extrato conciliado ainda não foi alcançado.

## Fase 6 — Operação, relatórios e IA (iniciada)

- Tarefas com tipo, prioridade, responsável, solicitante, prazo, estimativa e resumo da entrega.
- Lista, quadro com cinco situações, filtro por contrato via hub e aba Tarefas do contrato.
- Transições validadas, conclusão exige resumo quando incluída em relatório, reabertura auditada.
- Horas decimais, limite de 24 h/dia por usuário entre tarefas e bloqueio de datas
  futuras/anteriores à abertura. Tarefas encerradas devem ser reabertas para novos apontamentos.
- Anexos como evidências; leitura/download dos técnicos restritos à alocação do
  contrato e às próprias tarefas sem contrato. Escrita para Operação/Administrador;
  papel Leitura permanece sem escrita.
- Relatório mensal com revisão, aprovação, PDF e versões preservadas implementado,
  com sugestão baseada nas tarefas e horas da competência.
- Pendentes: evidências com seleção/legenda, vínculo a sistemas/SLA, DOCX e
  integração Gemini com controles de custo.
  O aceite de relatório de um mês real ainda não foi alcançado.

## Ambiente local Windows

- Emissão real de R$ 1,00 em 09/10/2026: municipal E&L autorizou a NFS-e
  2600000000012, também recuperada pela consulta nacional. Emissão nacional
  direta rejeitada E0039 (município sem emissor público habilitado). XML e
  assinatura verificados; DANFSe local disponível em PDF. A API anterior foi
  descontinuada; veja [pdf_e_entrega_nfse.md](pdf_e_entrega_nfse.md).
  Veja [emissao_producao_20261009.md](emissao_producao_20261009.md).

- Novo canal municipal DPS identificado no portal, com autenticação por token,
  schemas e cliente de homologação preparados. Inscrição municipal e tomador
  cadastrados; tabelas nacionais atualizadas e importação de agrupadores corrigida.
  Token configurado localmente; uma nota real autorizada pelo novo fluxo por comando.
  Veja [integracao_el_dps.md](integracao_el_dps.md).

- Diagnóstico com A1 e envio nacional de R$ 1,00 em homologação: rejeitado E0037;
  convênio de Valença/BA não ativo nesse ambiente. Serviço municipal acessível,
  porém consulta no serviço legado sem resultado de negócio. O novo canal E&L
  em produção emitiu a nota documentada acima.
  Evidências e comandos em [testes_emissao_nfse.md](testes_emissao_nfse.md).

- Perfil sem dependência de Docker/Redis/PostgreSQL para testes de uso.
- Scripts de preparação e início, usuário local com senha aleatória e banco fora do Git.
- PDFs com executável oficial portátil para isolar bibliotecas nativas do Windows.
- Veja `testes_locais.md` para roteiro, diferenças de produção e pendências por fase.

## Custos e pacote contratual — avanço das fases 8 e 4

- Composição mensal por contrato com quantidade, valor, rateio, periodicidade e
  fonte; BDI informado, versões aprovadas e exportação XLSX/PDF.
- Pacote fiscal com nota PDF/XML, certidões vigentes, relatório e custos aprovados.
  Revisão antes de envio, revalidação dos documentos e histórico sem reenvio automático.
- Ainda pendentes: orçamento de custos completo, importações e análises avançadas
  previstas no plano, SLA e aceite com documentos de um contrato real.
