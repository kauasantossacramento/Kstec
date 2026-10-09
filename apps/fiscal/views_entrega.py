from datetime import date

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.contratos.models import Contrato
from apps.contratos.views import contratos_visiveis
from apps.core.permissoes import exigir_escrita, pode_escrever
from apps.financeiro.models import PlanilhaCustos
from apps.financeiro.services.custos import nova_planilha, salvar_planilha
from apps.operacao.models import RelatorioAtividades
from apps.operacao.relatorios import novo_relatorio, salvar_relatorio

from .forms_entrega import CustosFormSet, EnviarEntregaForm, PlanilhaForm, PrepararEntregaForm, RelatorioForm
from .models import EntregaNota, NotaFiscal
from .services.entregas import documentos_contrato, enviar_entrega, preparar_entrega
from .services.pdf_nfse import garantir_pdf
from .views import _leitura


@login_required
def pdf(request, pk):
    _leitura(request)
    nota = get_object_or_404(NotaFiscal, pk=pk, empresa=request.empresa)
    try:
        arquivo = garantir_pdf(nota)
    except ValidationError as erro:
        messages.error(request, "; ".join(erro.messages))
        return redirect("fiscal:nota_detalhe", pk=pk)
    return FileResponse(arquivo.arquivo.open("rb"), as_attachment=request.GET.get("baixar") == "1", filename=arquivo.nome)


@login_required
def entregas(request, pk):
    exigir_escrita(request.user, ["Fiscal", "Financeiro"])
    nota = get_object_or_404(NotaFiscal, pk=pk, empresa=request.empresa)
    pendentes = []
    if nota.contrato_id:
        try:
            documentos_contrato(nota)
        except ValidationError as erro:
            pendentes = erro.messages
    form = PrepararEntregaForm(request.POST or None, initial={
        "destinatarios": nota.tomador.email_destino_nf,
        "assunto": f"NFS-e {nota.numero_nfse}" + (f" · Contrato {nota.contrato.numero}" if nota.contrato_id else ""),
        "mensagem": f"Prezados,\n\nSegue a documentação da NFS-e {nota.numero_nfse}, competência {nota.competencia:%m/%Y}.\n\nAtenciosamente,\n{nota.empresa.razao_social}"})
    if request.method == "POST" and form.is_valid():
        try:
            entrega = preparar_entrega(nota, **form.cleaned_data)
        except (ValidationError, OSError) as erro:
            form.add_error(None, erro if isinstance(erro, ValidationError) else "Não foi possível ler os documentos cadastrados.")
        else:
            return redirect("fiscal:entrega_revisar", pk=entrega.pk)
    return render(request, "fiscal/entregas.html", {"nota": nota, "form": form, "pendentes": pendentes,
              "entregas": nota.entregas.all(), "backend_email": settings.EMAIL_BACKEND,
              "email_real": settings.EMAIL_BACKEND == "django.core.mail.backends.smtp.EmailBackend"})


@login_required
def entrega_revisar(request, pk):
    exigir_escrita(request.user, ["Fiscal", "Financeiro"])
    entrega = get_object_or_404(EntregaNota, pk=pk, empresa=request.empresa)
    form = EnviarEntregaForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            entrega = enviar_entrega(entrega)
        except (ValidationError, OSError) as erro:
            form.add_error(None, erro if isinstance(erro, ValidationError) else "Não foi possível ler o pacote arquivado.")
        else:
            messages.success(request, entrega.get_status_display() + ".")
            return redirect("fiscal:entrega_revisar", pk=pk)
    return render(request, "fiscal/entrega_revisar.html", {"entrega": entrega, "form": form,
               "email_real": settings.EMAIL_BACKEND == "django.core.mail.backends.smtp.EmailBackend"})


@login_required
def documentos(request, pk):
    contrato = get_object_or_404(contratos_visiveis(request.user, Contrato.objects.filter(empresa=request.empresa)), pk=pk)
    try:
        competencia = date.fromisoformat(request.GET.get("competencia") or timezone.localdate().replace(day=1).isoformat()).replace(day=1)
        if competencia > timezone.localdate():
            raise ValueError
    except ValueError:
        return HttpResponse("Informe uma competência válida, sem mês futuro.", status=400)
    relatorio = RelatorioAtividades.objects.filter(contrato=contrato, empresa=request.empresa, competencia=competencia).first()
    planilha = PlanilhaCustos.objects.filter(contrato=contrato, empresa=request.empresa, competencia=competencia).first()
    pode_relatorio = pode_escrever(request.user, ["Operação"]) and (request.user.tem_papel("Administrador")
                            or contrato.responsaveis.filter(pk=request.user.pk).exists())
    pode_custos = pode_escrever(request.user, ["Financeiro"])
    ver_custos = request.user.tem_papel("Administrador", "Fiscal", "Financeiro", "Leitura")
    acao = request.POST.get("acao", "")
    form_relatorio = RelatorioForm(request.POST if acao in ("salvar_relatorio", "aprovar_relatorio") else None, instance=relatorio) if relatorio else None
    form_planilha = PlanilhaForm(request.POST if acao in ("salvar_custos", "aprovar_custos") else None, instance=planilha) if planilha and ver_custos else None
    iniciais = [{f: getattr(item, f) for f in ("grupo", "descricao", "unidade", "quantidade", "valor_unitario", "rateio_pct", "periodicidade", "fonte")}
                  for item in planilha.itens.order_by("criado_em", "pk")] if planilha and ver_custos else []
    custos = CustosFormSet(request.POST if acao in ("salvar_custos", "aprovar_custos") else None, prefix="custos", initial=iniciais)
    if request.method == "POST":
        if acao in ("novo_relatorio", "salvar_relatorio", "aprovar_relatorio"):
            if not pode_relatorio:
                raise PermissionDenied
        elif acao in ("nova_planilha", "salvar_custos", "aprovar_custos"):
            if not pode_custos:
                raise PermissionDenied
        else:
            return HttpResponse("Ação inválida.", status=400)
        try:
            if acao == "novo_relatorio":
                novo_relatorio(contrato, competencia)
            elif acao == "nova_planilha":
                nova_planilha(contrato, competencia)
            elif acao.endswith("relatorio") and form_relatorio and form_relatorio.is_valid():
                # O ID do formulário impede aprovar uma versão substituída em outra aba.
                if request.POST.get("versao_id") != str(relatorio.pk):
                    raise ValidationError("A versão mudou. Recarregue a tela antes de salvar.")
                salvar_relatorio(relatorio, form_relatorio.cleaned_data, request.user, acao.startswith("aprovar"))
            elif acao.endswith("custos") and form_planilha and form_planilha.is_valid() and custos.is_valid():
                if request.POST.get("versao_id") != str(planilha.pk):
                    raise ValidationError("A versão mudou. Recarregue a tela antes de salvar.")
                linhas = [{f: d[f] for f in ("grupo", "descricao", "unidade", "quantidade", "valor_unitario", "rateio_pct", "periodicidade", "fonte")}
                           for d in custos.cleaned_data if d]
                salvar_planilha(planilha, form_planilha.cleaned_data, linhas, request.user, acao.startswith("aprovar"))
            else:
                raise ValidationError("Corrija os campos destacados antes de salvar.")
        except ValidationError as erro:
            messages.error(request, "; ".join(erro.messages))
        else:
            messages.success(request, "Documento salvo. Versões aprovadas são preservadas.")
            return redirect(request.path + f"?competencia={competencia}")
    return render(request, "fiscal/documentos_contrato.html", {"contrato": contrato, "competencia": competencia,
          "relatorio": relatorio, "planilha": planilha if ver_custos else None, "form_relatorio": form_relatorio,
          "form_planilha": form_planilha, "custos": custos, "pode_relatorio": pode_relatorio, "pode_custos": pode_custos,
          "historico_relatorios": contrato.relatorios_atividades.filter(competencia=competencia),
          "historico_custos": contrato.planilhas_custos.filter(competencia=competencia) if ver_custos else []})
