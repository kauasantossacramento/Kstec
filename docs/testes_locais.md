# Desenvolvimento e testes locais no Windows

Repositório: `C:\Users\KS TEC\sistema_kstec_`. Branch de trabalho: `desenvolvimento-local`.
A pasta anterior `sistema_kstec` permanece preservada.

## Instalação

No PowerShell, na raiz do projeto:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
powershell -ExecutionPolicy Bypass -File scripts\preparar_pdf_windows.ps1
powershell -ExecutionPolicy Bypass -File scripts\iniciar_local.ps1 -Preparar
```

O último comando migra o banco, carrega catálogo, tipos de certidão e categorias financeiras e cria
`demo@kstec.local`, com senha aleatória exibida somente na primeira execução.
Reexecutar preserva a senha existente. Para iniciar novamente, omita `-Preparar`.
Acesse http://127.0.0.1:8000/ . O servidor fica restrito à máquina local.

O perfil `config.settings.local` usa `local.sqlite3`, cache em memória,
Celery síncrono, e-mail no console e MFA opcional. É destinado a demonstração
e testes de uso. PostgreSQL, Redis, workers e MFA de produção permanecem nos
perfis originais. SQLite não valida concorrência, locks ou comportamento
monetário do PostgreSQL; a homologação precisa passar pelo ambiente Docker/CI.
Ver [limitações documentadas pelo Django](https://docs.djangoproject.com/en/5.2/ref/databases/#sqlite-notes).

PDFs usam o executável oficial WeasyPrint 70.0 instalado em `.tools`, evitando
conflito com as DLLs do Tesseract presentes nesta máquina. Os perfis de produção
continuam usando a biblioteca Python. Ver [instalação oficial no Windows](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#windows).

## Testes automatizados

```powershell
.\.venv\Scripts\python.exe -m pytest --ds=config.settings.test_local --cov=apps.fiscal.services --cov-report=term-missing
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe manage.py check --settings=config.settings.local
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=config.settings.local
```

A suíte de CI segue com `config.settings.test` e PostgreSQL.
Os e-mails dos testes ficam na memória; os do perfil local aparecem no console.

## Roteiro de uso

1. Entrar com o administrador local. Abrir Painel, Agenda e Catálogo.
2. Criar cliente em Cadastros; informar CNPJ e sair do campo ou usar **Consultar CNPJ**.
   A BrasilAPI preenche razão social, nome fantasia, endereço, contatos, situação,
   abertura, CNAE, natureza jurídica, porte e Simples quando disponíveis.
   Conferir os dados antes de salvar. A consulta também está em Configurações → Empresa.
   CPF e inscrições estadual/municipal não são obtidos por esta consulta.
   Se o provedor estiver indisponível, tentar novamente ou preencher manualmente.
3. Cadastrar contrato e aditivo; verificar saldo e competências no hub.
4. Criar orçamento, selecionar 500 cartões e as variações; conferir R$ 410,00
   para couché 300g, verniz e faca especial conforme o seed do catálogo.
5. Gerar PDF e abrir o link público; aprovar em sessão sem login e converter em venda.
6. Em Fiscal → Perfis fiscais, cadastrar as alíquotas confirmadas pelo contador.
7. Em Fiscal → Nova NFS-e (rascunho), selecionar tomador, serviço, perfil,
   competência e valores. No Simples, informar a alíquota da competência.
8. Salvar e conferir base, ISS, retenções, líquido e histórico. Editar e verificar
   novo registro de auditoria. Mercadorias e vínculos com outra empresa são rejeitados.
9. Cadastrar certidão de teste, gerar kit e baixar o ZIP com índice PDF.
10. Em Financeiro, cadastrar uma conta e conferir saldo inicial/data de referência.
    Criar receita/despesa com categoria compatível, centro de custo, competência e vencimento.
11. Registrar baixa integral de pagamento de teste: conferir juros, multa, desconto,
    valor pago e auditoria. Para ordem bancária, informar número; não há execução de pagamento bancário.
12. Conferir Demonstrativo: competência determina o resultado; data de pagamento
    determina o caixa. Filtrar por contrato e consultar faixas de atraso no Financeiro.
13. Criar recorrência mensal/anual e clicar **Gerar previsões**. Repetir e verificar
    zero duplicações. Dia 31 vence no último dia disponível dos meses mais curtos.
14. Em Operação, criar tarefa, registrar horas e mudar a situação. Para concluir,
    preencher resumo da entrega ou desmarcar inclusão no relatório. Conferir quadro e histórico.
15. Testar com papel Operação alocado ao contrato: tarefas de outros contratos e
    seus anexos devem ficar inacessíveis. Leitura pode consultar e baixar anexos,
    sem criar/alterar registros ou registrar pagamentos.

Recorrências geram previsões por competência para o mês corrente e os 11 seguintes.
A geração não recompõe meses anteriores. Alterar/desativar uma recorrência não
altera/cancela previsões já criadas; revisar os lançamentos existentes separadamente.
No perfil local não há worker/beat executando periodicamente: use **Gerar previsões**.
No ambiente com Celery beat, as tasks financeiras já previstas no plano estão implementadas.

Rascunhos fiscais não geram numeração oficial, transmissão ou autorização.
Alíquotas usadas nos testes são exemplos, não enquadramento fiscal da KS TEC.

## Pendências do plano

| Fase | Estado observado | Pendente |
|---|---|---|
| 0 | Infraestrutura, CI, Docker e scripts existentes | Executar stack PostgreSQL/Redis; validar backup/restauração e deploy |
| 1 | Núcleo, login, MFA, auditoria, layout e cadastros existentes; logo oficial aplicada | Aceite visual/acessibilidade em todos os tamanhos |
| 2 | Contratos, aditivos, competências, certidões e kits existentes | Aceite com dados reais e e-mail em homologação |
| 3 | Catálogo, importador e orçamento público existentes; anexos XLSX reais importados no banco local | Validação dos códigos de cada serviço pelo contador |
| 4 | Emissão municipal autorizada, configuração A1, XML/XSD/assinatura, idempotência, consulta, PDF e envio documental | Cancelamento/substituição, outros regimes e guias; canal nacional direto rejeitado E0039 |
| 5 | Contas, lançamentos, baixas, recorrências, DRE/caixa, recebível da NFS-e e conciliação OFX/CSV | Vínculo a venda/empenho, transferências, árvore de categorias e aceite com extrato real |
| 6 | Tarefas, horas, anexos, alocação e relatório mensal aprovado em PDF com versões | Evidências específicas de relatório, DOCX e Gemini; aceite com atividades reais |
| 7 | Não implementada | Monitoramento, incidentes e SLA |
| 8 | Composição mensal de custos, BDI, XLSX/PDF e pacote contratual implementados | Orçamento de custos completo, importações, análises avançadas e aceite de contrato real |
| 9 | Não concluída | Segurança final, carga, manual, migração e lançamento |

O arquivo do plano no repositório coincide com o anexo em conteúdo de linhas.
As marcações antigas de conclusão em `fases.md` registram entregas anteriores;
não constituem evidência de homologação externa.

## Verificação nesta sessão

- Windows 11, Python 3.13.14 e Django 5.2.18 (produção/CI previstos com Python 3.12).
- Banco local migrado e carga inicial executada; `/health` e login disponíveis.
- 105 testes aprovados na suíte completa, com geração real de PDFs de orçamento e índice de kit.
- Regras fiscais, financeiras e operacionais verificadas por testes de services e fluxos HTTP.
- Navegador: login, navegação, cliente sintético, perfil fiscal e rascunho criados.
  No exemplo R$ 1.000,00 × 5%, ISS R$ 50,00 e líquido R$ 1.000,00 sem retenção.
- Anexos reais da pasta anterior extraídos para `.tools/tabelas_fiscais`, sem alterar
  o ZIP original. Importação reportou 232 itens LC 116, 576 códigos nacionais,
  918 NBS e 896 correlações processadas. Não substitui validação contábil.
- Lint, verificação Django e migrações em dia aprovados.
- Navegador: conta DEMO, receita de R$ 1.000,00 baixada por PIX, resultado/caixa
  conferidos; despesa recorrente de R$ 100,00 gerou 12 previsões e zero na repetição;
  tarefa DEMO com 1,50 h e situação Em andamento. Dados sintéticos permanecem no banco local.
- Cópia do banco antes das migrações financeiras/operacionais em
  `.tools/local-antes-fases5-6.sqlite3`; arquivo ignorado pelo Git.
- Docker, homologação externa, concorrência PostgreSQL, Lighthouse, backups,
  e-mail real e emissão fiscal não verificados nesta máquina.

Atualização da consulta CNPJ: 30 testes relacionados aprovados, cobrindo extração,
persistência dos campos, Simples verdadeiro/falso/desconhecido, timeout, resposta
inválida e falhas HTTP. Na consulta real do CNPJ da KS TEC, a BrasilAPI retornou
HTTP 500 com mensagem de erro 503 do provedor; nenhum cadastro foi criado a partir
dessa falha. O formulário exibiu a indisponibilidade e preservou o preenchimento.

Atualização fiscal de 08/10/2026: A1 validado e DPS de R$ 1,00 transmitida ao
ambiente nacional de produção restrita, rejeitada por convênio municipal (E0037).
Endpoint municipal acessível, consulta SOAP com retorno vazio. Nenhuma NFS-e
autorizada. Esta atualização substitui a informação acima sobre homologação externa
não verificada; veja [testes_emissao_nfse.md](testes_emissao_nfse.md).


## Atualização fiscal/financeira integrada — 09/10/2026

O [guia fiscal integrado](fiscal_integrado.md) descreve as telas e os limites atuais.
A configuração recebeu A1/token cifrados, IM 16845, canal municipal E&L, série 1,
ISS 2% e tributos aproximados 6% informados pelo usuário, com vigência em outubro/2026.
Foi importada a nota real nº 2600000000012, confirmada pela consulta nacional,
com recebível de R$ 1,00 pendente e XML disponível. Nenhuma nota adicional foi emitida
na implementação deste incremento. Consulta municipal no navegador retornou HTTP 200.

Tabelas atuais: 335 códigos nacionais vigentes, 918 NBS, 896 correlações e
204 referências municipais da LC 010/2021. Código E&L 101 / LC 01.01 confirmado;
os demais exigem confirmação, sem conversão presumida do item legal em código de API.

Roteiro adicional:

1. Abrir Fiscal → Configuração; conferir validade do A1, vigência dos percentuais e canal.
2. Consultar tabelas e códigos municipais; conferir TI-DEV no catálogo.
3. Abrir a nota autorizada, consultar resultado e baixar XML.
4. Abrir o recebível vinculado. Não registrar pagamento da nota real sem comprovação.
5. Em uma base isolada de teste, importar CSV/OFX sintético, repetir para conferir
   deduplicação e conciliar com lançamento compatível. Verificar baixa e auditoria.

A cobertura de testes inclui XML adulterado, indisponibilidade da consulta, timeout
após POST sem repetição, importação fiscal idempotente, permissões de Leitura,
segredos fora do formulário/histórico e autorização preservada se o financeiro falhar.
A suíte usa respostas fiscais simuladas e extratos sintéticos, sem POST real.
A cobertura global fiscal/financeira ainda exige ampliar testes dos comandos de
integração e dos fluxos HTTP para atingir o aceite de 80% indicado no plano.


Validação do incremento anterior: suíte completa com 140 testes aprovados; lint, check Django
e ausência de migrações pendentes aprovados. Cobertura fiscal/financeira medida em
71% (inclui comandos de operação sem cobertura automatizada). Relatório local em
`.tools/cobertura-fiscal-financeiro/index.html`. O fluxo financeiro foi conciliado
apenas com dados sintéticos nos testes; o recebível da nota real permanece pendente.

## NFS-e em PDF e envio documental

Ver [PDF e entrega da NFS-e](pdf_e_entrega_nfse.md) para os fluxos avulso e
contratual, papéis de aprovação, requisitos das certidões e configuração de SMTP.
A suíte completa passou com 158 testes, incluindo alocação, isolamento entre empresas,
horas por competência e bloqueio de SLA. Lint, check Django e migrações também aprovados.
