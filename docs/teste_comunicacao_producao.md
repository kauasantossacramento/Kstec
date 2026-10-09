# Comunicação em produção — 09/10/2026

Atualização: depois deste teste negativo, foi emitida a nota real nº
2600000000012 pelo canal municipal. Resultado e validações em
[emissao_producao_20261009.md](emissao_producao_20261009.md).
As pendências descritas abaixo retratam a etapa anterior a essa emissão.

Foi realizado um **teste negativo** nos dois canais, usando requisição JSON `{}`,
sem DPS, assinatura XML, tomador, serviço ou valores fiscais. A conexão SEFIN usou
o A1 e a municipal E&L usou o token cadastrado localmente. Dados aleatórios de
homologação não foram convertidos em declarações fiscais de produção.

| Canal | Endpoint POST | Resposta |
|---|---|---|
| SEFIN direta | `https://sefin.nfse.gov.br/SefinNacional/nfse` | HTTP 400, ambiente 1, E1226: estrutura descompactada mal formada |
| Municipal E&L | `https://ba-valenca-pm-nfs-backend.cloud.el.com.br/producao05/api/nacional/nfse` | HTTP 400, ambiente 1, E1235: falha de esquema XML, erro estrutural null |

Os dois endpoints responderam no ambiente de produção e rejeitaram a estrutura
incompleta. Não retornaram chave de acesso nem XML de NFS-e autorizado.
Nenhuma nota foi gerada por esse teste.

O resultado valida que as requisições alcançam os serviços e recebem erros
de validação de estrutura. **Não valida a autorização de emissão**, o cadastro do
prestador, a permissão de uso de cada emissor ou os parâmetros tributários.
Não permite concluir qual canal autorizará uma DPS fiscal válida.

O usuário escolheu desenvolvimento de sistema e informou ISS de 2%. O item
`TI-DEV` corresponde a desenvolvimento de sistema sob medida, LC 116 `01.01`,
código nacional `010101` e NBS `115022000`. O código municipal `101` consta
no exemplo E&L e foi aceito na homologação; isso não comprova a autorização
específica desse código para o prestador em produção.

Permanece pendente a informação de tributos totais aproximados para o envio
válido de R$ 1,00. Os 6% existentes na massa de homologação não foram informados
pelo usuário e não devem ser transferidos para produção. Os 2% de ISS não
determinam o percentual total do Simples.

O leiaute oficial oferece `pTotTribSN` ou os grupos de valores/percentuais
aproximados por esfera (`vTotTrib` / `pTotTrib`). A regra E0712 não permite
`indTotTrib` para ME/EPP optante do Simples; omitir a estimativa dessa forma
não resolve a pendência. O enquadramento Simples existente no cadastro local
ainda não foi confirmado por consulta oficial.

O IBPT informa que sua tabela 26.2.B tem vigência de 20/09/2026 a 31/10/2026.
Os percentuais específicos para a NBS na Bahia ainda não foram obtidos. É
necessária uma tabela vigente com origem verificável ou a informação da
contabilidade para preencher os tributos aproximados. Essa informação tem
caráter informativo; não representa uma cobrança adicional criada pela nota.

Referências: [leiaute e regras nacionais](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual/documentacao-atual)
e [FAQ e vigência IBPT](https://deolhonoimposto.ibpt.org.br/Site/Faq).

Se um canal receber
uma DPS para processamento, é necessário confirmar seu resultado antes de enviar
a mesma operação pelo outro canal, para evitar duplicidade.

Evidência completa local: `.tools/testes-conexao-producao-20261009.json`, fora do Git.
Script do teste negativo: `.tools/testar_conexao_producao.py`; requer senha A1 em
variável efêmera e token no `.env`; o relatório não inclui credenciais.

Para os convênios e alternativas documentados, consulte
[alternativas_api_nfse.md](alternativas_api_nfse.md) e
[integracao_el_dps.md](integracao_el_dps.md).
