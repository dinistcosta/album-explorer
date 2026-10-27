#!/usr/bin/env sh
# Start command for free hosting plans that have no separate worker process
# (e.g. Render's free web service): apply migrations, run the background
# task worker in this same container, then serve the site with gunicorn.
set -e

python manage.py migrate --noinput

# Restart the worker if it ever exits, so enrichment keeps running.
(while true; do python manage.py db_worker; sleep 5; done) &

exec gunicorn config.wsgi --workers 1 --threads 4 --timeout 60 \
  --bind "0.0.0.0:${PORT:-8000}" --log-file -
