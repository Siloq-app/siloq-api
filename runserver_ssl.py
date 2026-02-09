#!/usr/bin/env python
"""
Run Django development server with HTTPS support.
Usage: python runserver_ssl.py
"""
import os
import sys

# Set Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'siloq_backend.settings')

# Import Django after setting environment
import django
django.setup()

from django.core.management import call_command
from django.conf import settings

# SSL certificate paths
CERT_FILE = os.path.join(settings.BASE_DIR, 'ssl', 'localhost+2.pem')
KEY_FILE = os.path.join(settings.BASE_DIR, 'ssl', 'localhost+2-key.pem')

# Check if certificates exist
if not os.path.exists(CERT_FILE) or not os.path.exists(KEY_FILE):
    print("SSL certificates not found. Generating...")
    import subprocess
    subprocess.run(['mkdir', '-p', 'ssl'])
    subprocess.run(['mkcert', '-install'])
    result = subprocess.run(
        ['mkcert', 'localhost', '127.0.0.1', '::1'],
        cwd=os.path.join(settings.BASE_DIR, 'ssl')
    )
    if result.returncode != 0:
        print("Failed to generate SSL certificates. Please run: mkcert localhost 127.0.0.1 ::1")
        sys.exit(1)

print(f"Starting HTTPS server at https://localhost:8000")
print(f"Using certificate: {CERT_FILE}")

# Run Django with SSL
call_command(
    'runserver',
    '0.0.0.0:8000',
    '--cert-file', CERT_FILE,
    '--key-file', KEY_FILE
)
