"""Relatório versionado: fatos de tarefas, revisão humana e PDF aprovado."""
from calendar import monthrange
from datetime import datetime, time, timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from apps.contratos.models import Contrato
from apps.core.models import Anexo
from apps.core.pdf import renderizar_pdf
from apps.core.permissoes import exigir_escrita

from .models import RelatorioAtividades, Tarefa


@transaction.atomic
def novo_relatorio(contrato, competencia):
    contrato = Contrato.objects.select_for_update().get(pk=contrato.pk)
    inicio = competencia.replace(day=1)
    fim = inicio.replace(day=monthrange(inicio.year, inicio.month)[1])
    dt_inicio = timezone.make_aware(datetime.combine(inicio, time.min))
    dt_fim = timezone.make_aware(datetime.combine(fim + timedelta(days=1), time.min))
    tarefas = Tarefa.objects.filter(empresa=contrato.empresa, contrato=contrato, entrar_no_relatorio=True).exclude(status="CANCELADA")
    tarefas = tarefas.filter(Q(concluida_em__gte=dt_inicio, concluida_em__lt=dt_fim)
                            | Q(apontamentos__data__range=(inicio, fim))).distinct().order_by("titulo")
    linhas = []
    for t in tarefas:
        horas = sum((a.horas for a in t.apontamentos.filter(empresa=contrato.empresa, data__range=(inicio, fim))), 0)
        linhas.append({"id": str(t.pk), "titulo": t.titulo, "situacao": t.get_status_display(),
                       "resumo": t.resumo_para_relatorio, "horas": str(horas)})
    versao = (RelatorioAtividades.objects.filter(contrato=contrato, competencia=inicio).aggregate(v=Max("versao"))["v"] or 0) + 1
    conteudo = "\n\n".join(f"{linha['titulo']} — {linha['situacao']}\n{linha['resumo']}\nHoras registradas na competência: {linha['horas']} h." for linha in linhas)
    return RelatorioAtividades.objects.create(empresa=contrato.empresa, contrato=contrato, competencia=inicio,
                                               versao=versao, conteudo=conteudo, tarefas_snapshot=linhas)


@transaction.atomic
def salvar_relatorio(relatorio, dados, usuario, aprovar=False):
    exigir_escrita(usuario, ["Operação"])
    atual = RelatorioAtividades.objects.select_for_update().get(pk=relatorio.pk, empresa=usuario.empresa)
    if not usuario.tem_papel("Administrador") and not atual.contrato.responsaveis.filter(pk=usuario.pk).exists():
        raise PermissionDenied
    if atual.status != "RASCUNHO":
        raise ValidationError("O relatório aprovado está preservado. Crie uma nova versão para alterar.")
    for campo in ("introducao", "conteudo", "consideracoes_finais"):
        setattr(atual, campo, dados[campo])
    if not atual.conteudo.strip():
        raise ValidationError("Descreva as atividades reais da competência antes de aprovar.")
    if aprovar:
        atual.status, atual.aprovado_por, atual.aprovado_em = "APROVADO", usuario, timezone.now()
        pdf = renderizar_pdf("pdf/relatorio_atividades.html", {"relatorio": atual, "empresa": atual.empresa})
        atual.pdf = Anexo.criar(atual, f"atividades_{atual.competencia:%Y%m}_v{atual.versao}.pdf", pdf, retencao_anos=5)
    atual.full_clean()
    atual.save()
    return atual
