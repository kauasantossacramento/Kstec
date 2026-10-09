from django.core.management.base import BaseCommand, CommandError

from apps.catalogo.importador import Resultado, importar_arquivo


class Command(BaseCommand):
    help = "Importa LC 116, cTribNac, NBS (Anexo B) e correlação IBS/CBS (Anexo VIII) a partir dos XLSX."

    def add_arguments(self, parser):
        parser.add_argument("arquivos", nargs="+")

    def handle(self, *args, **options):
        r = Resultado()
        for arq in options["arquivos"]:
            try:
                importar_arquivo(arq, r)
            except FileNotFoundError as e:
                raise CommandError(str(e))
            self.stdout.write(f"  {arq}: processado")
        for a in r.avisos:
            self.stdout.write(self.style.WARNING(a))
        self.stdout.write(self.style.SUCCESS(str(r)))
