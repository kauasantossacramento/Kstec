import base64
import io

import qrcode
import qrcode.image.svg
from django import forms
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice

from .busca import buscar
from .crud import Coluna, Crud
from .forms import FormKS, FormSimples
from .models import Anexo, Empresa, LogAcesso, LogIntegracao, Notificacao, Parametro, Usuario
from .permissoes import exigir_escrita
from .services.brasilapi import ConsultaIndisponivel, consultar_cep, consultar_cnpj

# ---------------------------------------------------------------------------
# Autenticação e MFA
# ---------------------------------------------------------------------------


class LoginForm(FormSimples):
    username = forms.EmailField(label="E-mail", widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email"}))
    password = forms.CharField(label="Senha", widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user_cache = None
        super().__init__(*args, **kwargs)

    def clean(self):
        from django.contrib.auth import authenticate

        email = (self.cleaned_data.get("username") or "").lower()
        senha = self.cleaned_data.get("password")
        if email and senha:
            self.user_cache = authenticate(self.request, username=email, password=senha)
            if self.user_cache is None or not self.user_cache.is_active:
                raise forms.ValidationError("E-mail ou senha incorretos.")
        return self.cleaned_data

    def get_user(self):
        return self.user_cache


class Login(auth_views.LoginView):
    template_name = "registration/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


class TokenForm(FormSimples):
    token = forms.CharField(label="Código de 6 dígitos", max_length=6, min_length=6,
                            widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "one-time-code",
                                                          "autofocus": True, "class": "mono"}))


def _qr_svg(uri: str) -> str:
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=8)
    buf = io.BytesIO()
    img.save(buf)
    return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()


@login_required
def mfa_configurar(request):
    device = TOTPDevice.objects.filter(user=request.user, confirmed=False).first()
    if device is None:
        device = TOTPDevice.objects.create(user=request.user, name="Autenticador", confirmed=False)
    form = TokenForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if device.verify_token(form.cleaned_data["token"]):
            device.confirmed = True
            device.save()
            TOTPDevice.objects.filter(user=request.user).exclude(pk=device.pk).delete()
            otp_login(request, device)
            request.user.mfa_ativo = True
            request.user.save(update_fields=["mfa_ativo"])
            messages.success(request, "Autenticação em dois fatores ativada.")
            return redirect("painel:home")
        form.add_error("token", "Código inválido. Confira o horário do celular e tente novamente.")
    segredo = base64.b32encode(device.bin_key).decode().rstrip("=")
    return render(request, "registration/mfa_configurar.html",
                  {"form": form, "qr": _qr_svg(device.config_url), "segredo": segredo})


@login_required
def mfa_verificar(request):
    form = TokenForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        for device in TOTPDevice.objects.filter(user=request.user, confirmed=True):
            if device.verify_token(form.cleaned_data["token"]):
                otp_login(request, device)
                destino = request.GET.get("next") or reverse("painel:home")
                return redirect(destino if destino.startswith("/") else "/")
        form.add_error("token", "Código inválido.")
    return render(request, "registration/mfa_verificar.html", {"form": form})


# ---------------------------------------------------------------------------
# Perfil, tema, notificações, busca, anexos
# ---------------------------------------------------------------------------


class PerfilForm(FormKS):
    class Meta:
        model = Usuario
        fields = ["nome", "cargo", "telefone", "tema"]


@login_required
def perfil(request):
    form = PerfilForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Perfil atualizado.")
        return redirect("core:perfil")
    return render(request, "core/perfil.html", {"form": form,
                                                "mfa": TOTPDevice.objects.filter(user=request.user, confirmed=True).exists()})


@login_required
@require_POST
def tema(request):
    valor = request.POST.get("tema")
    if valor in ("claro", "escuro"):
        request.user.tema = valor
        request.user.save(update_fields=["tema"])
    return HttpResponse(status=204)


@login_required
def notificacoes(request):
    qs = request.user.notificacoes.all()[:100]
    if request.method == "POST":
        request.user.notificacoes.filter(lida_em__isnull=True).update(lida_em=timezone.now())
        return redirect("core:notificacoes")
    return render(request, "core/notificacoes.html", {"notificacoes": qs})


@login_required
def notificacao_abrir(request, pk):
    n = get_object_or_404(Notificacao, pk=pk, usuario=request.user)
    if not n.lida_em:
        n.lida_em = timezone.now()
        n.save(update_fields=["lida_em"])
    return redirect(n.link or "core:notificacoes")


@login_required
def busca(request):
    grupos = buscar(request.GET.get("q", ""), request.empresa)
    return render(request, "core/busca_resultados.html", {"grupos": grupos, "q": request.GET.get("q", "")})


@login_required
def anexo_baixar(request, pk):
    anexo = get_object_or_404(Anexo, pk=pk, empresa=request.empresa)
    objeto = anexo.objeto
    if objeto is not None and objeto.__class__.__name__ in ("NotaFiscal", "Lancamento", "GuiaISS"):
        if not request.user.tem_papel("Administrador", "Fiscal", "Financeiro", "Leitura"):
            raise PermissionDenied
    LogAcesso.objects.create(
        usuario=request.user, acao="download", content_type=anexo.content_type, object_id=anexo.object_id,
        descricao=anexo.nome, ip=request.META.get("REMOTE_ADDR"), empresa=request.empresa,
    )
    return FileResponse(anexo.arquivo.open("rb"), as_attachment=request.GET.get("ver") != "1", filename=anexo.nome)


@login_required
def consulta_cnpj(request):
    try:
        return JsonResponse(consultar_cnpj(request.GET.get("cnpj", "")))
    except ConsultaIndisponivel as e:
        return JsonResponse({"erro": str(e)})


@login_required
def consulta_cep(request):
    try:
        return JsonResponse(consultar_cep(request.GET.get("cep", "")))
    except ConsultaIndisponivel as e:
        return JsonResponse({"erro": str(e)})


@login_required
def componentes(request):
    """Catálogo vivo do design system (/_componentes)."""
    dias = [{"dia": timezone.localdate() - timezone.timedelta(days=89 - i),
             "pct": 100 if i % 17 else (97.2 if i % 2 else 92.0)} for i in range(90)]
    return render(request, "core/componentes.html", {"dias": dias,
                                                     "status_nota": ["RASCUNHO", "VALIDADA", "NA_FILA", "AUTORIZADA",
                                                                     "REJEITADA", "CANCELADA", "ERRO_COMUNICACAO"]})


# ---------------------------------------------------------------------------
# Configurações
# ---------------------------------------------------------------------------


@login_required
def configuracoes(request):
    return render(request, "core/configuracoes.html")


class EmpresaForm(FormKS):
    class Meta:
        model = Empresa
        fields = ["razao_social", "nome_fantasia", "cnpj", "inscricao_municipal", "inscricao_estadual",
                  "regime_tributario", "optante_simples", "regime_especial_tributacao", "natureza_juridica",
                  "cnae_principal", "email", "telefone", "site", "municipio_ibge", "responsavel_tecnico",
                  "cor_primaria"]


@login_required
def empresa_editar(request):
    if request.method == "POST" and not request.user.tem_papel("Administrador"):
        raise PermissionDenied
    form = EmpresaForm(request.POST or None, instance=request.empresa)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Dados da empresa atualizados.")
        return redirect("core:configuracoes")
    return render(request, "core/empresa.html", {"form": form})


class UsuarioForm(FormKS):
    papeis = forms.ModelMultipleChoiceField(queryset=Group.objects.all(), required=False,
                                            widget=forms.CheckboxSelectMultiple, label="Papéis")
    senha_inicial = forms.CharField(required=False, widget=forms.PasswordInput, label="Senha inicial",
                                    help_text="Mínimo de 10 caracteres. Deixe em branco para manter a atual.")

    class Meta:
        model = Usuario
        fields = ["email", "nome", "cargo", "telefone", "cpf", "is_active"]

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        if self.instance.pk:
            self.fields["papeis"].initial = self.instance.groups.all()

    def clean_senha_inicial(self):
        from django.contrib.auth.password_validation import validate_password

        s = self.cleaned_data.get("senha_inicial")
        if s:
            validate_password(s)
        elif not self.instance.pk:
            raise forms.ValidationError("Informe a senha inicial.")
        return s

    def save(self, commit=True):
        u = super().save(commit=False)
        if self.cleaned_data.get("senha_inicial"):
            u.set_password(self.cleaned_data["senha_inicial"])
        papeis = self.cleaned_data["papeis"]
        self.save_m2m = lambda: u.groups.set(papeis)
        if commit:
            u.save()
            self.save_m2m()
        return u


CRUD_USUARIO = Crud(
    model=Usuario, prefixo="usuario", namespace="core", caminho="configuracoes/usuarios", conversor="int",
    colunas=[Coluna("Nome", "nome", link=True), Coluna("E-mail", "email"), Coluna("Cargo", "cargo"),
             Coluna("Ativo", "is_active", "bool"), Coluna("MFA", "mfa_ativo", "bool")],
    form_class=UsuarioForm, busca=["nome", "email"], ordenacao=["nome"], papeis_escrita=["Administrador"],
    papeis_leitura=["Administrador"], anexos=False,
    campos_detalhe=["email", "nome", "cargo", "telefone", "is_active", "mfa_ativo", "last_login"],
)

CRUD_PARAMETRO = Crud(
    model=Parametro, prefixo="parametro", namespace="core", caminho="configuracoes/parametros",
    colunas=[Coluna("Chave", "chave", "mono", link=True), Coluna("Valor", "valor", "mono"),
             Coluna("Descrição", "descricao")],
    fields=["chave", "valor", "descricao"], busca=["chave", "descricao"], ordenacao=["chave"],
    papeis_escrita=["Administrador"], anexos=False,
)

CRUD_LOG = Crud(
    model=LogIntegracao, prefixo="log", namespace="core", caminho="configuracoes/logs",
    titulo="Log de integração", titulo_plural="Logs de integração",
    colunas=[Coluna("Quando", "criado_em", "datahora"), Coluna("Serviço", "servico"),
             Coluna("Operação", "operacao", "mono"), Coluna("HTTP", "status_http", "mono"),
             Coluna("ms", "duracao_ms", "mono"), Coluna("Sucesso", "sucesso", "bool")],
    fields=["servico", "operacao", "chave_idempotencia", "status_http", "duracao_ms", "sucesso", "request", "response"],
    filtros=["servico", "sucesso"], busca=["operacao", "chave_idempotencia"], permitir_criar=False,
    permitir_editar=False, anexos=False, papeis_leitura=["Administrador", "Fiscal", "Financeiro"],
)


def registrar_acesso(request, objeto, acao="visualizar", descricao=""):
    LogAcesso.objects.create(
        usuario=request.user, acao=acao, content_type=ContentType.objects.get_for_model(objeto),
        object_id=str(objeto.pk), descricao=descricao[:300], ip=request.META.get("REMOTE_ADDR"),
        empresa=request.empresa,
    )


def exigir_admin(request):
    exigir_escrita(request.user, ["Administrador"])
