"""Regras de negócio de contratos: competências, indicadores e alertas (Fase 2)."""

from datetime import date
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from apps.core.models import Parametro
from apps.core.services.notificacoes import notificar_papeis

from .models import Competencia, Contrato, primeiro_dia, somar_meses


def gerar_competencias(contrato: Contrato, ate: date | None = None) -> int:
    """Cria as competências mensais da vigência (inclusive aditivos de prazo). Idempotente."""
    if contrato.forma_faturamento != Contrato.Faturamento.MENSAL:
        return 0
    fim = contrato.vigencia_fim_atual
    if ate:
        fim = min(fim, ate)
    atual = primeiro_dia(contrato.vigencia_inicio)
    existentes = set(contrato.competencias.values_list("ano_mes", flat=True))
    criadas = 0
    while atual <= fim:
        if atual not in existentes:
            Competencia.objects.create(contrato=contrato, ano_mes=atual, empresa=contrato.empresa)
            criadas += 1
        atual = somar_meses(atual, 1)
    return criadas


def gerar_competencias_vigentes(empresa=None) -> int:
    qs = Contrato.objects.filter(status=Contrato.Status.VIGENTE)
    if empresa:
        qs = qs.filter(empresa=empresa)
    return sum(gerar_competencias(c) for c in qs)


def alterar_situacao(contrato: Contrato, status: str, motivo: str, usuario=None) -> Contrato:
    """Inativa (encerrado/suspenso/rescindido) ou reativa o contrato. Inativo: faturamento recorrente pausado,
    fora das contagens, previsões e alertas; notas e recebíveis já emitidos permanecem."""
    from django.core.exceptions import ValidationError

    if status not in Contrato.Status.values or status == Contrato.Status.RASCUNHO:
        raise ValidationError("Situação inválida.")
    if status != Contrato.Status.VIGENTE and not motivo.strip():
        raise ValidationError("Informe o motivo da inativação.")
    contrato.status = status
    contrato.motivo_situacao = (motivo.strip() or "Reativado")[:300]
    contrato.save()
    agenda = getattr(contrato, "agenda_faturamento", None)
    if agenda is not None:
        agenda.ativo = status == Contrato.Status.VIGENTE
        if agenda.ativo:
            agenda.ativa_desde = max(agenda.ativa_desde, timezone.localdate())
        agenda.save()
    return contrato


def alertas_contrato(contrato: Contrato) -> list[dict]:
    """Avisos de vigência (90/60/30 dias) e saldo abaixo do limite (seção 2.2, item 5)."""
    alertas = []
    dias = contrato.dias_para_fim
    limites = sorted(Parametro.get("contratos.dias_alerta_vigencia", [90, 60, 30], empresa=contrato.empresa))
    if contrato.status == Contrato.Status.VIGENTE:
        if dias < 0:
            alertas.append({"nivel": "danger", "texto": f"Vigência encerrada há {-dias} dias.", "chave": "vencido"})
        else:
            for lim in limites:
                if dias <= lim:
                    alertas.append({"nivel": "danger" if lim <= 30 else "warning",
                                    "texto": f"Vigência termina em {dias} dias ({contrato.vigencia_fim_atual:%d/%m/%Y}).",
                                    "chave": f"vig{lim}"})
                    break
        pct_limite = Decimal(str(Parametro.get("contratos.percentual_alerta_saldo", 20, empresa=contrato.empresa)))
        if contrato.valor_atualizado and contrato.percentual_saldo < pct_limite:
            alertas.append({"nivel": "warning",
                            "texto": f"Saldo contratual abaixo de {pct_limite}% ({contrato.percentual_saldo}%).",
                            "chave": "saldo"})
    return alertas


def alertar_vigencia_saldo() -> int:
    enviados = 0
    for c in Contrato.objects.filter(status=Contrato.Status.VIGENTE).select_related("cliente"):
        for a in alertas_contrato(c):
            n = notificar_papeis(
                ["Administrador", "Financeiro"], f"Contrato {c.numero}: {a['texto']}",
                f"{c.cliente} — {c.objeto[:200]}", nivel=a["nivel"],
                link=reverse("contratos:contrato_detalhe", args=[c.pk]), email=True,
                chave_dedup=f"contrato-{c.pk}-{a['chave']}", janela_dedup_horas=24 * 25, empresa=c.empresa,
            )
            enviados += len(n)
    return enviados


def competencia_atual() -> date:
    return primeiro_dia(timezone.localdate())
