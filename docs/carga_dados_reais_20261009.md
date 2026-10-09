# Carga dos dados reais — 09/10/2026

Fonte: pasta `C:\Users\KS TEC\Documents\Documentos Fiscais - KS TEC` + distribuição nacional (ADN), consultada com o
A1 da empresa (somente GET). Backups prévios: `.tools/backups/antes-limpeza-dados-reais.sqlite3` e
`.tools/backups/media-antes-limpeza.tar.gz`. XMLs brutos baixados: `.tools/importacao-notas/` (fora do Git).

## 1. Limpeza

Removidos do banco local: os 2 tomadores de teste, a NFS-e de R$ 1,00 (nº 2600000000012) com tentativa, anexos e
recebível, o rascunho de R$ 1.000, 14 lançamentos e a recorrência "DEMO", a conta "DEMO", a tarefa/apontamento de
teste, o perfil "Simulação ISS 5%" e os respectivos históricos. **Preservados:** empresa, usuário, A1/token cifrados,
configuração fiscal, tabelas fiscais, catálogo e parâmetros. A sequência de DPS do sistema (`20261009000001`) foi
mantida. A nota de R$ 1,00 **continua válida na prefeitura/ADN**; cancelá-la, se desejado, é feito no portal E&L.

## 2. O que a pasta mostrava × o que vale

As NFS-e da pasta (`NFS-E 1`, `NFS-E 2`, `NFSe 4`, `NFSe 5`, `NFSe 6`) foram emitidas com **ISS 0% e "não retido"** e
estão **canceladas por substituição** (18–20/08/2026). As válidas são as substitutas **2600000000007 a 011**, com
**ISS 2% retido pelo tomador** (`tpRetISSQN=2`). A Transparência (nº 6 a 9) e o SIGAL de maio (nº 10) saíram pelo
**emissor nacional como MEI** (`opSimpNac=2`, `cStat=107`), antes da migração para ME/EPP.

| NFS-e | Contrato | Competência | Valor | ISS | Situação |
|---|---|---|---|---|---|
| 6 (nacional) | 072/2026 Transparência | 03/2026 | 3.850,00 | — (MEI) | válida |
| 7 (nacional) | 072/2026 Transparência | "01 de 12" (sem mês) | 3.850,00 | — (MEI) | válida — **possível duplicidade de março** |
| 8 (nacional) | 072/2026 Transparência | 04/2026 | 3.850,00 | — (MEI) | válida |
| 9 (nacional) | 072/2026 Transparência | 05/2026 | 3.850,00 | — (MEI) | válida |
| 10 (nacional) | 116/2026 SIGAL | 05/2026 | 4.950,00 | — (MEI) | válida |
| 2600000000007 | 116/2026 SIGAL | 06/2026 | 4.950,00 | 99,00 retido | válida (substitui 001) |
| 2600000000008 | 116/2026 SIGAL | 07/2026 | 4.950,00 | 99,00 retido | válida (substitui 002) |
| 2600000000009 | 136/2026 STaaS | 06/2026 | 2.150,00 | 43,00 retido | válida (substitui 004) |
| 2600000000010 | 022/2026 Fibromialgia | 06/2026 | 1.180,00 | 23,60 retido | válida (substitui 005) |
| 2600000000011 | 022/2026 Fibromialgia | 07/2026 | 1.180,00 | 23,60 retido | válida (substitui 006) |
| 2600000000003 | avulsa — Agrocampo (pessoa física) | 08/2026 | 350,00 | não retido | válida |

## 3. Cadastrado no sistema

- **Tomadores:** Município de Valença (CNPJ 14.235.899/0001-36, IM 0000005082, e-mail NF `nfe@valenca.ba.gov.br`) e
  FUMSAUDE (CNPJ 11.159.883/0001-01, IM 0014685); a pessoa física da nota avulsa veio do XML.
- **Contratos** (extratos anexados): 072/2026 Transparência (inexig. 020/2026, PA 051/2026, R$ 3.850/mês,
  vigência 25/02/2026–24/02/2027); 116/2026 SIGAL (inexig. 035/2026, PA 145/2026, R$ 4.950, 29/04/2026–28/04/2027);
  136/2026 STaaS (dispensa 020/2026, PA 159/2026, R$ 2.150, 27/05/2026–26/05/2027, exige relatório de SLA);
  022/2026 Fibromialgia/SIDEC — FUMSAUDE (dispensa 022/2026, PA 152/2026, R$ 1.180, 26/05/2026–25/05/2027).
- **Catálogo:** códigos municipais **105** (01.05) e **107** (01.07) confirmados pelas notas autorizadas; serviços
  TI-SIGAL (010501 · NBS 1.1103.21.00), TI-LIC (010501 · 1.1103.22.00 · Fibromialgia), TI-SUP (010701 · 1.1501.30.00 ·
  STaaS) e TI-TRANSP (170101 · 1.1501.10.00 · código municipal pendente).
- **Perfil padrão:** "KS TEC — ISS 2% retido pelo tomador". **Conta:** Banco do Brasil ag. 545-2 cc 74956-7.
- **NFS-e:** 11 válidas + 5 canceladas importadas com os valores do XML (`importar_nfse_adn`), PDFs municipais gerados.
- **Recebíveis:** 11 lançamentos (R$ 34.821,80 líquidos) como **pendentes** — a situação de pagamento não estava nos
  arquivos (a planilha HTML guarda as marcações só no navegador). Dê baixa nos já recebidos.
- **Agendas** (modo Confirmar, dia 5, prazo 30 dias, mês anterior) com ciclos: emitidos vinculados às notas; demais
  programados com o texto padrão de cada contrato ("{mes_nome} - {parcela2} de {total_parcelas}", "{parcela}º mês").
- **Certidões** (PDF anexado): Federal (positiva c/ efeito de negativa) e Trabalhista até 12/01/2027 — válidas;
  FGTS (até 04/09/2026), Municipal (30 dias de 11/08) e Estadual (estimada 14/09) — **vencidas, renovar**.

## 4. Competências pendentes de emissão (até setembro/2026)

Regra das suas notas: o 1º mês de execução é o mês seguinte à assinatura/publicação.

| Contrato | Última nota válida | Pendentes | Qtde | Bruto | Líquido (ISS 2% retido) |
|---|---|---|---|---|---|
| 072/2026 Transparência | maio/2026 (nº 9) | jun, jul, ago, set | 4 | 15.400,00 | 15.092,00 |
| 116/2026 SIGAL | julho/2026 (nº …008) | ago, set | 2 | 9.900,00 | 9.702,00 |
| 136/2026 STaaS | junho/2026 (nº …009) | jul, ago, set | 3 | 6.450,00 | 6.321,00 |
| 022/2026 Fibromialgia | julho/2026 (nº …011) | ago, set | 2 | 2.360,00 | 2.312,80 |
| **Total** | | | **11** | **34.110,00** | **33.427,80** |

Outubro/2026 fecha em 31/10 (emissão programada para 05/11): mais 4 notas, R$ 12.130,00.

## 5. Antes de emitir pelo KS CENTRAL

1. **ISS retido (tarefa futura, bloqueante):** o adaptador atual só transmite "não retido" e bloqueia perfis com
   retenção — de propósito, para não repetir o erro das notas canceladas. Os ciclos vão gerar rascunhos com os valores
   certos (ISS 2%, líquido 98%) mas ficarão **Bloqueados** até implementar `tpRetISSQN=2` (e `regApTribSN` conforme as
   notas 007–011) com testes. Até lá, emita pelo portal E&L e sincronize com `importar_nfse_adn`.
2. **Percentuais por competência:** a configuração fiscal vale só para 01–31/10/2026; competências de junho a setembro
   precisam de vigência/percentuais confirmados pelo contador.
3. **Transparência:** confirmar o código municipal para o item 17.01 (ou o serviço que será usado no E&L) e se a NFS-e
   nacional nº 7 ("01 de 12") duplicou março.
4. **Fibromialgia:** as notas citam "(Contrato 116/2026)", número do SIGAL; o resumo usa 022/2026 (nº da dispensa).
   O texto da agenda manteve a redação emitida — confirme o número correto e ajuste.
5. **SDL Advocacia** (R$ 5.000/mês desde junho, na planilha HTML): nenhum documento ou NFS-e encontrado; não cadastrado.
6. DANFSe das notas MEI do emissor nacional (`cStat 107`) ainda não é gerado pelo sistema (XML oficial anexado).

Sincronizar notas emitidas fora do sistema:
`.venv\Scripts\python.exe manage.py importar_nfse_adn --settings=config.settings.local` (continua do último NSU).
