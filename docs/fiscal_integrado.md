# Fiscal e financeiro integrados — 09/10/2026

## Configuração local aplicada

Abra `/fiscal/configuracao/`. Prestador: KS TEC SOLUÇÕES DE TECNOLOGIA LTDA,
CNPJ 62.501.281/0001-13, IM 16845, Valença/BA (2932903).
Canal padrão municipal E&L, ambiente produção, série DPS 1.
Certificado A1, senha e token foram cadastrados cifrados no banco, com metadados
de validade. Os formulários não retornam os segredos; campos vazios preservam o cadastro.
O histórico do certificado exclui os conteúdos cifrados e a senha.

ISS 2% e tributos totais aproximados do Simples 6% são informações fornecidas
pelo usuário nesta conversa, aplicadas à competência outubro/2026, com fonte
registrada. Não são apuração PGDAS nem valores calculados pelo IBPT. A vigência
termina em 31/10/2026; outra competência exige revisão e atualização da configuração.
O percentual aproximado não é descontado do recebível.

Conta de recebimento permanece em branco, pois só existe uma conta DEMO no banco.
O prazo inicial é 30 dias, editável, e cada nota pode informar um vencimento próprio.
Cadastre a conta efetiva em Financeiro antes de registrar uma baixa real.

A chave `FIELD_ENCRYPTION_KEY` está no `.env` local. Restauração do banco com
credenciais exige preservar também essa chave; não a regenere para um banco existente.
Backup anterior a esta integração: `.tools/backups/antes-fiscal-integrado.sqlite3`.
Banco, mídia, certificados, `.env` e evidências locais estão fora do Git.

## Tabelas e preenchimento

Em `/catalogo/tabelas/`, estão carregados 335 códigos nacionais vigentes, 918 NBS,
896 correlações e 204 serviços municipais de Valença. O importador da interface aceita
XLSX nacional/NBS/correlações e PDF/CSV municipal, com validação transacional.
Arquivos sem registros válidos ou com duplicidades municipais não substituem a tabela.

A referência municipal veio do Anexo I da
[LC municipal 010/2021](https://www.valenca.ba.leg.br/leis/legislacao-municipal/leis-de-2021/lei-complementar-010-2021-codigo-tributario.pdf/at_download/file).
Ela é identificada pela versão da fonte; eventuais alterações posteriores precisam
ser confrontadas antes de usar outros serviços. O item legal LC 116 e o código
`cIntContrib` do provedor são campos diferentes; o importador não inventa a conversão.

O serviço TI-DEV usa LC 116 01.01, cTribNac 010101, NBS 115022000 e código municipal
101, combinação comprovada na nota autorizada. Outros códigos municipais exigem
confirmação em `/catalogo/municipais/` antes da transmissão.
No catálogo, o seletor municipal mostra apenas códigos confirmados para o município.

## Fluxo da interface

1. Cadastre e confira tomador, serviço e perfil. Crie a nota como rascunho.
2. Abra **Revisar e transmitir**. A tela apresenta ambiente, canal, valores e códigos.
   São verificados certificado, competência, vigência, percentuais e código municipal.
   Cadastros alterados após o rascunho exigem revisão e novo salvamento.
3. A confirmação na tela transmite uma nota efetiva no ambiente selecionado.
   A tentativa e a numeração são persistidas antes do POST. Somente o papel Fiscal
   ou Administrador transmite; Leitura não altera configuração ou emissão.
4. Use **Consultar resultado** para processamento ou falha de comunicação.
   O sistema bloqueia segundo POST e troca automática de canal para a mesma nota.
5. XML autorizado é arquivado e gera recebível único em produção. Caso o financeiro
   esteja incompleto, a autorização é preservada e a tela permite gerar o recebível
   após corrigir os cadastros. Homologação não gera recebível real.
6. Em Financeiro → Extratos e conciliação, importe CSV ou OFX. Confira a transação
   e escolha o lançamento de mesmo tipo/valor. A confirmação registra a baixa.
   Não executa transferência bancária. Identificador repetido com dados iguais é
   ignorado; dados divergentes com o mesmo identificador são rejeitados.

CSV UTF-8, separado por ponto e vírgula:

```csv
id;data;valor;descricao
IDENTIFICADOR-DO-BANCO;2026-10-09;1,00;Recebimento de serviço
```

Créditos positivos, débitos negativos; datas ISO ou DD/MM/AAAA. OFX exige FITID,
DTPOSTED e TRNAMT. O exemplo é formato, não comprovação do pagamento da nota real.

## Resultado real e limites

A nota nº **2600000000012**, R$ 1,00, está em Fiscal com XML, consulta municipal
e recebível pendente, vencimento 08/11/2026. Sua importação foi confirmada pela
API nacional autenticada, sem novo POST. A série foi sincronizada com a DPS já usada.
O botão **Consultar resultado** foi testado no navegador com HTTP 200 municipal.

O emissor nacional direto retornou E0039 e permanece bloqueado na configuração.
A consulta nacional da nota municipal funciona. O serviço DANFSe retornou 503
na emissão anterior; o PDF agora é gerado localmente do XML autorizado, conforme
a NT 008 v1.02, e está disponível na tela da nota. A API antiga foi suspensa
em 03/08/2026. Veja [PDF e entrega por e-mail](pdf_e_entrega_nfse.md).

O adaptador transmite ME/EPP optante do Simples sem retenções, descontos ou deduções.
Rascunhos calculam situações adicionais, mas elas são bloqueadas na transmissão
até implementar seus campos e testes fiscais. Cancelamento/substituição e guias
também permanecem pendentes; consulte [fases.md](fases.md).

XML recebido é validado em XSD, digest, assinatura, identidade e correspondência
com a DPS. O importador exige comparar o XML com a resposta nacional autenticada.
A verificação de assinatura usa o certificado incorporado; não substitui validação
completa da cadeia e revogação ICP-Brasil, cujo resultado anterior ficou offline.
Testes locais SQLite não comprovam concorrência/locks do PostgreSQL.
