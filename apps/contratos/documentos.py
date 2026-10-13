"""Central de documentos dos contratos: relatórios de atividades, planilhas de custos, relatórios de SLA e
documentos enviados (PDFs assinados, extratos, ofícios), com filtro por contrato, tipo e competência."""

from dataclasses import dataclass
from datetime import date

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.views.decorators.http import require_POST

from apps.core.forms import FormSimples
from apps.core.models import Anexo
from apps.core.permissoes import exigir_escrita, pode_escrever

from .models import Contrato, DocumentoContrato
from .views import contratos_visiveis

LIMITE_ARQUIVO = 15_000_000


@dataclass
class Linha:
    tipo: str
    rotulo: str
    contrato: Contrato
    competencia: date | None
    titulo: str
    origem: str
    situacao: str
    cor: str
    anexo_id: object = None
    anexo_extra_id: object = None
    link: str = ""
    objeto_id: object = None
    previa: str = ""


class DocumentoForm(FormSimples):
    contrato = forms.ModelChoiceField(queryset=Contrato.objects.none())
    tipo = forms.ChoiceField(choices=DocumentoContrato.Tipo.choices)
    competencia = forms.DateField(label="competência", required=False, help_text="Qualquer dia do mês.")
    titulo = forms.CharField(label="título", max_length=200, required=False, help_text="Vazio usa o nome do arquivo.")
    assinado = forms.BooleanField(required=False, initial=True)
    arquivo = forms.FileField(help_text="PDF, XLSX, DOCX, ZIP ou imagem, até 15 MB.")
    observacao = forms.CharField(label="observação", max_length=300, required=False)

    def __init__(self, *args, contratos=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["contrato"].queryset = contratos

    def clean_arquivo(self):
        arquivo = self.cleaned_data["arquivo"]
        if arquivo.size > LIMITE_ARQUIVO:
            raise ValidationError("Arquivo acima de 15 MB.")
        if not arquivo.name.lower().endswith((".pdf", ".xlsx", ".xls", ".docx", ".zip", ".png", ".jpg", ".jpeg")):
            raise ValidationError("Formato não aceito.")
        return arquivo


def _mes(texto):
    try:
        return date.fromisoformat(f"{texto}-01") if texto else None
    except ValueError:
        return None


def linhas(request, contratos, tipo="", competencia=None):
    from apps.financeiro.models import PlanilhaCustos
    from apps.operacao.models import RelatorioAtividades
    from apps.sla.models import RelatorioSLA

    saida = []
    ver_custos = request.user.tem_papel("Administrador", "Fiscal", "Financeiro", "Leitura")
    filtro = {"contrato__in": contratos}
    if competencia:
        filtro["competencia"] = competencia
    if tipo in ("", "RELATORIO_ATIVIDADES"):
        for r in RelatorioAtividades.objects.filter(**filtro, ativo=True).select_related("contrato"):
            saida.append(Linha("RELATORIO_ATIVIDADES", "Relatório de atividades", r.contrato, r.competencia,
                               f"Relatório de atividades v{r.versao}", "Gerado no sistema", r.get_status_display(),
                               "success" if r.status == "APROVADO" else "neutral", r.pdf_id,
                               link=reverse("fiscal:documentos_contrato", args=[r.contrato_id]) + f"?competencia={r.competencia:%Y-%m-%d}",
                               previa=reverse("fiscal:previa", args=["relatorio", r.pk]) if not r.pdf_id else ""))
    if ver_custos and tipo in ("", "PLANILHA_CUSTOS"):
        for p in PlanilhaCustos.objects.filter(**filtro, ativo=True).select_related("contrato"):
            saida.append(Linha("PLANILHA_CUSTOS", "Planilha de custos", p.contrato, p.competencia, f"Planilha de custos v{p.versao}",
                               "Gerado no sistema", p.get_status_display(), "success" if p.status == "APROVADO" else "neutral",
                               p.pdf_id, p.xlsx_id,
                               link=reverse("fiscal:documentos_contrato", args=[p.contrato_id]) + f"?competencia={p.competencia:%Y-%m-%d}",
                               previa=reverse("fiscal:previa", args=["planilha", p.pk]) if not p.pdf_id else ""))
    if tipo in ("", "RELATORIO_SLA"):
        for s in RelatorioSLA.objects.filter(**filtro, ativo=True).select_related("contrato"):
            saida.append(Linha("RELATORIO_SLA", "Relatório de SLA", s.contrato, s.competencia, f"Relatório de SLA v{s.versao}",
                               "Gerado do monitoramento", s.get_status_display(),
                               "success" if s.status == "APROVADO" else "neutral", s.pdf_id,
                               link=reverse("relatorios:sla", args=[s.pk]), objeto_id=s.pk))
    docs = DocumentoContrato.objects.filter(contrato__in=contratos, ativo=True).select_related("contrato", "anexo")
    if tipo:
        docs = docs.filter(tipo=tipo)
    if competencia:
        docs = docs.filter(competencia=competencia)
    for d in docs:
        if d.tipo == "PLANILHA_CUSTOS" and not ver_custos:
            continue
        saida.append(Linha(d.tipo, d.get_tipo_display(), d.contrato, d.competencia, d.titulo,
                           "Enviado" + (" · assinado" if d.assinado else ""), "Arquivado", "info", d.anexo_id, objeto_id=d.pk))
    return sorted(saida, key=lambda x: (x.competencia or date.min, x.contrato.numero, x.tipo), reverse=True)


@login_required
def central(request):
    contratos = contratos_visiveis(request.user, Contrato.objects.filter(empresa=request.empresa)).select_related("cliente")
    contrato_sel = contratos.filter(pk=request.GET.get("contrato")).first() if request.GET.get("contrato") else None
    tipo = request.GET.get("tipo", "")
    competencia = _mes(request.GET.get("mes"))
    alvo = contratos.filter(pk=contrato_sel.pk) if contrato_sel else contratos
    form = DocumentoForm(contratos=contratos, initial={"contrato": contrato_sel, "competencia": competencia, "tipo": tipo or None})
    return render(request, "contratos/documentos_central.html", {
        "linhas": linhas(request, alvo, tipo, competencia), "contratos": contratos, "contrato_sel": contrato_sel,
        "tipo": tipo, "mes": request.GET.get("mes", ""), "tipos": DocumentoContrato.Tipo.choices, "form": form,
        "pode_enviar": pode_escrever(request.user, ["Fiscal", "Financeiro", "Operação"])})


@login_required
@require_POST
def enviar(request):
    exigir_escrita(request.user, ["Fiscal", "Financeiro", "Operação"])
    contratos = contratos_visiveis(request.user, Contrato.objects.filter(empresa=request.empresa))
    form = DocumentoForm(request.POST, request.FILES, contratos=contratos)
    if not form.is_valid():
        messages.error(request, "Documento não enviado: " + "; ".join(f"{form.fields[c].label or c}: {' '.join(e)}"
                                                                     for c, e in form.errors.items()))
        return redirect("relatorios:home")
    d = form.cleaned_data
    arquivo = d["arquivo"]
    anexo = Anexo.criar(d["contrato"], arquivo.name, arquivo.read(), descricao=d["titulo"] or arquivo.name, retencao_anos=5)
    DocumentoContrato.objects.create(empresa=request.empresa, contrato=d["contrato"], tipo=d["tipo"],
                                     competencia=d["competencia"], titulo=d["titulo"] or arquivo.name.rsplit(".", 1)[0],
                                     assinado=d["assinado"], anexo=anexo, observacao=d["observacao"])
    messages.success(request, "Documento arquivado no contrato.")
    return redirect(f"{reverse('relatorios:home')}?contrato={d['contrato'].pk}")


@login_required
@require_POST
def arquivar(request, pk):
    exigir_escrita(request.user, ["Fiscal", "Financeiro"])
    doc = get_object_or_404(DocumentoContrato, pk=pk, empresa=request.empresa)
    doc.ativo = False
    doc.save()
    messages.success(request, "Documento retirado da lista (o arquivo permanece guardado pela retenção legal).")
    return redirect("relatorios:home")


# ---------------------------------------------------------------------------
# Relatório de SLA
# ---------------------------------------------------------------------------

class MedicaoManualForm(FormSimples):
    """Medição de disponibilidade informada a partir de um monitor externo (ex.: UptimeRobot)."""
    periodo_inicio = forms.DateField(label="início do período apurado")
    periodo_fim = forms.DateField(label="fim do período apurado")
    uptime = forms.DecimalField(label="disponibilidade (%)", max_digits=7, decimal_places=3, min_value=0, max_value=100)
    incidentes = forms.IntegerField(label="incidentes", min_value=0, initial=0)
    indisponivel_seg = forms.IntegerField(label="tempo indisponível (segundos)", min_value=0, initial=0,
                                          help_text="Ex.: 10 min 11 s = 611.")
    tempo_medio_ms = forms.IntegerField(label="resposta média (ms)", min_value=0, required=False)
    tempo_min_ms = forms.IntegerField(label="resposta mínima (ms)", min_value=0, required=False)
    tempo_max_ms = forms.IntegerField(label="resposta máxima (ms)", min_value=0, required=False)
    intervalo_min = forms.IntegerField(label="intervalo de verificação (min)", min_value=1, initial=5, required=False)
    fonte = forms.CharField(label="fonte", max_length=60, initial="UptimeRobot")
    referencia = forms.CharField(label="referência / observação", max_length=300, required=False,
                                 help_text="Ex.: painel do monitor, intervalo “Últimos 30 dias” consultado em 13/10/2026.")

@login_required
@require_POST
def sla_gerar(request):
    exigir_escrita(request.user, ["Fiscal", "Financeiro", "Operação"])
    from apps.sla.services import relatorio as srv

    contrato = get_object_or_404(contratos_visiveis(request.user, Contrato.objects.filter(empresa=request.empresa)),
                                 pk=request.POST.get("contrato"))
    competencia = _mes(request.POST.get("mes"))
    if competencia is None:
        messages.error(request, "Informe a competência.")
        return redirect("relatorios:home")
    try:
        rel = srv.novo(contrato, competencia)
    except ValidationError as erro:
        messages.error(request, "; ".join(erro.messages))
        return redirect(f"{reverse('relatorios:home')}?contrato={contrato.pk}")
    return redirect("relatorios:sla", pk=rel.pk)


@login_required
def sla(request, pk):
    from apps.sla.models import RelatorioSLA
    from apps.sla.services import relatorio as srv

    rel = get_object_or_404(RelatorioSLA.objects.select_related("contrato__cliente", "pdf"), pk=pk, empresa=request.empresa)
    if not contratos_visiveis(request.user, Contrato.objects.filter(pk=rel.contrato_id)).exists():
        raise PermissionDenied
    sistemas = list(rel.contrato.sistemas.filter(ativo=True).order_by("nome"))
    manuais = rel.dados.get("manuais") or {}
    if request.method == "POST" and request.POST.get("acao") in ("manual", "remover_manual"):
        exigir_escrita(request.user, ["Fiscal", "Financeiro", "Operação"])
        sistema = next((s for s in sistemas if str(s.pk) == request.POST.get("sistema")), None)
        if sistema is None:
            raise PermissionDenied
        form = MedicaoManualForm(request.POST, prefix=str(sistema.pk))
        try:
            if request.POST["acao"] == "remover_manual":
                srv.registrar_manual(rel, sistema, None)
                messages.success(request, f"Medição manual de {sistema.nome} removida.")
            elif form.is_valid():
                srv.registrar_manual(rel, sistema, form.cleaned_data)
                messages.success(request, f"Medição manual de {sistema.nome} registrada e relatório reapurado.")
            else:
                messages.error(request, "Revise a medição: " + "; ".join(
                    f"{form.fields[c].label}: {' '.join(e)}" if c in form.fields else " ".join(e) for c, e in form.errors.items()))
        except ValidationError as erro:
            messages.error(request, "; ".join(erro.messages))
        return redirect("relatorios:sla", pk=pk)
    if request.method == "POST":
        exigir_escrita(request.user, ["Fiscal", "Financeiro", "Operação"])
        try:
            srv.aprovar(rel, request.user, request.POST.get("observacoes", ""))
        except ValidationError as erro:
            messages.error(request, "; ".join(erro.messages))
        else:
            messages.success(request, "Relatório de SLA aprovado e PDF gerado.")
        return redirect("relatorios:sla", pk=pk)
    inicio = rel.competencia.replace(day=1)
    blocos = [{"sistema": s, "manual": str(s.pk) in manuais, "form": MedicaoManualForm(
        prefix=str(s.pk), initial=manuais.get(str(s.pk)) or {"periodo_inicio": inicio, "periodo_fim": srv.periodo(inicio)[1].date(),
                                                              "fonte": "UptimeRobot", "intervalo_min": 5, "incidentes": 0,
                                                              "indisponivel_seg": 0})} for s in sistemas]
    return render(request, "contratos/relatorio_sla.html", {"rel": rel, "dados": rel.dados, "blocos": blocos,
                  "pode_aprovar": pode_escrever(request.user, ["Fiscal", "Financeiro", "Operação"]) and rel.status != "APROVADO"})


app_name = "relatorios"
urlpatterns = [
    path("", central, name="home"),
    path("enviar/", enviar, name="enviar"),
    path("documentos/<uuid:pk>/arquivar/", arquivar, name="arquivar"),
    path("sla/gerar/", sla_gerar, name="sla_gerar"),
    path("sla/<uuid:pk>/", sla, name="sla"),
]
