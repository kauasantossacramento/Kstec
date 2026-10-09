# Diagnóstico de emissão NFS-e — 08/10/2026 (Bahia)

Atualização posterior: inscrição municipal e tomador cadastrados; novo endpoint
municipal DPS e seu requisito de token identificados. O diagnóstico abaixo
preserva os testes anteriores ao fornecimento desses dados. Veja
[integração municipal DPS](integracao_el_dps.md) para a situação atual.

Nenhuma NFS-e foi autorizada nestes testes. Houve envio real de DPS de R$ 1,00
à produção restrita nacional e consulta SOAP no serviço municipal de produção.
Não houve envio de emissão nem cancelamento em produção.

## Certificado

O A1 da empresa foi aberto com sucesso, com chave correspondente, CNPJ do prestador,
uso de autenticação cliente e validade entre 17/08/2026 e 17/08/2027.
Os serviços nacionais de documentação responderam HTTP 200 usando autenticação mTLS.
Isso valida conexão autenticada, não autorização para emitir.

O PFX permanece fora do Git. A senha não foi gravada em configuração ou banco.
A chave utilizada pelo TLS é temporária, cifrada e removida após carregar o contexto.
Não foi realizada consulta de revogação OCSP/CRL do certificado.

## Nacional

- Primeiro envio: HTTP 400, E1228 (prefixo de namespace no XML).
- Após corrigir namespaces e verificar assinatura e XSD: HTTP 400, E0037
  (município emissor inexistente no cadastro de convênio nacional).
- DPS corrigida: `DPS293290326250128100011389999020261009021101`.
- Consulta de convênio de Valença/BA, IBGE 2932903, em produção restrita:
  HTTP 404, convênio ainda não ativo.
- Consulta de convênio em produção: HTTP 200,
  `aderenteAmbienteNacional=1`, `aderenteEmissorNacional=0` e
  `situacaoEmissaoPadraoContribuintesRFB=0`.

Esses parâmetros não sustentam a premissa do plano de que a emissão comum de
Valença/BA já funciona exclusivamente pelo Emissor Nacional. A adesão ao ambiente
e a habilitação do emissor são parâmetros distintos. O canal municipal precisa
ser validado antes de definir o roteamento; não foi tentada emissão nacional em produção.

O teste usa explicitamente dados tributários sintéticos e descrição de homologação,
sem alterar o perfil fiscal cadastrado. Ele não representa uma operação real.
O schema de produção restrita usado é o oficial v1.01, pacote de 27/07/2026;
os schemas de produção têm publicação própria e não foram intercambiados.

## Municipal

WSDL oficial acessível em
[serviço municipal E&L](https://ba-valenca-pm-nfs-backend.cloud.el.com.br/producao/NfseWSService?wsdl),
HTTP 200, com operações de consulta, geração, recepção e cancelamento.
A consulta `ConsultarNfsePorRps` também retornou HTTP 200, porém com
`ConsultarNfsePorRpsResponse` vazio, sem XML de resultado nem erro de negócio.
Portanto, somente o acesso ao endpoint está confirmado: a consulta e a emissão
municipal continuam sem validação funcional.

O cadastro local não contém inscrição municipal. Para avançar com a emissão
autorizada de R$ 1,00 em produção, faltam inscrição municipal, tomador real
(CPF/CNPJ e nome), serviço efetivamente prestado e enquadramento/alíquota aplicáveis
à competência. É necessário confirmar também o layout municipal vigente de 2026,
pois o pacote legado ABRASF 2.04 existente não comprova compatibilidade atual.
O código atual municipal só consulta RPS; não há adaptador de emissão municipal pronto.

## Reprodução local

Os comandos solicitam a senha de forma interativa, sem gravá-la:

```powershell
.\.venv\Scripts\python.exe manage.py diagnosticar_nfse "CAMINHO_DO_A1.pfx" --settings=config.settings.local
.\.venv\Scripts\python.exe manage.py testar_emissao_nfse "CAMINHO_DO_A1.pfx" --settings=config.settings.local
# Envio real apenas à produção restrita:
.\.venv\Scripts\python.exe manage.py testar_emissao_nfse "CAMINHO_DO_A1.pfx" --enviar-homologacao --settings=config.settings.local
.\.venv\Scripts\python.exe manage.py consultar_rps_municipal "CAMINHO_DO_A1.pfx" NUMERO SERIE --settings=config.settings.local
```

Evidências locais, fora do Git:

- `.tools/diagnostico-nfse.json`: certificado público, endpoints e parâmetros.
- `.tools/emissoes-homologacao/<id>/`: DPS assinada e resposta de cada envio.
- `.tools/consulta-municipal/`: requisição e resposta SOAP da última consulta.

O cliente nacional bloqueia produção e valores diferentes de R$ 1,00, consulta a
DPS antes de transmitir e registra resposta incerta sem retransmissão automática.
Testes automatizados usam certificado sintético e HTTP simulado, sem chamadas fiscais reais.

Validação do código: 111 testes aprovados com `config.settings.test_local`, Ruff
sem erros, `manage.py check` sem problemas e nenhuma migração pendente. Os seis
testes novos cobrem A1, assinatura/adulteração, bloqueio de produção/valor, retorno
municipal vazio, consulta somente de leitura e ausência de retransmissão automática.

Referências: [APIs oficiais](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/apis-prod-restrita-e-producao),
[documentação de produção restrita](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/producao-restrita)
e [orientação E&L para 2026](https://www.el.com.br/wp-content/uploads/2025/12/EL_TRB_POP_nova_legislacao_e_obrigacoes_dos_municipios1.pdf).
