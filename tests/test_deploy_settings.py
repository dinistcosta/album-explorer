import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROD_ENV = {
    "DEBUG": "0",
    "SECRET_KEY": "k3y-" + "x7Qp9Zr2" * 8,
    "ALLOWED_HOSTS": "example.org",
    "CSRF_TRUSTED_ORIGINS": "https://example.org",
    "DATABASE_URL": "sqlite:///:memory:",
}


def run_manage(*args, env):
    full = {k: v for k, v in os.environ.items() if k not in ("DEBUG", "SECRET_KEY", "DJANGO_SETTINGS_MODULE")}
    full["ENV_FILE"] = os.devnull  # never read the developer's .env
    full.update(env)
    return subprocess.run([sys.executable, "manage.py", *args], cwd=ROOT, env=full,
                          capture_output=True, text=True)


def test_check_deploy_passes():
    out = run_manage("check", "--deploy", "--fail-level", "WARNING", env=PROD_ENV)
    assert out.returncode == 0, out.stdout + out.stderr


def test_production_requires_secret_key():
    env = {k: v for k, v in PROD_ENV.items() if k != "SECRET_KEY"}
    out = run_manage("check", env=env)
    assert out.returncode != 0
    assert "SECRET_KEY" in out.stderr


def test_debug_defaults_to_false():
    out = run_manage("shell", "-c", "from django.conf import settings; print(settings.DEBUG)",
                     env={"SECRET_KEY": PROD_ENV["SECRET_KEY"]})
    assert out.stdout.strip().splitlines()[-1] == "False", out.stderr


def test_blank_values_in_env_file_count_as_unset(tmp_path):
    envfile = tmp_path / ".env"
    envfile.write_text("DEBUG=1\nDATABASE_URL=\nCONTACT_URL=\nLASTFM_API_KEY=\n", encoding="utf-8")
    out = run_manage(
        "shell", "-c",
        "from django.conf import settings as s; print(s.DATABASES['default']['ENGINE'], s.CONTACT_URL)",
        env={"ENV_FILE": str(envfile), "SECRET_KEY": "", "DEBUG": ""})
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == "django.db.backends.sqlite3 https://github.com/album-explorer"


def test_render_hostname_is_allowed_and_trusted():
    env = {k: v for k, v in PROD_ENV.items() if k not in ("ALLOWED_HOSTS", "CSRF_TRUSTED_ORIGINS")}
    out = run_manage(
        "shell", "-c",
        "from django.conf import settings as s; print(s.ALLOWED_HOSTS, s.CSRF_TRUSTED_ORIGINS)",
        env={**env, "RENDER_EXTERNAL_HOSTNAME": "album-explorer.onrender.com"})
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == (
        "['album-explorer.onrender.com'] ['https://album-explorer.onrender.com']")


def test_blank_environment_variables_count_as_unset():
    out = run_manage(
        "shell", "-c", "from django.conf import settings as s; print(s.CONTACT_URL)",
        env={**PROD_ENV, "CONTACT_URL": "", "DATABASE_URL": ""})
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == "https://github.com/album-explorer"


def test_log_lines_are_emitted_once():
    code = ("import logging; logging.getLogger('django.tasks').info('ONCE-MARKER')")
    out = run_manage("shell", "-c", code, env={"DEBUG": "1"})
    assert (out.stdout + out.stderr).count("ONCE-MARKER") == 1, out.stdout + out.stderr
