release: python manage.py migrate --noinput
web: gunicorn config.wsgi --log-file -
worker: python manage.py db_worker
