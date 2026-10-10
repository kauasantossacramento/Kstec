import httpx
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.core.crud import Coluna, CriarGenerico, Crud, DetalheGenerico, EditarGenerico
from apps.core.permissoes import exigir_escrita

from .forms import ConfiguracaoForm, ConfirmarEmissaoForm, NotaForm
from .models import ConfiguracaoFiscal, NotaFiscal, PerfilFiscal
from .services import configuracao as serv_config
from .services import emissao
from .services.rascunhos import salvar

notas = Crud(NotaFiscal, "nota", "fiscal", [
    Coluna("Nota / tomador", "tomador", link=True), Coluna("Número", "numero_nfse", "mono"), Coluna("Competência", "competencia", "data"),
    Coluna("Serviços", "valor_servicos", "brl"), Coluna("Líquido", "valor_liquido", "brl"),
    Coluna("Situação", "status", "status", entidade="NotaFiscal"),
    Coluna("Recebimento", "recebivel.status", "status", entidade="Lancamento"),
], form_class=NotaForm, feminino=True, caminho="notas", papeis_escrita=["Fiscal", "Financeiro"],
    titulo="NFS-e", titulo_plural="Notas fiscais de serviço",
    papeis_leitura=["Fiscal", "Financeiro"],
    template_lista="fiscal/lista.html",
    template_detalhe="fiscal/detalhe.html",
    busca=["tomador__razao_social", "discriminacao", "numero_nfse", "chave_acesso"], filtros=["status", "ambiente", "canal"], select_related=["tomador", "recebivel"],
    subtitulo="Rascunhos, transmissões e documentos autorizados, com consulta do resultado e recebíveis.",
    campos_detalhe=NotaForm.Meta.fields + ["base_calculo", "valor_iss", "valor_iss_retido", "valor_ir",
                                           "valor_inss", "valor_pis", "valor_cofins", "valor_csll", "valor_liquido",
                                           "numero_nfse", "chave_acesso", "id_dps", "canal", "ambiente", "autorizada_em"])
perfis = Crud(PerfilFiscal, "perfil", "fiscal", [Coluna("Nome", "nome", link=True),
    Coluna("ISS (%)", "aliquota_iss"), Coluna("ISS retido", "iss_retido", "bool")],
    caminho="perfis", papeis_escrita=["Fiscal", "Financeiro"], papeis_leitura=["Fiscal", "Financeiro"],
    busca=["nome"])


class PersistenciaFiscal:
    def form_valid(self, form):
        nota = form.save(commit=False)
        nota.empresa = self.request.empresa
        try:
            self.object = salvar(nota)
        except ValidationError as erro:
            form.add_error(None, erro)
            return self.form_invalid(form)
        messages.success(self.request, "Rascunho calculado e salvo. Nenhuma nota foi transmitida.")
        return HttpResponseRedirect(self.get_success_url())


class CriarNota(PersistenciaFiscal, CriarGenerico):
    pass


class EditarNota(PersistenciaFiscal, EditarGenerico):
    pass


class DetalheNota(DetalheGenerico):
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.object.status != "RASCUNHO":
            ctx["url_editar"] = None
        ctx["tentativas"] = self.object.tentativas.all()
        ctx["pode_entregar"] = request_pode_entregar(self.request.user)
        ctx["entregas"] = self.object.entregas.all()
        from apps.core.permissoes import pode_escrever
        from apps.financeiro.models import ContaBancaria, Lancamento

        ctx["pode_receber"] = pode_escrever(self.request.user, ["Financeiro"])
        ctx["formas"] = Lancamento.Forma.choices
        ctx["forma_sugerida"] = "OB" if self.object.tomador.e_orgao_publico else "PIX"
        ctx["contas"] = ContaBancaria.objects.filter(empresa=self.request.empresa, ativo=True)
        ctx["anexos"] = ctx["anexos"].filter(ativo=True)
        return ctx


def request_pode_entregar(user):
    from apps.core.permissoes import pode_escrever

    return pode_escrever(user, ["Fiscal", "Financeiro"])


def _leitura(request):
    if not request.user.tem_papel("Administrador", "Fiscal", "Financeiro", "Leitura"):
        raise PermissionDenied


@login_required
def configuracao(request):
    _leitura(request)
    config = ConfiguracaoFiscal.objects.filter(empresa=request.empresa).first() or ConfiguracaoFiscal(empresa=request.empresa)
    form = ConfiguracaoForm(request.POST or None, request.FILES or None, instance=config)
    if request.method == "POST":
        exigir_escrita(request.user, ["Fiscal"])
        if form.is_valid():
            try:
                serv_config.salvar_configuracao(form.save(commit=False), token=form.cleaned_data["token"],
                    arquivo=form.cleaned_data.get("arquivo"), senha=form.cleaned_data["senha"])
            except ValidationError as erro:
                form.add_error(None, erro)
            else:
                messages.success(request, "Configuração fiscal salva. Credenciais protegidas por criptografia.")
                return redirect("fiscal:configuracao")
    return render(request, "fiscal/configuracao.html", {"form": form, "config": config,
                  "checklist": serv_config.checklist(config if config.pk and not config._state.adding else None),
                  "pode_salvar": request.user.tem_papel("Administrador", "Fiscal") and not request.user.somente_leitura})


@login_required
def emitir(request, pk):
    exigir_escrita(request.user, ["Fiscal"])
    nota = get_object_or_404(NotaFiscal, pk=pk, empresa=request.empresa)
    config = ConfiguracaoFiscal.objects.filter(empresa=request.empresa).first()
    form = ConfirmarEmissaoForm(request.POST or None)
    erros = []
    if config:
        try:
            emissao.validar_emissao(nota, config)
        except ValidationError as erro:
            erros = erro.messages
    else:
        erros = ["Cadastre a configuração fiscal."]
    if nota.status != "RASCUNHO":
        erros.append("A nota já tem uma transmissão. Consulte o resultado.")
    if request.method == "POST" and form.is_valid() and not erros:
        try:
            emissao.transmitir(nota)
        except ValidationError as erro:
            messages.error(request, "; ".join(erro.messages))
        else:
            messages.success(request, "Transmissão registrada. Consulte o resultado para acompanhar a autorização.")
        return redirect("fiscal:nota_detalhe", pk=pk)
    return render(request, "fiscal/emitir.html", {"nota": nota, "config": config, "form": form, "erros": erros})


@login_required
@require_POST
def consultar(request, pk):
    exigir_escrita(request.user, ["Fiscal"])
    nota = get_object_or_404(NotaFiscal, pk=pk, empresa=request.empresa)
    try:
        emissao.consultar(nota)
    except httpx.HTTPError:
        messages.error(request, "Consulta indisponível. Tente consultar novamente; não repita a emissão.")
    except ValidationError as erro:
        messages.error(request, "; ".join(erro.messages))
    else:
        messages.success(request, "Resultado da consulta registrado.")
    return redirect("fiscal:nota_detalhe", pk=pk)


@login_required
@require_POST
def gerar_recebivel(request, pk):
    exigir_escrita(request.user, ["Fiscal", "Financeiro"])
    nota = get_object_or_404(NotaFiscal, pk=pk, empresa=request.empresa)
    from apps.financeiro.services.recebiveis import gerar_recebivel as gerar

    try:
        gerar(nota)
    except ValidationError as erro:
        messages.error(request, "; ".join(erro.messages))
    else:
        messages.success(request, "Recebível vinculado à nota, sem duplicação.")
    return redirect("fiscal:nota_detalhe", pk=pk)


@login_required
@require_POST
def receber(request, pk):
    """Confirma o recebimento da nota: baixa integral do recebível, sem sair da tela da NFS-e."""
    from datetime import date

    from apps.financeiro.models import ContaBancaria, Lancamento
    from apps.financeiro.services.lancamentos import baixar

    exigir_escrita(request.user, ["Financeiro"])
    nota = get_object_or_404(NotaFiscal, pk=pk, empresa=request.empresa)
    lanc = Lancamento.objects.filter(nota_fiscal=nota, empresa=request.empresa).first()
    if lanc is None:
        messages.error(request, "A nota não tem recebível no financeiro. Gere o recebível primeiro.")
        return redirect("fiscal:nota_detalhe", pk=pk)
    try:
        conta = ContaBancaria.objects.filter(pk=request.POST.get("conta_bancaria") or None, empresa=request.empresa).first()
        baixar(lanc, data_pagamento=date.fromisoformat(request.POST.get("data_pagamento", "")),
               forma_pagamento=request.POST.get("forma_pagamento", ""), ordem_bancaria=request.POST.get("ordem_bancaria", ""),
               conta_bancaria=conta)
    except (ValidationError, ValueError) as erro:
        messages.error(request, "; ".join(erro.messages) if isinstance(erro, ValidationError) else "Data inválida.")
    else:
        messages.success(request, f"Recebimento da NFS-e {nota.numero_nfse} registrado.")
    return redirect(reverse("fiscal:nota_detalhe", args=[pk]) + "#recebimento")
