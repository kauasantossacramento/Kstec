from django.urls import path

from . import views

app_name = "painel"

urlpatterns = [
    path("", views.home, name="home"),
    path("agenda/", views.agenda, name="agenda"),
]
