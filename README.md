# Siloq Backend

Django REST Framework backend for the Siloq WordPress SEO dashboard platform.

## Features

- **JWT Authentication** - Secure token-based auth for dashboard users
- **Multi-Site Management** - Users can manage multiple WordPress sites
- **API Key Authentication** - Secure, rotatable keys for WordPress plugin integration
- **Page Sync** - Sync WordPress pages/posts with comprehensive metadata
- **SEO Analytics** - Store and analyze SEO metrics (titles, headings, links, images, scores)
- **Lead Gen Scanner** - Website scanning and reporting

## Architecture

```
siloq-backend/
├── accounts/          # User authentication (JWT)
├── sites/             # Site & API key management
├── seo/               # Page & SEO data storage
└── integrations/      # WordPress plugin endpoints
```

**Models:** User → Site → (APIKey, Page, Scan) → Page → SEOData

## Quick Start

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

## API Endpoints

### Authentication (JWT)
- `POST /api/v1/auth/login` - Login
- `POST /api/v1/auth/logout` - Logout
- `GET /api/v1/auth/me` - Current user

### Sites & API Keys
- `GET/POST /api/v1/sites/` - List/Create sites
- `GET /api/v1/sites/{id}/overview/` - Site health score
- `GET/POST /api/v1/api-keys/` - List/Create API keys

### Pages & SEO
- `GET /api/v1/pages/?site_id={id}` - List pages
- `GET /api/v1/pages/{id}/` - Page details
- `GET /api/v1/pages/{id}/seo/` - SEO data

### WordPress Plugin (API Key Auth)
- `POST /api/v1/auth/verify` - Verify API key
- `POST /api/v1/pages/sync/` - Sync page
- `POST /api/v1/pages/{id}/seo-data/` - Sync SEO data
- `POST /api/v1/scans/` - Create scan

## Authentication

### Dashboard (JWT)
```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "password123"}'
# Use returned token: Authorization: Bearer <token>
```

### WordPress Plugin (API Key)
```bash
curl -X POST http://localhost:8000/api/v1/pages/sync/ \
  -H "Authorization: Bearer sk_siloq_xxx" \
  -H "Content-Type: application/json" \
  -d '{"wp_post_id": 123, "url": "...", "title": "..."}'
```

## Security Features

- **API Keys** - SHA-256 hashed, never stored plaintext
- **JWT** - 7-day access tokens, 30-day refresh tokens with rotation
- **User Isolation** - Users can only access their own sites/data
- **Key Rotation** - Keys can be revoked and regenerated

## Production Deployment

1. Set `DEBUG=False`
2. Configure `ALLOWED_HOSTS`
3. Use environment variables for secrets
4. Enable HTTPS
5. Use Gunicorn + Nginx

## License

Proprietary
