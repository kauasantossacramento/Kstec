from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import Aditivo, Competencia, Contrato, Empenho, ItemContrato

for m in (Contrato, Aditivo, ItemContrato, Empenho, Competencia):
    admin.site.register(m, SimpleHistoryAdmin)
