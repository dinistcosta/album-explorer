from django.apps import AppConfig


class CatalogConfig(AppConfig):
    name = "catalog"

    def ready(self):
        # Importing registers the enrichers; later tasks add their modules here.
        from . import tasks  # noqa: F401
        from .services import wikidata_import  # noqa: F401
        from .services import stories  # noqa: F401
        from .services import genres  # noqa: F401
        from .services import links  # noqa: F401
        from .services import quotes  # noqa: F401
