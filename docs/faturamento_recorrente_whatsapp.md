# Faturamento recorrente, recebimentos, Asaas, WhatsApp e monitoramento

Guia de uso e de funcionamento interno dos módulos entregues em 09/10/2026.

## 1. Faturamento recorrente de NFS-e (`apps/faturamento`)

**Onde:** menu **Faturamento** · aba **Faturamento** do contrato · botão **Novo → Faturamento recorrente**.

### Conceitos

| Objeto | O que é |
|---|---|
| `AgendaFaturamento` | Regra mensal de um contrato (1 por contrato): serviço, valor, texto, dia/hora, competência faturada, vencimento e modo. |
| `CicloFaturamento` | Uma competência programada. Restrição única `(agenda, competência)`: no máximo **uma nota por mês**. |
| `AjustePrevisao` | Muda só a **previsão** de recebimento de um contrato em um mês (data, valor ou exclusão). |

Modos: **Rascunho** (prepara e avisa) · **Confirmar** (recomendado: valida e pede SIM no app ou no WhatsApp) ·
**Automático** (transmite no horário; exige aceite explícito no wizard).

### Wizard (4 passos)
1. Contrato e serviço — ao escolher o contrato, valor, dia, prazo, início e texto são pré-preenchidos.
2. Valor e descrição — placeholders `{competencia}`, `{mes_extenso}`, `{contrato}`, `{empenho}`, `{objeto}`.
3. Calendário — mês anterior/mesmo mês, dia (ajuste para dia útil), horário, vencimento por prazo ou dia fixo.
4. Automação — modo, envio por WhatsApp, cobrança Asaas.

A prévia lateral (HTMX) mostra a regra em linguagem natural, as próximas 6 emissões e o texto da 1ª nota.

### Ciclo de vida
`PROGRAMADO → (RASCUNHO | AGUARDANDO | TRANSMITIDO) → AUTORIZADO`, com desvios `BLOQUEADO`, `FALHA`, `PULADO`.

Proteções:
- trava distribuída (Redis) + `select_for_update` por ciclo; chamadas externas fora de transação;
- `emissao.transmitir` continua impedindo segunda tentativa da mesma nota;
- resultado incerto → `TRANSMITIDO`, apenas **consultado** a cada 10 min (nunca reenviado); após 3 dias vira `FALHA`;
- vigência, status e **saldo contratual** conferidos a cada emissão; percentuais fiscais vencidos bloqueiam;
- emissões com mais de 20 dias de atraso não saem sozinhas (exigem "Emitir agora");
- ciclos anteriores à ativação (`ativa_desde`) não são criados.

Ações por ciclo: emitir agora, confirmar, ajustar só este mês, pular (com motivo), voltar à fila, refazer nota rejeitada
(a rejeitada permanece no histórico fiscal).

Após a autorização (`pos_autorizacao`): DANFSe PDF, cobrança Asaas (se marcada) e lote de WhatsApp ao cliente
(se marcado). Falhas nesses passos não afetam a nota.

### Agendamento (Celery beat)
| Tarefa | Quando |
|---|---|
| `faturamento.planejar_ciclos` | diária 00:40 (horizonte de 62 dias) |
| `faturamento.processar_ciclos` | a cada 15 min (respeita data e hora da agenda) |
| `faturamento.acompanhar_transmissoes` | a cada 10 min |

No perfil local (sem Redis) use **Faturamento → Executar rotina agora**.

## 2. Previsão de recebimentos

**Onde:** Faturamento → **Previsão de recebimentos** (calendário mensal, KPIs, gráfico acumulado).

Fontes sem duplicidade: Recebido (pagos no mês) · Lançado (receitas em aberto, incluindo notas avulsas) ·
Programado (ciclos sem recebível) · Estimado (competências futuras e contratos mensais sem agenda, por
`dia_faturamento` + `prazo_pagamento_dias`). Clique no dia para detalhes e em **ajustar** para mudar a previsão do
contrato naquele mês; o valor original aparece riscado.

## 3. Cobrança Asaas (`apps/cobranca`)

**Configurar:** Configurações → **Cobrança Asaas** (ambiente Sandbox/Produção, chave cifrada, forma padrão, multa,
juros, baixa automática e conta). Copie a **URL e o token do webhook** para Asaas → Integrações → Webhooks.

- Lançamento de receita → **Cobrança Asaas** cria/reaproveita a cobrança (link, boleto, PIX copia e cola e QR).
- Idempotência: `externalReference = lancamento:<id>` é consultada antes de criar (seguro contra timeout).
- Webhook `POST /cobrancas/webhook/` autenticado por `asaas-access-token` (tempo constante); eventos repetidos ignorados;
  pagamento confirmado → baixa do lançamento (se ativada) e aviso no app/WhatsApp.
- Por cliente: **Cadastros → cliente → Comunicação e cobrança**.

## 4. WhatsApp (`apps/mensageria`) — neonize

**Configurar:** Configurações → **WhatsApp**. Ative, escolha "WhatsApp Web (neonize)", informe **meus números**.
**Conectar:** rode o worker e leia o QR em **WhatsApp** (a tela atualiza sozinha).

Arquitetura: telas e tarefas apenas **enfileiram**; um único processo `manage.py whatsapp_worker` mantém a sessão,
envia e recebe. Sessão em `WHATSAPP_SESSAO` (fora do Git).

Medidas anti-bloqueio: consentimento registrado por contato (LGPD) · descadastro por **SAIR** · janela de horário e dias
úteis · limites por hora/dia · cota de contatos novos/dia · intervalos aleatórios e "digitando…" · verificação do
número no WhatsApp · textos variados · disjuntor (3 falhas → pausa de 30 min e aviso) · deduplicação.

Confirmações: envios a clientes podem ficar **retidos**; você recebe o resumo com destinatários, texto e os mesmos
arquivos (PDF/XML) e responde **SIM 1234 / NAO 1234** (ou usa a tela). Sem resposta no prazo: cancelar, enviar ou
continuar aguardando (configurável). Emissões no modo Confirmar também geram código SIM/NAO.

Automações: NFS-e autorizada ao cliente · lembretes antes/no dia/após o vencimento (por cliente) · avisos de faturamento
· quedas/retornos dos sistemas · resumo diário.

Comandos do administrador: `ajuda`, `status`, `financeiro`, `previsao`, `vencidos`, `faturamento`, `notas`, `nota 123`,
`relatorio` (XLSX), `pausar`, `retomar`, `sim/nao <código>`. Mensagens livres de clientes são encaminhadas a você.

> WhatsApp Web via neonize não é API oficial da Meta: use número dedicado, aqueça o chip e mantenha volume baixo.

## 5. Monitoramento (`apps/sla`)

**Onde:** menu **Monitoramento** e aba **Sistemas/SLA** do contrato. Verificação HTTP (método, status esperado, texto
esperado, tempo-limite, lento acima de X ms). N falhas seguidas → **Fora do ar**, incidente aberto e alerta; retorno
fecha o incidente e informa a duração. Modo manutenção suprime alertas. Verificação SSL diária e retenção de 90 dias.

## 6. Testes

`tests/test_faturamento_recorrente.py` (21), `tests/test_mensageria.py` (15), `tests/test_cobranca_sla.py` (9).
Asaas e HTTP usam `httpx.MockTransport`; WhatsApp usa `TransporteSimulado`. **Nenhuma nota, cobrança ou mensagem real
foi enviada durante o desenvolvimento.**
