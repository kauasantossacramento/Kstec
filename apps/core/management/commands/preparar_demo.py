"""Cria acesso de demonstração sem alterar senhas de usuários existentes."""

import secrets

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.models import Usuario
from apps.core.seeds import seed


class Command(BaseCommand):
    help = "Cria administrador local; exibe senha aleatória somente na criação."

    def handle(self, *args, **options):
        if settings.SETTINGS_MODULE != "config.settings.local":
            raise CommandError("Use somente com --settings=config.settings.local.")
        with transaction.atomic():
            empresa = seed()
            usuario, criado = Usuario.objects.get_or_create(
                email="demo@kstec.local",
                defaults={"nome": "Administrador local", "empresa": empresa, "is_staff": True},
            )
            if criado:
                senha = secrets.token_urlsafe(18)
                usuario.set_password(senha)
                usuario.save()
                usuario.groups.add(Group.objects.get(name="Administrador"))
                self.stdout.write(f"Acesso local: {usuario.email}\nSenha inicial: {senha}")
            else:
                self.stdout.write("Administrador local já existe; senha e permissões preservadas.")
