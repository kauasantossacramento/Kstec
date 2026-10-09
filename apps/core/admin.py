from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from simple_history.admin import SimpleHistoryAdmin

from .models import (
    Anexo,
    Empresa,
    Endereco,
    LogAcesso,
    LogIntegracao,
    Notificacao,
    Parametro,
    Segredo,
    Usuario,
)


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    ordering = ["email"]
    list_display = ["email", "nome", "is_active", "is_superuser", "mfa_ativo"]
    search_fields = ["email", "nome"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Dados", {"fields": ("nome", "empresa", "cargo", "telefone", "cpf", "tema", "mfa_ativo")}),
        ("Permissões", {"fields": ("is_active", "is_staff", "is_superuser", "groups")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),)


admin.site.register(Empresa, SimpleHistoryAdmin)
admin.site.register(Endereco, SimpleHistoryAdmin)
admin.site.register(Parametro, SimpleHistoryAdmin)
admin.site.register(Anexo, SimpleHistoryAdmin)


@admin.register(Segredo)
class SegredoAdmin(admin.ModelAdmin):
    list_display = ["nome", "escopo", "rotacionado_em"]
    exclude = ["valor_criptografado"]


@admin.register(LogIntegracao)
class LogIntegracaoAdmin(admin.ModelAdmin):
    list_display = ["criado_em", "servico", "operacao", "status_http", "sucesso", "duracao_ms"]
    list_filter = ["servico", "sucesso"]
    search_fields = ["operacao", "chave_idempotencia"]


admin.site.register(Notificacao)
admin.site.register(LogAcesso)

admin.site.site_header = "KS CENTRAL — Administração"
