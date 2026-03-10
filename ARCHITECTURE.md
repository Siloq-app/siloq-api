# Siloq Backend Architecture

## Overview

The Siloq Django backend is designed as a RESTful API service that powers the dashboard frontend and integrates with WordPress sites via a plugin.

## System Architecture

```
┌─────────────────┐         ┌──────────────────┐         ┌─────────────────┐
│                 │         │                  │         │                 │
│ siloq-dashboard │────────▶│  Django Backend  │◀────────│ siloq-wordpress│
│   (Next.js)     │  JWT    │   (Django/DRF)   │  API    │    (Plugin)    │
│                 │         │                  │  Key    │                 │
└─────────────────┘         └──────────────────┘         └─────────────────┘
                                      │
                                      │
                              ┌───────▼───────┐
                              │  PostgreSQL   │
                              │   Database    │
                              └───────────────┘
```

## Django App Structure

### 1. accounts
**Purpose:** User authentication and management

**Models:**
- `User`: Custom user model extending AbstractUser

**Key Features:**
- JWT-based authentication
- Email as username
- User registration/login/logout

**Endpoints:**
- `POST /api/v1/auth/login` - Login
- `POST /api/v1/auth/logout` - Logout
- `GET /api/v1/auth/me` - Get current user

### 2. sites
**Purpose:** Site and API key management

**Models:**
- `Site`: WordPress website connected to a user
- `APIKey`: Secure API keys for WordPress plugin authentication

**Key Features:**
- One user can have multiple sites
- API keys are hashed (SHA-256) before storage
- API keys are site-specific
- Usage tracking (last_used_at, usage_count)
- Key rotation support (revoke/regenerate)

**Endpoints:**
- `GET /api/v1/sites/` - List sites
- `POST /api/v1/sites/` - Create site
- `GET /api/v1/sites/{id}/overview/` - Site overview
- `GET /api/v1/api-keys/` - List API keys
- `POST /api/v1/api-keys/` - Create API key
- `DELETE /api/v1/api-keys/{id}/` - Revoke API key

### 3. seo
**Purpose:** Page and SEO metrics storage

**Models:**
- `Page`: WordPress pages/posts synced from WordPress
- `SEOData`: Comprehensive SEO metrics and analysis

**Key Features:**
- Stores page content, metadata, WordPress-specific data
- Comprehensive SEO analysis (titles, meta, headings, links, images)
- SEO scoring (0-100)
- Issue tracking and recommendations
- One-to-one relationship: Page → SEOData

**Endpoints:**
- `GET /api/v1/pages/` - List pages
- `GET /api/v1/pages/{id}/` - Get page details
- `GET /api/v1/pages/{id}/seo/` - Get SEO data

### 4. integrations
**Purpose:** WordPress plugin integration endpoints

**Models:**
- `Scan`: Website scans from lead gen scanner

**Key Features:**
- Custom API key authentication
- Page synchronization from WordPress
- SEO data synchronization
- Website scanning for lead generation

**Endpoints:**
- `POST /api/v1/auth/verify` - Verify API key
- `POST /api/v1/pages/sync` - Sync page from WordPress
- `POST /api/v1/pages/{id}/seo-data/` - Sync SEO data
- `POST /api/v1/scans` - Create scan
- `GET /api/v1/scans/{id}` - Get scan status
- `GET /api/v1/scans/{id}/report` - Get full report

## Database Schema

### Entity Relationships

```
User
 ├── Site (1:N)
 │    ├── APIKey (1:N)
 │    ├── Page (1:N)
 │    │    └── SEOData (1:1)
 │    └── Scan (1:N)
```

### Key Tables

**users**
- id, email, username, password, created_at, updated_at

**sites**
- id, user_id, name, url, is_active, last_synced_at, created_at, updated_at

**api_keys**
- id, site_id, name, key_hash, key_prefix, is_active, expires_at, last_used_at, usage_count, created_at, revoked_at

**pages**
- id, site_id, wp_post_id, url, title, content, status, published_at, modified_at, yoast_title, yoast_description, created_at, updated_at

**seo_data**
- id, page_id, meta_title, meta_description, h1_count, h1_text, h2_texts (JSON), internal_links (JSON), images (JSON), seo_score, issues (JSON), recommendations (JSON), scanned_at

**scans**
- id, site_id, url, scan_type, status, score, pages_analyzed, results (JSON), created_at, completed_at

## Authentication Flow

### Dashboard Users

1. User logs in with email/password
2. Backend validates credentials
3. Backend generates JWT token
4. Frontend stores token
5. Frontend sends token in `Authorization: Bearer <token>` header
6. Backend validates token on each request

### WordPress Plugin

1. User generates API key in dashboard for a site
2. User copies API key to WordPress plugin settings
3. Plugin stores API key in WordPress options
4. Plugin sends API key in `Authorization: Bearer <key>` header
5. Backend hashes key and looks up in database
6. Backend validates key and returns site context
7. Plugin uses site context for subsequent requests

## Security Features

### API Key Security

- **Hashing**: Keys are hashed using SHA-256 before storage
- **Never Exposed**: Full keys are only shown once during creation
- **Prefix Display**: Only first 16 characters shown in lists
- **Revocation**: Keys can be revoked (soft delete)
- **Expiration**: Optional expiration date support
- **Usage Tracking**: Track when and how often keys are used

### JWT Security

- **Token Expiration**: Access tokens expire after 7 days
- **Refresh Tokens**: Refresh tokens expire after 30 days
- **Token Rotation**: Refresh tokens rotate on use
- **Blacklisting**: Revoked tokens are blacklisted

### Permissions

- **User Isolation**: Users can only access their own sites/data
- **Site Scoping**: API keys are scoped to specific sites
- **Object-Level Permissions**: Custom permissions ensure data isolation

## Data Flow

### Page Synchronization Flow

1. WordPress plugin detects page publish/update
2. Plugin calls `POST /api/v1/pages/sync` with page data
3. Backend validates API key and identifies site
4. Backend creates/updates Page record
5. Backend updates site's `last_synced_at`
6. Backend returns page_id

### SEO Data Flow

1. WordPress plugin scans page for SEO metrics
2. Plugin calls `POST /api/v1/pages/{id}/seo-data/` with SEO data
3. Backend validates API key and page ownership
4. Backend creates/updates SEOData record
5. Backend calculates/updates SEO score
6. Backend stores issues and recommendations

### Dashboard Data Flow

1. User logs into dashboard
2. Dashboard calls `GET /api/v1/sites/` to list sites
3. Dashboard calls `GET /api/v1/sites/{id}/overview/` for health scores
4. Dashboard calls `GET /api/v1/pages/?site_id={id}` to list pages
5. Dashboard calls `GET /api/v1/pages/{id}/` for page details
6. Dashboard displays SEO metrics and issues

## Scalability Considerations

### Database

- **Indexes**: Key fields are indexed (site_id, wp_post_id, url, key_hash)
- **JSON Fields**: Used for flexible data (issues, recommendations, results)
- **Relationships**: Proper foreign keys with CASCADE deletes

### API Design

- **Pagination**: List endpoints support pagination
- **Filtering**: Pages can be filtered by site_id
- **Efficient Queries**: Uses select_related/prefetch_related where needed
- **Read-Only Views**: Dashboard views are read-only for pages

### Future Enhancements

- **Caching**: Add Redis caching for frequently accessed data
- **Async Tasks**: Use Celery for async scan processing
- **Rate Limiting**: Add rate limiting for API endpoints
- **Webhooks**: Add webhook support for real-time updates
- **Search**: Add full-text search for pages
- **Analytics**: Add analytics tracking for API usage

## Technology Stack

- **Framework**: Django 5.0
- **API**: Django REST Framework 3.14
- **Authentication**: djangorestframework-simplejwt 5.3
- **Database**: PostgreSQL 14+
- **CORS**: django-cors-headers 4.3

## Development Guidelines

### Code Organization

- **Apps**: Each app has clear responsibility
- **Models**: One model per file, clear relationships
- **Views**: Use ViewSets for CRUD, function views for custom actions
- **Serializers**: Separate serializers for create/list/detail
- **Permissions**: Custom permissions for access control

### Best Practices

- **Validation**: Use serializers for input validation
- **Error Handling**: Consistent error response format
- **Documentation**: Docstrings for all views and models
- **Security**: Never expose sensitive data in responses
- **Testing**: Write tests for critical paths (TODO)

## Deployment Considerations

### Environment Variables

- `SECRET_KEY`: Django secret key
- `DEBUG`: Debug mode (False in production)
- `ALLOWED_HOSTS`: Comma-separated list of allowed hosts
- `DB_*`: Database connection settings
- `CORS_ALLOWED_ORIGINS`: Allowed CORS origins

### Production Checklist

- [ ] Set `DEBUG=False`
- [ ] Configure proper `ALLOWED_HOSTS`
- [ ] Use environment variables for secrets
- [ ] Set up PostgreSQL with proper credentials
- [ ] Configure CORS for frontend domain
- [ ] Use production WSGI server (Gunicorn)
- [ ] Set up reverse proxy (Nginx)
- [ ] Enable HTTPS
- [ ] Set up monitoring and logging
- [ ] Configure database backups
- [ ] Add rate limiting
- [ ] Set up error tracking (Sentry)
