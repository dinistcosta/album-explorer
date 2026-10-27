import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent



def _load_dotenv(path):
    """Minimal .env reader (KEY=VALUE lines). Real environment variables win; blank values are skipped."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip("\"'")
        key = key.strip()
        if value and not os.environ.get(key):
            os.environ[key] = value


def env(name, default=""):
    """Environment variable where an empty value counts as unset."""
    return os.environ.get(name) or default


# ENV_FILE=/some/path overrides the default .env location (tests point it at a missing file).
_load_dotenv(Path(os.environ["ENV_FILE"]) if "ENV_FILE" in os.environ else BASE_DIR / ".env")


def env_list(name, default=""):
    return [v.strip() for v in env(name, default).split(",") if v.strip()]


# Secure by default: DEBUG is off unless explicitly enabled (DEBUG=1 in .env for local work).
DEBUG = env("DEBUG", "0").lower() in ("1", "true", "yes")

SECRET_KEY = env("SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("SECRET_KEY must be set when DEBUG is off.")
    SECRET_KEY = "dev-insecure-key-change-me"  # development only

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1" if DEBUG else "")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

# Render sets this to the service's public hostname.
RENDER_EXTERNAL_HOSTNAME = env("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_EXTERNAL_HOSTNAME}")

LASTFM_API_KEY = env("LASTFM_API_KEY")
DISCOGS_TOKEN = env("DISCOGS_TOKEN")
CONTACT_URL = env("CONTACT_URL", "https://github.com/album-explorer")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "django.contrib.messages",
    "django_tasks_db",
    "catalog",
    "sources",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.i18n",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.static",
            ],
        },
    },
]

DATABASES = {"default": dj_database_url.parse(env("DATABASE_URL", "sqlite:///db.sqlite3"))}
if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
    DATABASES["default"].setdefault("OPTIONS", {})["transaction_mode"] = "IMMEDIATE"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGES = [("pt", "Português"), ("en", "English")]
LANGUAGE_CODE = "pt"
LOCALE_PATHS = [BASE_DIR / "locale"]
USE_I18N = True
USE_TZ = True
TIME_ZONE = "UTC"

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Database-backed task queue (no Redis). Worker: `python manage.py db_worker`.
# Tests swap this for the immediate backend (tests/conftest.py).
TASKS = {"default": {"BACKEND": "django_tasks_db.DatabaseBackend"}}

if not DEBUG:
    # TLS is terminated by the host's proxy, which sets X-Forwarded-Proto.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env("SECURE_SSL_REDIRECT", "1").lower() in ("1", "true", "yes")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # Conservative until the final domain is chosen; raise via env (31536000 = 1 year), then enable the rest.
    SECURE_HSTS_SECONDS = int(env("SECURE_HSTS_SECONDS", "3600"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env("SECURE_HSTS_INCLUDE_SUBDOMAINS", "0").lower() in ("1", "true", "yes")
    SECURE_HSTS_PRELOAD = env("SECURE_HSTS_PRELOAD", "0").lower() in ("1", "true", "yes")
    SILENCED_SYSTEM_CHECKS = [
        c for c, on in (("security.W005", SECURE_HSTS_INCLUDE_SUBDOMAINS), ("security.W021", SECURE_HSTS_PRELOAD))
        if not on  # deliberately off until the domain is final
    ]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    # Django's own console handler would duplicate every line the root handler already prints.
    "loggers": {"django": {"handlers": [], "propagate": True}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}
