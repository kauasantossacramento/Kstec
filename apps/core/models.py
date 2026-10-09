"""Modelos do núcleo. Na Fase 0 apenas o usuário customizado (login por e-mail)."""

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UsuarioManager(BaseUserManager):
    use_in_migrations = True

    def _criar(self, email, password, **extra):
        if not email:
            raise ValueError("E-mail é obrigatório.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, username=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._criar(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self._criar(email, password, **extra)


class Usuario(AbstractUser):
    """Usuário do sistema; o login é feito por e-mail."""

    email = models.EmailField("e-mail", unique=True)
    nome = models.CharField(max_length=150, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []
    objects = UsuarioManager()

    class Meta:
        verbose_name = "usuário"
        verbose_name_plural = "usuários"

    def __str__(self):
        return self.nome or self.email
