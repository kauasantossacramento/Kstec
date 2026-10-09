# KS CENTRAL — passagem de desenvolvimento para o próximo agente

Atualizado em **09/10/2026**, após integração fiscal, financeiro, operação,
DANFSe PDF e entrega documental. Este documento descreve o estado observado;
não equivale à conclusão integral do plano ou à homologação de todos os cenários.

## 1. Repositório, ambiente e origem do trabalho

- Repositório: https://github.com/kauasantossacramento/Kstec.
- Branch de entrega: **`desenvolvimento-local`**. Base anterior: `9f4807c`
  (Fase 3). A branch remota original é `ccr-86406a8c-5a2ak0`.
  A entrega não implica merge na branch padrão nem deploy em produção.
- Workspace Windows: `C:\Users\KS TEC\sistema_kstec_`, PowerShell.
  A pasta anterior `sistema_kstec` foi preservada.
- Plano de referência: [plano_desenvolvimento.md](plano_desenvolvimento.md),
  correspondente ao anexo `KS_CENTRAL_plano_desenvolvimento.md` de Downloads.
  As solicitações diretas do usuário definiram as prioridades desta implementação.
- Local: Python 3.13.14, Django 5.2.18, SQLite, cache em memória,
  Celery síncrono, e-mail simulado e MFA opcional. CI usa Python 3.12/PostgreSQL.
- Aplicação: http://localhost:8000/. Servidor de desenvolvimento com `--noreload`.
  Alterações Python precisam de reinício. O processo foi iniciado oculto no Windows.
  Identifique pelo comando/processo antes de interromper; não encerre servidores de outros projetos.

## 2. O que já existia e foi preservado

As fases 0–3 já tinham infraestrutura Django/Docker/CI, autenticação, MFA,
papéis, auditoria, cadastros, contratos, aditivos, competências, certidões,
kits, agenda, catálogo fiscal, configuração de preços e orçamentos públicos.
O trabalho manteve essa base e integrou os novos módulos à navegação e ao hub do contrato.
Marcações antigas de conclusão em `fases.md` não comprovam aceites externos.

## 3. Identidade visual e consulta cadastral

- Logo oficial obtida de `https://kstec.online/assets/ks-tec-logo.png`.
  PNG e variantes SVG aplicados no sistema, favicon e PDFs com a identidade KS TEC.
- Consulta CNPJ ampliada para razão social, fantasia, endereço, contato,
  situação, abertura, CNAE, natureza jurídica, porte e opção pelo Simples quando disponível.
  Informações devem ser conferidas antes do salvamento; desconhecido não vira falso automaticamente.
- O provedor implementado é **BrasilAPI**, em `apps/core/services/brasilapi.py`.
  Não confundir com a APIBrasil comercial citada pelo usuário: não há integração
  paga/credenciais desse fornecedor implementadas. Não se extraem CPF ou inscrições
  estadual/municipal por essa consulta de CNPJ.

## 4. Tabelas fiscais e serviço confirmado

No banco local foram importados **335 códigos nacionais vigentes, 918 NBS,
896 correlações, 201 itens LC 116 e 204 referências municipais** de Valença/BA.

- Importador XLSX nacional/NBS/correlações com reconhecimento de abas e agrupadores.
- Importador municipal PDF/CSV com validação transacional, fonte e versão.
- Fonte municipal: Anexo I da LC municipal 010/2021, documentada em `fiscal_integrado.md`.
- Serviço TI-DEV: LC 116 **01.01**, nacional **010101**, municipal **101**,
  NBS **115022000**. O código 101 foi confirmado na nota real autorizada.
- As demais referências municipais não têm código de integração automaticamente
  confirmado. Item da lei e `cIntContrib` do provedor são campos diferentes.
  A interface só oferece códigos municipais confirmados para transmissão.
- Correlações NBS são referências; não devem ser transformadas em regra absoluta
  de negócio sem sustentação na documentação oficial.

As tabelas completas residem no banco local, que não é versionado. Um clone novo
precisa de seed/importação dos arquivos oficiais; o seed contém somente um conjunto mínimo.

## 5. Fiscal: implementação e resultado real

Implementados em `apps/fiscal/`: perfis, rascunhos, cálculos `Decimal`/HALF_UP,
snapshots, configuração por empresa, A1/senha/token cifrados, série/numeração,
tentativas persistidas antes do POST, validação XML/XSD/assinatura, consulta,
importação de NFS-e autorizada, histórico, recebível e telas de revisão/transmissão.

O adaptador de emissão atual atende **ME/EPP optante do Simples sem retenções,
descontos ou deduções**. Outros cenários podem ser calculados no rascunho,
mas são bloqueados na transmissão até implementar seus campos e testes.
Estado indeterminado/timeout não autoriza segundo POST ou troca automática de canal.

### Configuração aplicada na máquina

- Prestador: KS TEC SOLUÇÕES DE TECNOLOGIA LTDA, CNPJ 62.501.281/0001-13,
  IM 16845, Valença/BA, IBGE 2932903.
- Canal municipal E&L, produção, série DPS 1. A1 e token já cadastrados cifrados.
- ISS **2%** e total aproximado do Simples **6%**, fornecidos pelo usuário,
  fonte registrada e vigência **01–31/10/2026**. Não são apuração PGDAS-D/IBPT.
  Não reutilizar em outras competências sem revisar e atualizar a configuração.
- Conta bancária efetiva não cadastrada; a conta DEMO não foi usada para a nota real.

### Nota já emitida: não duplicar

Foi emitida **uma NFS-e real**, nº **2600000000012**, de **R$ 1,00**,
por desenvolvimento de sistema, para o cliente Kauã cadastrado localmente.

- Municipal E&L: POST HTTP 201; consulta posterior HTTP 200, XML `cStat=100`.
- Nacional direto: POST HTTP 400/**E0039**; município não parametrizado para
  emissão pública nacional. Não gerou outra nota. Esse canal permanece desabilitado.
- Consulta nacional autenticada da nota municipal: HTTP 200, mesmo XML.
  Compartilhamento/consulta nacional não significa emissão direta nacional habilitada.
- DPS já utilizada: `DPS293290326250128100011300001020261009000001`.
- Nota no banco: `01a11ed5-8cb3-723f-8607-08b1a7df69a4`.
  Recebível: `01a11ed5-8ce2-7106-868c-ce90ae92679c`, pendente,
  vencimento **08/11/2026**, sem evidência de pagamento real.
- XML e assinatura verificados; retorno municipal utiliza RSA-SHA1/SHA1,
  aceito na verificação desse retorno. As DPS enviadas usam SHA-256.
- A cadeia/revogação ICP-Brasil não foi completamente validada:
  Windows retornou `CRYPT_E_REVOCATION_OFFLINE`. Não afirmar validação integral.

Chave de consulta completa, CPF do tomador, XML/PDF reais e credenciais permanecem
no banco/mídia/evidências locais, fora do Git. Nunca retransmitir a nota acima
como teste de retomada. Use consultas ou massas sintéticas em base isolada.
Os testes negativos iniciais E0037/E1272 e relatórios sem autorização são históricos,
anteriores ao resultado municipal autorizado descrito aqui.

## 6. PDF e e-mail avulso/contratual

- DANFSe local v2.0, uma página A4, dados exclusivamente do XML autorizado,
  QR Code de consulta nacional, integridade e identidade verificadas antes de arquivar.
- Referência: NT 008 v1.02. A antiga API DANFSe foi suspensa em **03/08/2026**;
  o HTTP 503 antigo deixou de ser dependência para disponibilizar o PDF.
- A nota real possui PDF final arquivado. Visualização/download estão na tela Fiscal.
  O arquivo foi renderizado e conferido visualmente; o visualizador PDF nativo da
  sessão automatizada ficou vazio, apesar do HTTP 200 e PDF válido. O download
  é a alternativa disponível. Não alterar globalmente a CSP para contornar isso.
- O gerador bloqueia XML com grupo IBS/CBS até ampliar o leiaute. Cancelamento e
  substituição ainda precisam de implementação, eventos e representação correspondente.
- E-mail avulso: PDF e XML separados. Contratual: ZIP com nota PDF/XML, relatório
  aprovado em PDF, custos aprovados XLSX/PDF, kit de certidões ZIP com índice,
  índice geral e manifesto de hashes.
- Certidões devem estar ativas, com PDF, emitidas e vigentes na data do envio,
  negativas ou positivas com efeito de negativa. Todos os tipos exigidos no
  contrato precisam estar atendidos. Sem exigências específicas, usa certidões
  aptas dos tipos ativos da empresa, com ao menos um PDF válido.
- Preparação, revisão, confirmação e histórico são separados. Revalidação no envio
  bloqueia certidão vencida/alterada, nova exigência e versão aprovada substituída.
  Pacote acima de 15 MB de conteúdo é bloqueado.
- Estados distinguem simulação, aceitação SMTP e ausência de confirmação.
  Aceitação pelo servidor não comprova entrega na caixa postal. Não há retry automático.
- **Nenhum e-mail externo foi enviado nos testes.** SMTP real ainda depende de
  `EMAIL_URL` e `DEFAULT_FROM_EMAIL`; no perfil local exige `KSCENTRAL_EMAIL_REAL=True`.
  Os testes utilizam locmem e SMTP mock. Detalhes em [pdf_e_entrega_nfse.md](pdf_e_entrega_nfse.md).

## 7. Financeiro e operação

**Financeiro:** contas, categorias, centros por contrato, contas a pagar/receber,
baixas integrais auditadas, recorrências, DRE, caixa, aging, recebível idempotente
de NFS-e e importação CSV/OFX. Conciliação manual verifica empresa, conta, tipo e
valor; identificadores repetidos são deduplicados ou rejeitados se divergentes.
Os testes de pagamento/conciliação foram sintéticos. Não marcar a nota real como paga.

**Operação:** tarefas, quadro, prioridades, prazos, transições, evidências,
apontamentos decimais e limite diário de 24 horas por usuário. Operação vê contratos
alocados; relatórios sugerem tarefas concluídas ou com horas no mês, excluindo canceladas.
Revisão/aprovação preserva versão, responsável, data e PDF. Não inventa atividades.

**Custos:** composição mensal por contrato com grupo, quantidade, valor, rateio,
periodicidade e fonte. Anual divide por 12; único pertence à competência.
BDI = `(1+AC+SG+R)*(1+DF)*(1+L)/(1-I)-1`, percentuais em frações.
Financeiro/Administrador aprova. XLSX conserva fórmulas e resultados em cache,
com proteção de textos contra execução como fórmula; PDF resume composição.
Documentos aprovados são imutáveis no fluxo: alterações exigem nova versão.

Não há contrato real cadastrado para a nota avulsa nem pacote contratual real
montado nesta entrega. O fluxo foi validado com contratos/certidões sintéticos em
banco isolado. Documentos de QA ficaram em `.tools`, sem despesas ou entregas
fictícias cadastradas no banco operacional.

## 8. Arquivos e pontos de entrada

| Área | Pontos principais |
|---|---|
| Fiscal | `apps/fiscal/models.py`, `views.py`, `views_entrega.py`, `forms*.py`, `services/` |
| Integrações | `certificado.py`, `services/el_nacional.py`, `emissao.py`, `importacao.py`, `producao.py`, `homologacao.py`, `xml/schemas/` |
| PDF/pacotes | `services/pdf_nfse.py`, `services/entregas.py`, `templates/pdf/`, `apps/core/pdf.py` |
| Financeiro | `apps/financeiro/models.py`, `services/`, `abas.py`, telas e tarefas |
| Relatórios | `apps/operacao/models.py`, `relatorios.py`, `services.py`, `abas.py` |
| Catálogo | `apps/catalogo/importador.py`, `municipal.py`, `services.py`, migrations e comandos |
| Local | `config/settings/local.py`, `test_local.py`, `scripts/iniciar_local.ps1`, `preparar_pdf_windows.ps1` |
| Testes novos | `tests/test_consulta_empresas.py`, `test_integracao_nfse.py`, `test_fiscal_integrado.py`, `test_entregas_nfse.py`, `test_fase4_rascunhos.py`, `test_fase5_financeiro.py`, `test_fase6_operacao.py` |

Todas as migrações novas de cadastro/catálogo/fiscal/financeiro/operação foram
aplicadas ao SQLite local; `makemigrations --check` não encontrou diferenças.
Schemas oficiais e adaptações estão documentados nos respectivos README.
Não editar ou afrouxar XSD/assinatura para mascarar rejeições fiscais.

## 9. Verificações executadas e reprodução

- Suíte local completa: **158 testes aprovados**, após as novas funcionalidades.
  Fluxo HTTP de permissões/relatórios/custos/e-mail revalidado separadamente.
- Ruff, Django check, migrações em dia e `git diff --check` aprovados.
- PDFs da nota real e dos modelos relatório/custos/índices renderizados e
  conferidos visualmente. XLSX testado com fórmulas, valores em cache e BDI.
- Cobertura fiscal/financeira do incremento anterior: **71%**, incluindo comandos
  sem cobertura. Não foi medida novamente após PDF/pacotes; não afirmar meta de 80%.
- Navegador: login, nota autorizada, anexos, botões e formulário de envio conferidos.
  Em `127.0.0.1:8000` havia service worker de outro sistema municipal; foi usada
  origem `localhost:8000` para evitar interferência. Não limpar dados de outros sistemas.

```powershell
# Dentro do workspace, usando o .env existente:
.venv/Scripts/python.exe manage.py migrate --settings=config.settings.local
.venv/Scripts/python.exe manage.py check --settings=config.settings.local
.venv/Scripts/python.exe manage.py makemigrations --check --dry-run --settings=config.settings.local
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m pytest --ds=config.settings.test_local
.venv/Scripts/python.exe manage.py runserver 127.0.0.1:8000 --noreload --settings=config.settings.local
```

Em máquina nova, instale `requirements-dev.txt`, prepare o WeasyPrint Windows
e siga [testes_locais.md](testes_locais.md). Não execute `preparar_demo` para
resetar acesso: ele preserva a senha existente. PyMuPDF foi usado apenas para QA
local, não é dependência de execução do sistema. CI PostgreSQL/Docker não foi
executado nesta máquina; resultado local não comprova locks/concorrência de produção.

## 10. Dados locais e cuidados obrigatórios na continuidade

- `.env`, `local.sqlite3`, mídia, `.tools`, backups, PFX/P12 e chaves privadas
  são ignorados pelo Git. Não enviar esses arquivos ao repositório ou terceiros.
- **Preservar `FIELD_ENCRYPTION_KEY` existente.** Regenerar a chave impede ler
  A1/senha/token cifrados. Recuperação requer banco, mídia e chave correspondentes.
- Backups locais: `.tools/backups/antes-fiscal-integrado.sqlite3` e
  `.tools/backups/antes-pdf-pacotes.sqlite3`. Evidências em
  `.tools/emissoes-producao/<id-DPS>/`; documento anterior à omissão da chave
  de consulta foi preservado em `.tools/handoff-docs/`.
- O A1 está cadastrado cifrado; o arquivo original permanece local na raiz.
  Não colocar senha, token, CPF real, XML/PDF real ou chave de consulta em testes/docs.
- Autorizações fiscais desta conversa dizem respeito à operação já realizada.
  Não interpretar este documento como autorização para novas emissões reais,
  envios a destinatários, cancelamentos ou mudanças cadastrais fiscais.
- Conferir estado atual antes de agir: cadastros, vigência de percentuais,
  validade do A1, certidões, versão aprovada, ambiente e histórico de tentativas.

## 11. Pendências e prioridade sugerida

1. **Aceite contratual real:** cadastrar contrato/cliente, certidões exigidas,
   atividades e custos efetivos; revisar/aprovar e testar pacote com destinatário
   autorizado. Configurar SMTP e validar entrega real quando solicitado.
2. **Fiscal:** cancelamento/substituição e eventos, guias, demais regimes/retenções,
   representação completa IBS/CBS quando aplicável; validar cadeia/revogação;
   homologar novos códigos municipais. Nacional direto depende de habilitação externa.
3. **Operação/IA:** seleção de evidências/legendas no relatório, DOCX e Gemini
   com revisão humana, controle de custos e configuração segura.
4. **Fase 7:** sistemas, monitoramento, incidentes e SLA não implementados.
   Se o contrato exige relatório SLA, o pacote bloqueia envio para não ficar incompleto.
5. **Financeiro/custos:** vínculo a venda/empenho, transferências, categorias em
   árvore, DAPS opcional, orçamento de custos completo, importações e análises avançadas.
6. **Produção/qualidade:** executar CI PostgreSQL, stack Docker/Redis/worker/beat,
   concorrência, carga, backup/restauração, segurança final, acessibilidade e manual.
   Meta de cobertura/aceites do plano ainda não alcançada integralmente.
7. **Entrega Git:** trabalhar a partir da branch publicada, acompanhar o CI remoto
   e planejar revisão/merge/deploy separadamente. Não tratar push como deploy aprovado.

## 12. Leituras complementares

- [Fiscal integrado](fiscal_integrado.md): configuração e fluxo de emissão/recebível.
- [PDF e entrega](pdf_e_entrega_nfse.md): uso, aprovação, certificados e SMTP.
- [Resultado real](emissao_producao_20261009.md): evidências e limites da emissão.
- [Integração E&L](integracao_el_dps.md): canal municipal e comunicação DPS.
- [Testes locais](testes_locais.md) e [fases](fases.md): execução e aceites pendentes.
- `testes_emissao_nfse.md`, `teste_comunicacao_producao.md` e
  `alternativas_api_nfse.md` registram investigações anteriores; prevalecem os
  resultados posteriores e o estado atual documentado nesta passagem.
