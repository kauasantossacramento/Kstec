# PDF e entrega da NFS-e

Implementação local em 09/10/2026. A NFS-e nº 2600000000012 já tem PDF
arquivado na tela Fiscal → Notas, nos botões **Visualizar PDF** e **Baixar PDF**.
O PDF usa o XML autorizado, preserva sua chave e inclui QR Code de consulta.

## DANFSe

O sistema gera uma página A4 conforme o modelo DANFSe v2.0 da
[NT 008, versão 1.02](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/rtc/nt-008-se-cgnfse-danfse-20260714-v1-02.pdf).
A API anterior do DANFSe foi suspensa em 03/08/2026; o HTTP 503 observado
na emissão anterior não impede mais a disponibilização do documento.
Os dados fiscais impressos vêm do XML, não dos cadastros atuais.
Campos ausentes permanecem sem informação. O gerador verifica hash,
identidade, autorização, DPS, ambiente e quantidade de páginas antes de arquivar.

O leiaute implementado atende o fluxo atual do Simples sem grupo IBS/CBS.
XML com esse grupo é bloqueado até ampliar a representação; não se imprime
um DANFSe omitindo seus valores. Cancelamento e substituição ainda não estão
implementados. O QR Code consulta a situação atual no portal nacional.

## Envio avulso

1. Abra uma NFS-e autorizada em produção e clique **Enviar por e-mail**.
2. Informe destinatários, assunto e mensagem. O cadastro do tomador pode fornecer
   o e-mail inicial, que continua editável.
3. Clique **Montar documentos para revisão**. Baixe o ZIP para conferir os arquivos.
4. Marque a conferência e clique **Enviar e-mail**, ou **Simular envio local**.

O e-mail avulso leva PDF e XML como anexos separados. O ZIP de revisão e o
manifesto ficam arquivados no histórico. Fiscal, Financeiro e Administrador
podem preparar e enviar; Leitura pode acessar o PDF e não realiza envios.
Não houve envio externo durante os testes de desenvolvimento.

## Envio por contrato

O vínculo da nota com contrato determina o pacote. Contrato e tomador devem
corresponder ao mesmo cliente e empresa. No hub do contrato, abra as abas
**Relatórios** ou **Custos** e acesse a preparação dos documentos da competência.

- **Relatório de atividades:** o rascunho sugere tarefas incluídas no relatório
  com conclusão ou horas na competência. Horas de outros meses e tarefas canceladas
  são excluídas. Operação alocada ao contrato ou Administrador revisa o texto,
  informa as atividades efetivas e aprova para gerar PDF.
- **Planilha de custos:** Financeiro ou Administrador cadastra grupo, descrição,
  quantidade, valor unitário, rateio, periodicidade e fonte. Custos anuais são
  divididos por 12; custos únicos são apropriados naquela competência. Os seis
  percentuais de BDI são informados na própria composição. A aprovação gera
  XLSX com fórmulas e resultados calculados, e PDF para conferência.
- **Certidões:** cadastre PDFs, situação, emissão e validade em Certidões.
  Configure os tipos exigidos no contrato. Todos os tipos exigidos precisam ter
  certidão ativa, negativa ou positiva com efeito de negativa, vigente no dia do
  envio. Sem exigências específicas, são usadas as certidões aptas dos tipos
  ativos da empresa; é necessário ao menos um PDF válido.

Relatório e custos precisam de versões aprovadas da mesma competência da nota.
Versões aprovadas são preservadas; alterações exigem nova versão. O custo não é
deduzido do valor da nota, e o sistema não inventa despesas ou atividades.

O e-mail contratual anexa um ZIP com PDF/XML da NFS-e, relatório PDF, custos
XLSX/PDF, kit de certidões ZIP com índice PDF, índice geral e manifesto de hashes.
Antes do envio, o sistema verifica novamente certidões, arquivos, exigências e
versões aprovadas. Mudanças exigem montar outro pacote. Pacotes acima de 15 MB
de conteúdo são bloqueados. Contratos que exigem relatório de SLA ficam bloqueados
enquanto esse módulo não estiver implementado.

## E-mail real e simulação

O ambiente local usa simulação por padrão. Para enviar efetivamente, configure
`EMAIL_URL` com o SMTP autorizado, `DEFAULT_FROM_EMAIL` com o remetente do provedor
e `KSCENTRAL_EMAIL_REAL=True` no `.env`, então reinicie o servidor. Preserve os
segredos fora do Git. Em produção, o backend segue a configuração do ambiente.

Estados do histórico: preparado para revisão, enviando, aceito pelo servidor,
simulado e sem confirmação. Aceitação SMTP não comprova chegada à caixa postal.
Falha ou timeout não dispara repetição automática: confira o provedor antes de
preparar outro envio. Um envio já iniciado não pode ser executado novamente.

Os testes usam caixa de e-mail em memória e SMTP simulado, sem destinatário externo.
Os PDFs da nota real e dos modelos contratuais foram renderizados e conferidos
visualmente. Os documentos contratuais de QA são sintéticos e ficaram em `.tools`,
sem cadastro de atividades ou despesas fictícias nos contratos reais.
