from pathlib import Path

from django.core.management.base import BaseCommand

from apps.catalogo.municipal import importar_municipais


class Command(BaseCommand):
    help = "Importa referências municipais de PDF/CSV, sem inferir código da API a partir da LC 116."

    def add_arguments(self, parser):
        parser.add_argument("arquivo")
        parser.add_argument("--municipio", required=True)
        parser.add_argument("--fonte", required=True)
        parser.add_argument("--confirmar-codigos", action="store_true")

    def handle(self, *args, **options):
        p = Path(options["arquivo"])
        n = importar_municipais(p.read_bytes(), p.name, options["municipio"], options["fonte"], options["confirmar_codigos"])
        self.stdout.write(f"{n} serviços municipais importados com fonte.")
