# Emissão real em produção — 09/10/2026

A operação de R$ 1,00 autorizada pelo usuário foi emitida pelo motor municipal
E&L de Valença/BA. A consulta nacional por chave também retornou HTTP 200 e o
mesmo XML. Houve uma única nota emitida.

| Campo | Resultado |
|---|---|
| Número NFS-e | 2600000000012 |
| Chave de acesso | [preservada no banco e nos arquivos locais; omitida do Git] |
| DPS | DPS293290326250128100011300001020261009000001 |
| Emitente | KS TEC SOLUÇÕES DE TECNOLOGIA LTDA, CNPJ 62.501.281/0001-13, IM 16845 |
| Serviço | Desenvolvimento de sistema sob medida |
| LC 116 / nacional / municipal / NBS | 01.01 / 010101 / 101 / 115022000 |
| Valor / ISS / tributos totais aproximados | R$ 1,00 / 2% / 6% |
| Competência | 09/10/2026 |
| Ambiente / cStat | Produção (1) / 100 |

Os percentuais de 2% e 6% foram informados pelo usuário nesta conversa. Os 6%
não foram extraídos da tabela IBPT ou de uma apuração PGDAS-D. O cadastro local
do Simples foi utilizado na declaração; o aceite não substitui a conferência
contábil desses dados. O tomador é o cliente Kauã cadastrado localmente.

## Resultado dos canais

1. SEFIN nacional: POST de DPS válida retornou HTTP 400 / E0039. Valença não
   está parametrizada para usar os emissores públicos nacionais. Não gerou nota.
2. Municipal E&L: ausência da DPS confirmada, POST único retornou HTTP 201 e
   processamento assíncrono. Consulta posterior retornou XML e chave.
3. SEFIN nacional: GET `/nfse/{chaveAcesso}` retornou HTTP 200, ambiente 1 e
   XML idêntico ao obtido no canal municipal. Isso confirma a disponibilidade
   da nota nacionalmente, sem habilitar emissão direta pelo emissor público.

## Conferência e artefatos

XML validado contra XSD municipal e oficial de produção, com a adaptação do
padrão de série documentada em `apps/fiscal/xml/schemas/producao/README.md`.
A DPS incorporada tem todos os dados iguais aos da DPS enviada, ambiente 1
e valor R$ 1,00. A assinatura da NFS-e foi verificada criptograficamente com
o certificado de `MUNICIPIO DE VALENCA:14235899000136`, dentro da validade.
O retorno municipal usa RSA-SHA1/SHA1; foi habilitado apenas na verificação
desse documento recebido. As DPS do sistema continuam assinadas com SHA-256.

O Windows encontrou a cadeia ICP-Brasil do autorizador. A verificação completa
de revogação retornou `CRYPT_E_REVOCATION_OFFLINE`; não foi considerada
concluída. A verificação criptográfica de assinatura e digest passou.

O serviço oficial DANFSe retornou HTTP 503, inclusive para o download por
chave naquela tentativa. Posteriormente foi implementada geração local do DANFSe
a partir do XML autorizado, conforme NT 008 v1.02; a API anterior foi suspensa
em 03/08/2026. O PDF está arquivado no sistema. Veja [pdf_e_entrega_nfse.md](pdf_e_entrega_nfse.md).

Evidências em `.tools/emissoes-producao/DPS293290326250128100011300001020261009000001/`:
`dps-assinada.xml`, `nfse.xml`, `resultado.json`, `validacao.json`,
`consulta-sefin.html` (resposta JSON), `danfse-http.json` e certificado público
do autorizador. Pasta ignorada pelo Git, sem senha, token ou chave privada.

## Uso local

`emitir_nfse_producao` prepara uma DPS do Simples com os parâmetros explícitos
`--numero`, `--canal nacional|municipal`, `--tomador`, `--item`,
`--codigo-municipal`, `--valor`, `--iss` e `--tributos-simples`.
Só transmite com `--enviar-producao`; A1 e token seguem os mecanismos locais.
O comando registra a tentativa antes do POST, não retransmite automaticamente
e impede outro canal se houver recebimento, timeout ou situação pendente.

Para acompanhar esta operação, use apenas a consulta:

```powershell
.venv/Scripts/python.exe manage.py consultar_dps_el DPS293290326250128100011300001020261009000001 --ambiente 1 --settings=config.settings.local
```

Não repita o comando de emissão desta nota. O registro local bloqueia repetição.
Os artefatos de integração ficam em disco. A nota foi importada para a tela Fiscal,
com XML, PDF, histórico, consulta e recebível pendente. A chave completa fica no
banco e nas evidências locais, sem exposição na documentação versionada.
