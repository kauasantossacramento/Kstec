"""Carga inicial: executa `seeds.seed(empresa)` de cada app local, na ordem de INSTALLED_APPS."""

from importlib import import_module

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core import contexto


class Command(BaseCommand):
    help = "Empresa KS TEC, papéis, categorias financeiras, tipos de certidão, prompts de IA, catálogo inicial."

    @transaction.atomic
    def handle(self, *args, **options):
        from apps.core.seeds import seed as seed_core

        empresa = seed_core()
        self.stdout.write(f"  core: empresa {empresa} e papéis")
        with contexto.usar_contexto(empresa=empresa):
            for app in apps.get_app_configs():
                if not app.name.startswith("apps.") or app.name == "apps.core":
                    continue
                try:
                    mod = import_module(f"{app.name}.seeds")
                except ModuleNotFoundError:
                    continue
                resultado = mod.seed(empresa)
                self.stdout.write(f"  {app.label}: {resultado or 'ok'}")
        self.stdout.write(self.style.SUCCESS("Carga inicial concluída."))
