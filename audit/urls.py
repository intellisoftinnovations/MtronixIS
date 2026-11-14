from django.urls import path

from . import views

app_name = "audit"

urlpatterns = [
    path("", views.log_list, name="log_list"),
    path("export.csv", views.log_export, name="log_export"),
]

