# Siloq Backend

Django REST Framework backend for the Siloq WordPress SEO dashboard platform.

## Quick Start

```bash
# Setup
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Environment
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

# Google OAuth (optional)
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret
FRONTEND_URL=http://localhost:3000
```

## Features

- **JWT Authentication** - Token-based auth with SimpleJWT
- **Google OAuth** - One-click login via Google
- **Multi-Site Management** - Users manage multiple WordPress sites
- **API Key Authentication** - Secure keys for WordPress plugin integration
- **Page Sync** - Sync WordPress pages with metadata
- **SEO Analytics** - Store and analyze SEO metrics
- **Lead Gen Scanner** - Website scanning and reporting

## API Endpoints

### Authentication
| Method | Endpoint | Auth |
|--------|----------|------|
| POST | `/api/v1/auth/login/` | - |
| POST | `/api/v1/auth/register/` | - |
| POST | `/api/v1/auth/logout/` | JWT |
| GET | `/api/v1/auth/me/` | JWT |
| GET | `/api/v1/auth/google/login/` | - |

### Sites & API Keys
| Method | Endpoint | Auth |
|--------|----------|------|
| GET | `/api/v1/sites/` | JWT |
| POST | `/api/v1/sites/` | JWT |
| GET | `/api/v1/sites/{id}/overview/` | JWT |
| GET | `/api/v1/api-keys/` | JWT |
| POST | `/api/v1/api-keys/` | JWT |

### WordPress Integration
| Method | Endpoint | Auth |
|--------|----------|------|
| POST | `/api/v1/auth/verify` | API Key |
| POST | `/api/v1/pages/sync/` | API Key |
| POST | `/api/v1/pages/{id}/seo-data/` | API Key |
| POST | `/api/v1/scans/` | API Key |

## Authentication Examples

### JWT Login
```bash
curl -X POST http://localhost:8000/api/v1/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "password123"}'
```

### WordPress Plugin
```bash
curl -X POST http://localhost:8000/api/v1/pages/sync/ \
  -H "Authorization: Bearer sk_siloq_xxx" \
  -H "Content-Type: application/json" \
  -d '{"wp_post_id": 123, "url": "...", "title": "..."}'
```

## Project Structure

```
siloq-backend/
├── accounts/          # User auth (JWT, OAuth)
├── sites/             # Site & API key management
├── seo/               # Page & SEO data
├── integrations/      # WordPress plugin endpoints
└── siloq_backend/     # Project settings
```

## Testing

```bash
pytest
```

## Tech Stack

- Django 5.0 + Django REST Framework
- PostgreSQL
- JWT (SimpleJWT) + Google OAuth2
- pytest

## License

Proprietary
