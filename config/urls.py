from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path

from .health import health

urlpatterns = [
    path("health", health, name="health"),
    path("admin/", admin.site.urls),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
