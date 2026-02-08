# Siloq Backend

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-5.0-green.svg)](https://www.djangoproject.com/)
[![DRF](https://img.shields.io/badge/DRF-3.14+-red.svg)](https://www.django-rest-framework.org/)
[![License](https://img.shields.io/badge/License-Proprietary-lightgrey.svg)](LICENSE)

Django REST Framework backend for the Siloq WordPress SEO dashboard platform. Provides JWT authentication, multi-site management, API key authentication for WordPress plugins, and SEO analytics.

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Quick Start](#quick-start)
- [Environment Variables](#environment-variables)
- [API Documentation](#api-documentation)
- [Authentication](#authentication)
- [Development](#development)
- [Testing](#testing)
- [Security](#security)
- [Deployment](#deployment)

## Features

- **JWT Authentication** - Secure token-based auth with SimpleJWT (7-day access, 30-day refresh)
- **Google OAuth** - One-click login via Google accounts
- **Multi-Site Management** - Users can manage multiple WordPress sites
- **API Key Authentication** - Secure, rotatable keys for WordPress plugin integration
- **Page Sync** - Sync WordPress pages/posts with comprehensive metadata
- **SEO Analytics** - Store and analyze SEO metrics (titles, headings, links, images, scores)
- **Lead Gen Scanner** - Website scanning and reporting with status tracking

## Tech Stack

| Component | Technology |
|-----------|------------|
| Framework | Django 5.0 + Django REST Framework |
| Database | PostgreSQL |
| Authentication | JWT (SimpleJWT) + Google OAuth2 |
| Testing | pytest + pytest-django |
| Environment | python-dotenv |
| HTTP Client | requests |

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 14+
- Git

### Installation

```bash
# Setup
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your database credentials

# Database
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Environment Variables

```env
SECRET_KEY=your-secret-key
DEBUG=True
DB_NAME=siloq_db
DB_USER=postgres
DB_PASSWORD=postgres
DB_HOST=localhost
DB_PORT=5432

# Google OAuth (required for Google login)
GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-google-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/auth/google/callback/
FRONTEND_URL=http://localhost:3000
```

### Google OAuth Setup

1. Go to https://console.cloud.google.com/apis/credentials
2. Create a new project or select existing one
3. Click "Create Credentials" > "OAuth client ID"
4. Configure consent screen (External type for testing)
5. Application type: Web application
6. Add authorized redirect URI: `http://localhost:8000/api/v1/auth/google/callback/`
7. Copy Client ID and Client Secret to your `.env` file

## API Documentation

### Authentication Endpoints

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| POST | `/api/v1/auth/login/` | Email/password login | - |
| POST | `/api/v1/auth/register/` | User registration | - |
| POST | `/api/v1/auth/logout/` | Logout (blacklist token) | JWT |
| GET | `/api/v1/auth/me/` | Current user info | JWT |
| GET | `/api/v1/auth/google/login/` | Initiate Google OAuth | - |
| GET | `/api/v1/auth/google/callback/` | Google OAuth callback | - |
| POST | `/api/v1/token/refresh/` | Refresh access token | Refresh |

### Sites & API Keys

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/v1/sites/` | List user sites | JWT |
| POST | `/api/v1/sites/` | Create new site | JWT |
| GET | `/api/v1/sites/{id}/` | Site details | JWT |
| GET | `/api/v1/sites/{id}/overview/` | Site health score | JWT |
| GET | `/api/v1/api-keys/` | List API keys | JWT |
| POST | `/api/v1/api-keys/` | Create API key | JWT |
| DELETE | `/api/v1/api-keys/{id}/` | Revoke API key | JWT |

### Pages & SEO

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/v1/pages/` | List pages (filter by `site_id`) | JWT |
| GET | `/api/v1/pages/{id}/` | Page details | JWT |
| GET | `/api/v1/pages/{id}/seo/` | SEO data | JWT |

### WordPress Integration (API Key Auth)

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| POST | `/api/v1/auth/verify` | Verify API key | API Key |
| POST | `/api/v1/pages/sync/` | Sync page from WordPress | API Key |
| POST | `/api/v1/pages/{id}/seo-data/` | Sync SEO data | API Key |
| POST | `/api/v1/scans/` | Create scan | API Key |
| GET | `/api/v1/scans/{id}/` | Get scan status | API Key |
| GET | `/api/v1/scans/{id}/report/` | Get scan report | API Key |

## Authentication

### JWT Dashboard Authentication

```bash
# Login
curl -X POST http://localhost:8000/api/v1/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "securepassword123"
  }'

# Response: {"access": "...", "refresh": "...", "user": {...}}

# Use access token for subsequent requests
curl -X GET http://localhost:8000/api/v1/auth/me/ \
  -H "Authorization: Bearer <access_token>"
```

### WordPress Plugin Authentication

```bash
# Sync page from WordPress plugin
curl -X POST http://localhost:8000/api/v1/pages/sync/ \
  -H "Authorization: Bearer sk_siloq_xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "wp_post_id": 123,
    "url": "https://example.com/page",
    "title": "Page Title",
    "site_id": 1
  }'
```

## Development

### Project Structure

```
siloq-backend/
├── accounts/              # User authentication
│   ├── auth.py           # JWT login/register/logout
│   └── oauth.py          # Google OAuth flow
├── sites/                 # Site & API key management
│   ├── sites.py          # Site CRUD operations
│   └── api_keys.py       # API key management
├── seo/                   # Page & SEO data
│   ├── models.py         # Page, SEOData models
│   └── views.py          # PageViewSet
├── integrations/          # WordPress plugin endpoints
│   ├── sync.py           # Page/SEO sync endpoints
│   └── scans.py          # Scanner endpoints
└── siloq_backend/         # Project settings
```

### Code Style

- Follow PEP 8
- Use type hints where appropriate
- Write docstrings for functions and classes
- Keep modules focused and small

## Testing

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific app tests
pytest accounts/tests.py
pytest sites/tests.py
pytest integrations/tests.py

# Run with coverage
pytest --cov=siloq_backend --cov-report=html
```

### Test Configuration

Tests use SQLite in-memory database for speed. Configuration in `pytest.ini`:

```ini
[pytest]
DJANGO_SETTINGS_MODULE = siloq_backend.test_settings
python_files = tests.py test_*.py
```

## Security

- **API Keys** - SHA-256 hashed, never stored plaintext
- **JWT Tokens** - Short-lived access tokens (7 days), refresh tokens (30 days) with rotation
- **User Isolation** - Users can only access their own sites and data
- **Key Rotation** - API keys can be revoked and regenerated instantly
- **OAuth Security** - State validation, secure redirect URI validation

## Deployment

### Production Checklist

1. Set `DEBUG=False`
2. Configure `ALLOWED_HOSTS` with your domain
3. Use strong `SECRET_KEY` from environment variable
4. Enable HTTPS only
5. Set up PostgreSQL with SSL
6. Configure CORS for production frontend URL
7. Set up Gunicorn + Nginx
8. Enable request logging and monitoring

### DigitalOcean App Platform

See `DEPLOYMENT_DIGITALOCEAN.md` for detailed deployment instructions.

```bash
# Quick deploy
git push origin main
```

## License

Proprietary - All rights reserved.

---

**Support:** For issues or questions, contact the development team.
