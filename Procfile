release: python manage.py migrate --noinput
web: gunicorn config.wsgi --workers 2 --threads 4 --timeout 60 --log-file -
worker: python manage.py db_worker
