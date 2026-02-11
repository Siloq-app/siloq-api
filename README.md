# Siloq Backend

Django REST API powering Siloq — a WordPress SEO dashboard for site management, SEO analytics, and WordPress plugin integration.

## Quick Start

```bash
# Setup
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Environment
cp .env.example .env
# Edit .env with your configuration

# Database & Server
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

# Google OAuth
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/auth/google/callback/

# Frontend
FRONTEND_URL=http://localhost:3000

# Stripe (optional)
STRIPE_SECRET_KEY=sk_test_xxx
```

## Features

- **Authentication** — JWT tokens, Google OAuth
- **Site Management** — Multi-site dashboard with API key generation
- **SEO Analytics** — Cannibalization detection, silo analysis
- **WordPress Integration** — REST API endpoints for plugin communication
- **Billing** — Stripe subscriptions with trial periods

## API Documentation

### Authentication

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/v1/auth/register/` | POST | - | Register new user |
| `/api/v1/auth/login/` | POST | - | Login (returns JWT) |
| `/api/v1/auth/google/login/` | GET | - | Google OAuth redirect |
| `/api/v1/auth/google/callback/` | GET | - | Google OAuth callback |
| `/api/v1/auth/me/` | GET | JWT | Get current user |

### Sites & API Keys

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/v1/sites/` | GET, POST | JWT | List / create sites |
| `/api/v1/sites/{id}/overview/` | GET | JWT | Site overview |
| `/api/v1/api-keys/` | GET, POST | JWT | Manage API keys |

### SEO & Integrations

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/v1/seo/health/` | GET | API Key | Site health check |
| `/api/v1/seo/cannibalization/` | GET | API Key | Cannibalization issues |
| `/api/v1/seo/silos/` | GET | API Key | Silo structure analysis |
| `/api/v1/integrations/pages/sync/` | POST | API Key | Sync WordPress pages |

## Architecture

```
siloq-backend/
├── accounts/          # Custom user model, JWT, OAuth
├── billing/           # Stripe subscriptions & usage tracking
├── integrations/      # WordPress plugin endpoints
├── seo/               # SEO analysis models & logic
├── sites/             # Site & API key management
└── siloq_backend/     # Project settings
```

## Testing

```bash
pytest
```

## Stack

- Django 5 + Django REST Framework
- PostgreSQL
- JWT (djangorestframework-simplejwt)
- Google OAuth2
- Stripe API
- pytest

## License

Proprietary — All rights reserved.
