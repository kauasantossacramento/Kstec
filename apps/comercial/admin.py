from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import ItemOrcamento, ItemVenda, Orcamento, Venda

for m in (Orcamento, ItemOrcamento, Venda, ItemVenda):
    admin.site.register(m, SimpleHistoryAdmin)
