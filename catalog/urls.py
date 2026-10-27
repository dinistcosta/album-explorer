from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("album/<uuid:mbid>/", views.album_detail, name="album_detail"),
    path("album/<uuid:mbid>/sections/", views.album_enrichment, name="album_enrichment"),
]
