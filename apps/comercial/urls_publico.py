from django.urls import path

from . import views

urlpatterns = [path("<uuid:token>/", views.publico, name="publico")]
