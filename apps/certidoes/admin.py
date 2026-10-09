from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import Certidao, KitHabilitacao, TipoCertidao

for m in (TipoCertidao, Certidao, KitHabilitacao):
    admin.site.register(m, SimpleHistoryAdmin)
