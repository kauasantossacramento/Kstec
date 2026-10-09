"""Relatório mensal de SLA por contrato: disponibilidade, tempo de resposta e incidentes de cada sistema."""

from calendar import monthrange
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Avg, Count, Max, Q
from django.utils import timezone

from apps.core.models import Anexo
from apps.core.pdf import renderizar_pdf

from ..models import Incidente, RelatorioSLA


def periodo(competencia):
    inicio = timezone.make_aware(datetime.combine(competencia.replace(day=1), time.min))
    ultimo = competencia.replace(day=monthrange(competencia.year, competencia.month)[1])
    return inicio, timezone.make_aware(datetime.combine(ultimo, time.max))


def minutos(delta):
    return round(delta.total_seconds() / 60)


def apurar(contrato, competencia):
    inicio, fim = periodo(competencia)
    sistemas = []
    for s in contrato.sistemas.filter(ativo=True).order_by("nome"):
        v = s.verificacoes.filter(em__range=(inicio, fim)).aggregate(
            total=Count("pk"), ok=Count("pk", filter=Q(sucesso=True)), medio=Avg("tempo_ms", filter=Q(sucesso=True)),
            pico=Max("tempo_ms"))
        incidentes = []
        indisponivel = timedelta()
        for inc in Incidente.objects.filter(sistema=s, inicio__lte=fim).filter(Q(fim__isnull=True) | Q(fim__gte=inicio)):
            ini, fi = max(inc.inicio, inicio), min(inc.fim or timezone.now(), fim)
            if fi > ini:
                indisponivel += fi - ini
            incidentes.append({"inicio": timezone.localtime(inc.inicio).strftime("%d/%m %H:%M"),
                               "fim": timezone.localtime(inc.fim).strftime("%d/%m %H:%M") if inc.fim else "em andamento",
                               "minutos": minutos((inc.fim or timezone.now()) - inc.inicio), "causa": inc.causa})
        uptime = round(100 * v["ok"] / v["total"], 3) if v["total"] else None
        sistemas.append({"nome": s.nome, "url": s.url, "meta": str(s.meta_sla), "verificacoes": v["total"],
                         "falhas": v["total"] - v["ok"], "uptime": uptime,
                         "atingiu": uptime is not None and Decimal(str(uptime)) >= s.meta_sla,
                         "tempo_medio_ms": int(v["medio"]) if v["medio"] else None, "pico_ms": v["pico"],
                         "indisponivel_min": minutos(indisponivel), "incidentes": incidentes})
    medidos = [x["uptime"] for x in sistemas if x["uptime"] is not None]
    return {"competencia": competencia.isoformat(), "gerado_em": timezone.now().isoformat(timespec="seconds"),
            "sistemas": sistemas, "uptime_geral": round(sum(medidos) / len(medidos), 3) if medidos else None,
            "sem_dados": not medidos}


@transaction.atomic
def novo(contrato, competencia):
    competencia = competencia.replace(day=1)
    if competencia > timezone.localdate():
        raise ValidationError("Competência futura.")
    if not contrato.sistemas.filter(ativo=True).exists():
        raise ValidationError("Vincule ao menos um sistema monitorado a este contrato (Monitoramento → Sistema).")
    ultimo = RelatorioSLA.objects.filter(contrato=contrato, competencia=competencia).order_by("-versao").first()
    return RelatorioSLA.objects.create(empresa=contrato.empresa, contrato=contrato, competencia=competencia,
                                       versao=(ultimo.versao + 1) if ultimo else 1, dados=apurar(contrato, competencia),
                                       observacoes=ultimo.observacoes if ultimo else "")


@transaction.atomic
def aprovar(relatorio, usuario, observacoes=""):
    atual = RelatorioSLA.objects.select_for_update().get(pk=relatorio.pk)
    if atual.status == "APROVADO":
        raise ValidationError("Este relatório já foi aprovado. Gere uma nova versão para alterar.")
    atual.observacoes = observacoes
    atual.dados = apurar(atual.contrato, atual.competencia)
    atual.status, atual.aprovado_por, atual.aprovado_em = "APROVADO", usuario, timezone.now()
    pdf = renderizar_pdf("pdf/relatorio_sla.html", {"relatorio": atual, "dados": atual.dados, "empresa": atual.empresa})
    atual.pdf = Anexo.criar(atual, f"sla_{atual.contrato.numero.replace('/', '-')}_{atual.competencia:%Y%m}_v{atual.versao}.pdf",
                            pdf, descricao="Relatório de SLA aprovado", retencao_anos=5)
    atual.save()
    return atual


def aprovado(contrato, competencia):
    return RelatorioSLA.objects.filter(contrato=contrato, competencia=competencia.replace(day=1),
                                       status="APROVADO").order_by("-versao").first()
