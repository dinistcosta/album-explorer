from django.apps import AppConfig


class CatalogConfig(AppConfig):
    name = "catalog"

    def ready(self):
        # Importing registers the enrichers; later tasks add their modules here.
        from . import tasks  # noqa: F401
