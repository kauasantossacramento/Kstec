from django.core.management.base import BaseCommand

from apps.contratos.services import gerar_competencias_vigentes


class Command(BaseCommand):
    help = "Cria as competências faltantes dos contratos vigentes."

    def handle(self, *args, **options):
        n = gerar_competencias_vigentes()
        self.stdout.write(self.style.SUCCESS(f"{n} competência(s) criada(s)."))
