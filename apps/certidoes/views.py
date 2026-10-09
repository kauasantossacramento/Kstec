from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.crud import Coluna, Crud, DetalheGenerico
from apps.core.forms import FormKS
from apps.core.permissoes import exigir_escrita, pode_escrever

from . import services
from .models import Certidao, KitHabilitacao, TipoCertidao


class CertidaoForm(FormKS):
    class Meta:
        model = Certidao
        fields = ["tipo", "arquivo", "data_emissao", "data_validade", "numero", "situacao", "codigo_autenticidade",
                  "url_validacao", "observacao"]

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["data_emissao"].required = False
        self.fields["data_validade"].required = False
        self.fields["arquivo"].help_text = "Envie o PDF: validade e código de controle são lidos automaticamente."
        self.extraido = {}

    def clean(self):
        d = super().clean()
        arq = d.get("arquivo")
        if arq and hasattr(arq, "read") and (not d.get("data_validade") or not d.get("numero")):
            conteudo = arq.read()
            arq.seek(0)
            self.extraido = services.extrair_dados(services.extrair_texto_pdf(conteudo))
            for campo in ("data_validade", "data_emissao", "numero"):
                if not d.get(campo) and self.extraido.get(campo):
                    d[campo] = self.extraido[campo]
                    self.instance.__dict__[campo] = self.extraido[campo]
            if self.extraido.get("situacao") and not self.data.get("situacao"):
                d["situacao"] = self.extraido["situacao"]
        if not d.get("data_emissao"):
            d["data_emissao"] = timezone.localdate()
        if not d.get("data_validade"):
            tipo = d.get("tipo")
            if tipo:
                # sem validade no PDF: usa a validade padrão do tipo (o usuário pode editar depois)
                d["data_validade"] = d["data_emissao"] + timezone.timedelta(days=tipo.validade_padrao_dias)
            else:
                self.add_error("data_validade", "Informe a validade.")
        return d


class KitForm(FormKS):
    class Meta:
        model = KitHabilitacao
        fields = ["nome", "certidoes"]
        widgets = {"certidoes": forms.CheckboxSelectMultiple}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["certidoes"].queryset = Certidao.objects.filter(ativo=True).select_related("tipo")
        if not self.instance.pk:
            vigentes = [t.vigente.pk for t in TipoCertidao.objects.filter(ativo=True) if t.vigente]
            self.fields["certidoes"].initial = vigentes


CRUD_TIPO = Crud(
    model=TipoCertidao, prefixo="tipo", namespace="certidoes", titulo="Tipo de certidão",
    colunas=[Coluna("Nome", "nome", link=True), Coluna("Órgão", "orgao_emissor"), Coluna("Esfera", "esfera"),
             Coluna("Validade (dias)", "validade_padrao_dias", "mono"),
             Coluna("Obrigatória", "obrigatoria_habilitacao", "bool")],
    busca=["nome", "orgao_emissor"], ordenacao=["nome"], anexos=False,
)
CRUD_CERTIDAO = Crud(
    model=Certidao, prefixo="certidao", namespace="certidoes", feminino=True, caminho="lista",
    colunas=[Coluna("Certidão", "tipo", link=True), Coluna("Nº / controle", "numero", "mono"),
             Coluna("Emissão", "data_emissao", "data"), Coluna("Validade", "data_validade", "data"),
             Coluna("Situação", "situacao"), Coluna("Status", "status", "status", "Certidao")],
    form_class=CertidaoForm, busca=["tipo__nome", "numero"], filtros=["tipo"], ordenacao=["-data_validade"],
    select_related=["tipo"],
)
CRUD_KIT = Crud(
    model=KitHabilitacao, prefixo="kit", namespace="certidoes", titulo="Kit de habilitação",
    colunas=[Coluna("Nome", "nome", link=True), Coluna("Gerado em", "gerado_em", "datahora")],
    form_class=KitForm, busca=["nome"], template_detalhe="certidoes/kit_detalhe.html",
)


class KitDetalhe(DetalheGenerico):
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["certs"] = self.object.certidoes.select_related("tipo")
        return ctx


@login_required
def home(request):
    situacao = services.situacao_habilitacao(request.empresa)
    return render(request, "certidoes/home.html", {"situacao": situacao,
                                                    "pode_escrever": pode_escrever(request.user)})


@login_required
@require_POST
def gerar_kit(request, pk):
    exigir_escrita(request.user)
    kit = get_object_or_404(KitHabilitacao, pk=pk, empresa=request.empresa)
    services.gerar_kit(kit)
    for a in getattr(kit, "avisos", []):
        messages.warning(request, a)
    messages.success(request, "Kit gerado.")
    return redirect(reverse("certidoes:kit_detalhe", args=[pk]))
