#!/usr/bin/env python
"""
Run Django development server with HTTPS support using werkzeug.
Usage: python runserver_https.py
"""
import os
import sys

# Set Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'siloq_backend.settings')

# Import Django after setting environment
import django
django.setup()

from werkzeug.serving import run_simple
from django.core.handlers.wsgi import WSGIHandler

# SSL certificate paths (relative to project root)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CERT_FILE = os.path.join(BASE_DIR, 'ssl', 'localhost+2.pem')
KEY_FILE = os.path.join(BASE_DIR, 'ssl', 'localhost+2-key.pem')

# Check if certificates exist
if not os.path.exists(CERT_FILE) or not os.path.exists(KEY_FILE):
    print("SSL certificates not found in ssl/ directory")
    print("Run: mkdir -p ssl && cd ssl && mkcert localhost 127.0.0.1 ::1")
    sys.exit(1)

print(f"Starting HTTPS server at https://localhost:8000")
print(f"Certificate: {CERT_FILE}")
print(f"Key: {KEY_FILE}")
print("Press Ctrl+C to stop")

# Run with SSL
application = WSGIHandler()
run_simple(
    'localhost',
    8000,
    application,
    ssl_context=(CERT_FILE, KEY_FILE),
    use_reloader=True,
    use_debugger=True
)
