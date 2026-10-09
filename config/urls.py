from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from .health import health

urlpatterns = [
    path("health", health, name="health"),
    path("admin/", admin.site.urls),
    path("conta/senha/", auth_views.PasswordChangeView.as_view(), name="password_change"),
    path("conta/senha/ok/", auth_views.PasswordChangeDoneView.as_view(), name="password_change_done"),
    path("", include("apps.core.urls")),
    path("cadastros/", include("apps.cadastros.urls")),
    path("contratos/", include("apps.contratos.urls")),
    path("certidoes/", include("apps.certidoes.urls")),
    path("catalogo/", include("apps.catalogo.urls")),
    path("comercial/", include("apps.comercial.urls")),
    path("o/", include(("apps.comercial.urls_publico", "comercial_publico"))),
    path("", include("apps.painel.urls")),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
