from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import Contato, Pessoa


class ContatoInline(admin.TabularInline):
    model = Contato
    extra = 0
    exclude = ["empresa"]


@admin.register(Pessoa)
class PessoaAdmin(SimpleHistoryAdmin):
    list_display = ["razao_social", "cpf_cnpj", "eh_cliente", "eh_fornecedor", "e_orgao_publico"]
    search_fields = ["razao_social", "cpf_cnpj"]
    inlines = [ContatoInline]
