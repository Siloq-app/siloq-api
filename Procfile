web: python manage.py migrate --noinput && gunicorn siloq_backend.wsgi:application --bind 0.0.0.0:${PORT:-8000}
