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
