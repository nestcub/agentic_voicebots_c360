"""telehub URL Configuration"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/telehub/", include("apps.telehub.api.urls")),
]
