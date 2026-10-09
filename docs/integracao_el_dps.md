# Valença/BA — integração municipal DPS

Verificação posterior, 09/10/2026: [alternativas de API nacional](alternativas_api_nfse.md).
O convênio de produção permanece ativo para ADN e sem adesão ao Emissor Nacional;
o bloqueio de homologação não comprova indisponibilidade da produção municipal.

## Atualização com token — 08/10/2026

O token fornecido foi cadastrado em `.env`, ignorado pelo Git; seu valor não é
incluído neste relatório. A consulta autenticada retornou HTTP 400 / EL99 com
complemento específico de DPS ausente do repositório municipal. O cliente passou
a reconhecer somente esse retorno explícito como ausência; outros EL99 não
liberam envio.

Foi transmitida massa de homologação de R$ 1,00 com inscrição 16845 e o tomador
cadastrado. Classificação do exemplo E&L: municipal **101** (ainda não confirmado
como código autorizado do prestador), nacional **010101**, NBS **115021000**;
descrição explícita de teste sem valor fiscal. A tributação é sintética e não
alterou o perfil fiscal da empresa.

- Primeiro envio municipal: rejeitado HTTP 400 / **EL0496**, por falta de `pAliq`.
- Segundo envio, com `pAliq=2.00` da massa de teste: **HTTP 201**, recebimento
  municipal, `nfseXmlGZipB64="<em processamento adn nacional>"`.
- DPS recebida: `DPS293290326250128100011389999020261009024951`.
- Consultas posteriores: **HTTP 400 / E1272**, município inexistente ou não ativo
  no convênio municipal para compartilhamento com o ADN.

Conclusão: autenticação e recepção municipal DPS funcionaram em homologação;
o processamento nacional foi rejeitado. Não há XML nacional autorizado nem
emissão de produção neste teste. A prefeitura precisa verificar a habilitação
do convênio de produção restrita. O cliente não retransmitiu a DPS recebida.

Evidências locais: `.tools/emissoes-el-homologacao/<id>/dps-assinada.xml` e
`resultado.json`, incluindo recebimento e consulta posterior, fora do Git.

Novo comando (solicita senha do A1; usa token do `.env`):

```powershell
.\.venv\Scripts\python.exe manage.py testar_emissao_el "CAMINHO_DO_A1.pfx" --tomador CPF_CADASTRADO --enviar-homologacao --settings=config.settings.local
```

Sem `--enviar-homologacao`, apenas prepara XML assinado e valida XSD. O código
municipal padrão 101 e ISS 2% são exclusivamente dados do exemplo de teste,
não autorização para preencher operações reais. Para produção continuam pendentes
serviço efetivamente prestado, código municipal autorizado e parâmetros tributários.

As seções abaixo preservam o diagnóstico anterior ao token; a exigência de token
nelas descrita foi resolvida nesta atualização.

## Descoberta em 08/10/2026

O menu **APIs de Integração** do [portal municipal](https://ba-valenca-pm-nfs.cloud.el.com.br/)
apresenta o modelo DPS como ativo e ABRASF 2.04 como inativo para emissão,
disponível apenas para consultas. Portanto, o WSDL legado não deve ser utilizado
para desenvolver novas emissões.

URLs exibidas no portal:

- Homologação: `https://ba-valenca-pm-nfs-backend.cloud.el.com.br/producao05/api/nacional/homologacao/nfse`
- Produção: `https://ba-valenca-pm-nfs-backend.cloud.el.com.br/producao05/api/nacional/nfse`

O [pacote oficial E&L](https://s3.us-east-1.amazonaws.com/el.com.br/nfse/Layout_EL_DPS_Nacional.zip)
contém manual, exemplos XML, XSD v1.01, Anexo B e Anexo VIII. Os quatro schemas
necessários para DPS foram preservados em `apps/fiscal/xml/schemas/el/`.

O manual exige token de integração do contribuinte no parâmetro `token`, XML
assinado e JSON com `dpsXmlGZipB64`. O código municipal deve ser enviado em
`infDPS/serv/cServ/cIntContrib`, conforme o cadastro da prefeitura. Não se deve
deduzir esse código por concatenação da LC 116 ou substituir por `cTribMun`.

HTTP 201 indica recebimento municipal. O processamento nacional é assíncrono e
precisa ser consultado em `homologacao/nfseDps/<idDPS>`; não representa autorização
imediata. O cliente implementado diferencia rejeição, processamento, resultado
incerto e XML disponível para validação. Não há retransmissão automática.

## Dados e tabelas locais

- Inscrição municipal 16845 salva na empresa correspondente ao CNPJ informado.
- Tomador Kauã Santos Sacramento cadastrado com o CPF fornecido, validado pelos
  dígitos verificadores. Isso não é consulta de situação cadastral na Receita.
- Anexos do novo pacote importados: 918 NBS, 335 códigos nacionais de serviço,
  201 subitens da LC 116 e 896 correlações LC 116/NBS/IBS-CBS.
- O importador foi corrigido para não criar cTribNac a partir de linhas de grupos
  e subitens com desdobro 00. Linhas antigas de agrupamento permanecem preservadas
  no banco, mas foram excluídas das opções de catálogo e sugestões.
- Códigos nacionais ausentes da nova lista são preservados, marcados como não
  vigentes e impedidos de serem utilizados em novos rascunhos fiscais.
- A tela de tabelas fiscais pesquisa código/descrição nas três listas e pagina
  cada uma, em vez de mostrar somente as primeiras NBS e LC 116.
- Exemplo de classificação para **suporte em TI**, caso corresponda ao serviço
  realmente prestado: LC 116 01.07, nacional 010701, NBS 115013000.
  O código municipal correspondente ainda precisa ser confirmado no portal.

Não foi encontrada lista municipal no ZIP. Nenhum código municipal ou alíquota
foi inventado. O arquivo original e o manual estão em `.tools/layout-el-dps/`,
fora do Git.

## Testes e impedimentos concretos

A consulta GET ao novo endpoint de homologação, sem token e sem dados do tomador,
retornou HTTP 400 com corpo vazio. Isso não valida autenticação nem emissão.

O acesso via certificado no navegador retornou “Certificado digital não encontrado”.
O link gerado pelo portal de Valença também continha um retorno para Guaratinga/BA;
esse fluxo foi interrompido e nenhum certificado foi instalado ou enviado a esse destino.

Para transmitir a nota autorizada de R$ 1,00 em produção ainda faltam:

1. Token válido da integração do contribuinte de Valença/BA.
2. Código de serviço municipal autorizado para o prestador.
3. Serviço efetivamente prestado e parâmetros tributários da competência.
4. Teste autenticado de homologação e desenvolvimento/validação do envio de produção.

O certificado A1 sozinho não substitui o token exigido pela E&L. Configure o token
localmente como `KSCENTRAL_EL_TOKEN` no `.env` ignorado pelo Git, ou forneça-o ao
prompt oculto do comando abaixo. Não use argumento de linha de comando nem grave
o token em arquivos versionados.

```powershell
.\.venv\Scripts\python.exe manage.py consultar_dps_el ID_DPS --ambiente 2 --settings=config.settings.local
```

O código de envio municipal desta etapa aceita somente homologação, valor de
R$ 1,00, inscrição municipal e `cIntContrib`, assinatura válida e XSD municipal.
Consulta a DPS antes de transmitir. Não existe autorização de produção na interface
do cliente implementado. Nenhuma NFS-e foi emitida nesta etapa.

Validação local: 115 testes aprovados, Ruff e verificações Django sem erros,
migrações em dia. No navegador, a pesquisa “suporte” apresentou LC 116 01.07,
código nacional 010701 e NBS 115013000, com suas descrições oficiais.
