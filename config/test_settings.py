"""Settings for the test suite: DEBUG on, throwaway key, plain static storage (no manifest needed)."""
import os
import tempfile

os.environ.setdefault("DEBUG", "1")
os.environ.setdefault("SECRET_KEY", "test-only-secret-key")

from .settings import *  # noqa: E402,F401,F403

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
STATIC_ROOT = tempfile.mkdtemp(prefix="album-explorer-static-")
STORAGES = {
    **STORAGES,  # noqa: F405
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
