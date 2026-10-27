from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("search/", views.search, name="search"),
    path("search/suggest/", views.suggest, name="suggest"),
    path("genre/<slug:slug>/", views.genre_detail, name="genre_detail"),
    path("album/<uuid:mbid>/", views.album_detail, name="album_detail"),
    path("album/<uuid:mbid>/sections/", views.album_enrichment, name="album_enrichment"),
    path("artist/<uuid:mbid>/", views.artist_detail, name="artist_detail"),
    path("artist/<uuid:mbid>/sections/", views.artist_enrichment, name="artist_enrichment"),
]
