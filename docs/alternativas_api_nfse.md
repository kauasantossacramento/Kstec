# Alternativas de comunicação NFS-e — verificação de 09/10/2026

> Registro histórico das consultas iniciais. Resultado posterior: uma NFS-e real
> autorizada pelo municipal E&L e recuperada pela consulta nacional; emissão direta
> nacional rejeitada E0039. Leia [fiscal_integrado.md](fiscal_integrado.md) e
> [PASSAGEM_AGENTE_IA.md](PASSAGEM_AGENTE_IA.md) para o estado final.

Atualização posterior: [teste negativo de comunicação em produção](teste_comunicacao_producao.md)
nos dois endpoints. Ambos responderam com erros de estrutura de DPS ausente;
autorização fiscal continua sem validação.

Existe API oficial de emissão direta pela SEFIN Nacional, distinta da API
municipal E&L que compartilha documentos com o ADN. Não foi identificada outra
API nacional comum que dispense a habilitação aplicável ao prestador e município.
Nenhum documento foi emitido nesta verificação; foram realizadas consultas GET.

## Comparação

| Canal | Finalidade | Aplicação à situação atual |
|---|---|---|
| SEFIN Nacional, `POST /nfse` | Recebe DPS assinada, valida e gera NFS-e de forma síncrona | Alternativa oficial direta; habilitação ordinária de Valença/BA não indicada pelos parâmetros atuais |
| E&L municipal, API DPS | Recebe DPS e processa compartilhamento nacional de forma assíncrona | Canal já autenticado e com recebimento HTTP 201 em homologação; compartilhamento rejeitado E1272 |
| ADN contribuinte | Distribuição/consulta de documentos e eventos disponíveis ao contribuinte | Não substitui o emissor SEFIN nem o emissor municipal |
| SEFIN por decisão administrativa/judicial | Recebe NFS-e completa em fluxo específico | Exige decisão cadastrada e autorização municipal prévia; não há evidência dessa autorização para a KS TEC |

A [documentação oficial do contribuinte SEFIN](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual/manual-contribuintes-emissor-publico-api-sistema-nacional-nfs-e-v1-2-out2025.pdf/@@download/file)
define a emissão em `POST /nfse`, consultas em `GET /dps/{id}` e
`GET /nfse/{chaveAcesso}`, com validações dependentes de parâmetros municipais,
cadastro do contribuinte e cadastros federais. O XML assinado é compactado e
transmitido pelo cliente com autenticação por certificado A1.

Base de produção: `https://sefin.nfse.gov.br/SefinNacional`.
Base usada nas chamadas de homologação: `https://sefin.producaorestrita.nfse.gov.br/SefinNacional`.
Não confundir a URL de documentação de homologação, que contém `/API/`, com a
base efetiva das chamadas testadas. A [lista oficial de APIs](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/apis-prod-restrita-e-producao)
separa SEFIN, ADN, CNC, parâmetros e DANFSe.

O [manual ADN para contribuintes](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual/manual-contribuintes-apis-adn-sistema-nacional-nfse.pdf)
não oferece emissão ordinária de DPS como alternativa ao `POST /nfse` da SEFIN.
O [manual do fluxo por decisão](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual/manual-contribuintes-emissor-publico-api-emissao-decisao-administrativa-e-judicial.pdf)
exige que o município cadastre previamente a decisão e autorize o contribuinte.
O endpoint específico é `POST /decisao-judicial/nfse`; ele não é uma alternativa
comum para resolver falhas de convênio em homologação.

## Estado consultado ao vivo

Consultas com o A1 da empresa em 09/10/2026:

- Documentação SEFIN, produção e produção restrita: HTTP 200.
- Convênio IBGE 2932903, produção: HTTP 200, `aderenteAmbienteNacional=1`,
  `aderenteEmissorNacional=0`, `situacaoEmissaoPadraoContribuintesRFB=0`.
- Convênio em produção restrita: HTTP 404, mensagem de convênio ainda não ativo.
- Evidência local: `.tools/diagnostico-nfse-20261009.json`, ignorada pelo Git.

Inferência: a configuração consultada não indica habilitação ordinária municipal
do Emissor Nacional. Não foi verificada autorização individual/excepcional da
KS TEC e não foi transmitida DPS à SEFIN de produção.

O E1272 anterior ocorreu em homologação do canal municipal E&L. Não permite
concluir que produção falhará: os convênios são parametrizados por ambiente e
o convênio de produção respondeu ativo para o ADN. Produção municipal permanece
sem teste de emissão, dependendo dos dados fiscais reais e código municipal autorizado.

## Transição do Simples Nacional

A [notícia oficial de prorrogação](https://www.gov.br/nfse/pt-br/noticias/comite-gestor-do-simples-nacional-prorroga-a-obrigatoriedade-de-emissao-de-notas-fiscais-de-servico-pelo-emissor-nacional-da-nfs-e),
publicada em 11/08/2026, informa que a Resolução CGSN 191/2026 adiou a exigência
do Emissor Nacional para ME/EPP do Simples de 01/09/2026 para **01/11/2026**.
Portanto, a data antiga não deve embasar o roteamento atual de outubro.
A aplicação dessa transição à empresa depende de seu enquadramento efetivo;
o cadastro local indica Simples, mas não constitui confirmação oficial da opção.

## Caminho de desenvolvimento

Manter adaptadores separados para E&L municipal e SEFIN direta. Selecionar o canal
após verificar ambiente, convênio e habilitação do prestador. Não usar uma falha
de emissão para reenviar automaticamente por outro emissor, pois isso pode gerar
duplicidade. Confirmar o resultado da DPS original antes de trocar o canal.

Para a situação observada, o canal municipal continua sendo o candidato a testar
em produção quando serviço efetivo, alíquota e código municipal forem confirmados.
Em paralelo, cabe validar a habilitação para SEFIN direta na transição de novembro.
