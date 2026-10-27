"""Relatório mensal de SLA por contrato: disponibilidade, tempo de resposta e incidentes de cada sistema."""

from calendar import monthrange
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Avg, Count, Max, Min, Q
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


def duracao(segundos):
    segundos = int(segundos or 0)
    if not segundos:
        return "0 min"
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    return " ".join(p for p in (f"{h} h" if h else "", f"{m} min" if m else "", f"{s} s" if s else "") if p)


def medicao_manual(s, m):
    """Linha do relatório a partir da medição informada manualmente (ex.: painel do UptimeRobot)."""
    uptime = float(m["uptime"])
    return {"nome": s.nome, "url": s.url, "meta": str(s.meta_sla), "origem": "manual", "verificacoes": None, "falhas": None,
            "uptime": uptime, "atingiu": Decimal(str(uptime)) >= s.meta_sla,
            "tempo_medio_ms": m.get("tempo_medio_ms"), "tempo_min_ms": m.get("tempo_min_ms"), "pico_ms": m.get("tempo_max_ms"),
            "indisponivel_min": round(int(m.get("indisponivel_seg") or 0) / 60), "indisponivel_txt": duracao(m.get("indisponivel_seg")),
            "incidentes_qtd": int(m.get("incidentes") or 0), "incidentes": [],
            "periodo": f"{m['periodo_inicio'][8:10]}/{m['periodo_inicio'][5:7]}/{m['periodo_inicio'][:4]} a "
                       f"{m['periodo_fim'][8:10]}/{m['periodo_fim'][5:7]}/{m['periodo_fim'][:4]}",
            "fonte": m.get("fonte") or "UptimeRobot", "intervalo_min": m.get("intervalo_min"), "referencia": m.get("referencia", "")}


def medicao_uptimerobot(s, inicio, fim, medir=None):
    """Linha do relatório a partir do UptimeRobot (disponibilidade e quedas) + tempos de resposta do monitor local."""
    from .uptimerobot import medir as medir_padrao

    m = (medir or medir_padrao)(s, inicio, fim)
    if m is None:
        return None
    tempos = s.verificacoes.filter(em__range=(m["inicio"], m["fim"]), sucesso=True).aggregate(
        medio=Avg("tempo_ms"), minimo=Min("tempo_ms"), pico=Max("tempo_ms"))
    ini, fi = timezone.localtime(m["inicio"]), timezone.localtime(m["fim"])
    return {"nome": s.nome, "url": s.url, "meta": str(s.meta_sla), "origem": "uptimerobot", "verificacoes": None, "falhas": None,
            "uptime": m["uptime"], "atingiu": Decimal(str(m["uptime"])) >= s.meta_sla,
            "tempo_medio_ms": int(tempos["medio"]) if tempos["medio"] else None, "tempo_min_ms": tempos["minimo"],
            "pico_ms": tempos["pico"], "indisponivel_min": round(m["indisponivel_seg"] / 60),
            "indisponivel_txt": duracao(m["indisponivel_seg"]), "incidentes_qtd": len(m["incidentes"]),
            "incidentes": m["incidentes"], "periodo": f"{ini:%d/%m/%Y} a {fi:%d/%m/%Y}", "fonte": "UptimeRobot",
            "intervalo_min": m["intervalo_min"]}


def apurar(contrato, competencia, manuais=None, medir=None):
    """Por sistema, nesta ordem: medição manual informada; UptimeRobot (referência externa); monitor do KS CENTRAL.
    Sistemas sem nenhum dado são omitidos se outro sistema do contrato tiver medição."""
    manuais = manuais or {}
    inicio, fim = periodo(competencia)
    sistemas, omitidos = [], []
    for s in contrato.sistemas.filter(ativo=True).order_by("nome"):
        if str(s.pk) in manuais:
            sistemas.append(medicao_manual(s, manuais[str(s.pk)]))
            continue
        externa = medicao_uptimerobot(s, inicio, fim, medir) if s.uptimerobot_id else None
        if externa:
            sistemas.append(externa)
            continue
        v = s.verificacoes.filter(em__range=(inicio, fim), desconsiderada=False).aggregate(
            total=Count("pk"), ok=Count("pk", filter=Q(sucesso=True)), medio=Avg("tempo_ms", filter=Q(sucesso=True)),
            pico=Max("tempo_ms"))
        incidentes = []
        indisponivel = timedelta()
        for inc in Incidente.objects.filter(sistema=s, inicio__lte=fim).exclude(status=Incidente.Status.DESCARTADO) \
                .filter(Q(fim__isnull=True) | Q(fim__gte=inicio)):
            ini, fi = max(inc.inicio, inicio), min(inc.fim or timezone.now(), fim)
            if fi > ini:
                indisponivel += fi - ini
            incidentes.append({"inicio": timezone.localtime(inc.inicio).strftime("%d/%m %H:%M"),
                               "fim": timezone.localtime(inc.fim).strftime("%d/%m %H:%M") if inc.fim else "em andamento",
                               "minutos": minutos((inc.fim or timezone.now()) - inc.inicio), "causa": inc.causa})
        uptime = round(100 * v["ok"] / v["total"], 3) if v["total"] else None
        sistemas.append({"nome": s.nome, "url": s.url, "meta": str(s.meta_sla), "origem": "automatica",
                         "periodo": f"{inicio:%d/%m/%Y} a {fim:%d/%m/%Y}", "fonte": "Monitoramento KS CENTRAL",
                         "incidentes_qtd": len(incidentes), "indisponivel_txt": duracao(indisponivel.total_seconds()),
                         "verificacoes": v["total"],
                         "falhas": v["total"] - v["ok"], "uptime": uptime,
                         "atingiu": uptime is not None and Decimal(str(uptime)) >= s.meta_sla,
                         "tempo_medio_ms": int(v["medio"]) if v["medio"] else None, "pico_ms": v["pico"],
                         "indisponivel_min": minutos(indisponivel), "incidentes": incidentes})
    medidos = [x["uptime"] for x in sistemas if x["uptime"] is not None]
    if medidos:
        omitidos = [x["nome"] for x in sistemas if x["uptime"] is None]
        sistemas = [x for x in sistemas if x["uptime"] is not None]
    return {"competencia": competencia.isoformat(), "gerado_em": timezone.now().isoformat(timespec="seconds"),
            "sistemas": sistemas, "uptime_geral": round(sum(medidos) / len(medidos), 3) if medidos else None,
            "sem_dados": not medidos, "omitidos": omitidos, "manuais": manuais,
            "tem_manual": any(x.get("origem") == "manual" for x in sistemas),
            "tem_uptimerobot": any(x.get("origem") == "uptimerobot" for x in sistemas)}


@transaction.atomic
def registrar_manual(relatorio, sistema, dados):
    """Grava (ou remove, com dados=None) a medição manual de um sistema no rascunho e reapura o relatório."""
    atual = RelatorioSLA.objects.select_for_update().get(pk=relatorio.pk)
    if atual.status != "RASCUNHO":
        raise ValidationError("Relatório aprovado é imutável. Gere uma nova versão para informar medições.")
    if sistema.contrato_id != atual.contrato_id:
        raise ValidationError("O sistema não pertence ao contrato do relatório.")
    manuais = dict(atual.dados.get("manuais") or {})
    if dados is None:
        manuais.pop(str(sistema.pk), None)
    else:
        if not Decimal(0) <= Decimal(str(dados["uptime"])) <= Decimal(100):
            raise ValidationError("A disponibilidade deve estar entre 0 e 100%.")
        if dados["periodo_fim"] < dados["periodo_inicio"]:
            raise ValidationError("O fim do período apurado deve ser igual ou posterior ao início.")
        manuais[str(sistema.pk)] = {k: (v.isoformat() if hasattr(v, "isoformat") else (str(v) if isinstance(v, Decimal) else v))
                                    for k, v in dados.items() if v not in (None, "")}
    atual.dados = apurar(atual.contrato, atual.competencia, manuais)
    atual.save()
    return atual


@transaction.atomic
def novo(contrato, competencia):
    competencia = competencia.replace(day=1)
    if competencia > timezone.localdate():
        raise ValidationError("Competência futura.")
    if not contrato.sistemas.filter(ativo=True).exists():
        raise ValidationError("Vincule ao menos um sistema monitorado a este contrato (Monitoramento → Sistema).")
    ultimo = RelatorioSLA.objects.filter(contrato=contrato, competencia=competencia).order_by("-versao").first()
    manuais = (ultimo.dados.get("manuais") if ultimo else None) or {}
    return RelatorioSLA.objects.create(empresa=contrato.empresa, contrato=contrato, competencia=competencia,
                                       versao=(ultimo.versao + 1) if ultimo else 1, dados=apurar(contrato, competencia, manuais),
                                       observacoes=ultimo.observacoes if ultimo else "")


@transaction.atomic
def aprovar(relatorio, usuario, observacoes=""):
    atual = RelatorioSLA.objects.select_for_update().get(pk=relatorio.pk)
    if atual.status == "APROVADO":
        raise ValidationError("Este relatório já foi aprovado. Gere uma nova versão para alterar.")
    atual.observacoes = observacoes
    atual.dados = apurar(atual.contrato, atual.competencia, atual.dados.get("manuais"))
    atual.status, atual.aprovado_por, atual.aprovado_em = "APROVADO", usuario, timezone.now()
    from apps.core.services.assinatura import assinar_se_possivel, titular_padrao

    pdf = renderizar_pdf("pdf/relatorio_sla.html", {"relatorio": atual, "dados": atual.dados, "empresa": atual.empresa,
                                                     "assinatura_digital": titular_padrao(atual.empresa)})
    pdf, titular = assinar_se_possivel(pdf, atual.empresa, f"Relatório de SLA {atual.competencia:%m/%Y} aprovado")
    atual.pdf = Anexo.criar(atual, f"sla_{atual.contrato.numero.replace('/', '-')}_{atual.competencia:%Y%m}_v{atual.versao}.pdf",
                            pdf, descricao=f"Relatório de SLA aprovado · assinado por {titular}" if titular else
                            "Relatório de SLA aprovado", retencao_anos=5)
    atual.save()
    return atual


def aprovado(contrato, competencia):
    return RelatorioSLA.objects.filter(contrato=contrato, competencia=competencia.replace(day=1),
                                       status="APROVADO").order_by("-versao").first()
