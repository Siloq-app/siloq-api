# Siloq Backend API Reference

Complete API reference for the Siloq Django backend.

## Base URL

```
http://localhost:8000/api/v1
```

## Authentication

### Dashboard Users (JWT)

1. Login to get JWT token:
```bash
POST /api/v1/auth/login
```

2. Use token in Authorization header:
```
Authorization: Bearer <jwt_token>
```

### WordPress Plugin (API Keys)

Use API key in Authorization header:
```
Authorization: Bearer sk_siloq_xxx
```

Or use X-API-Key header:
```
X-API-Key: sk_siloq_xxx
```

---

## Dashboard API Endpoints

### Authentication

#### Login
```http
POST /api/v1/auth/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "password123"
}
```

**Response:**
```json
{
  "message": "Login successful",
  "token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "user": {
    "id": 1,
    "email": "user@example.com",
    "username": "user",
    "created_at": "2024-01-01T00:00:00Z"
  }
}
```

#### Logout
```http
POST /api/v1/auth/logout
Authorization: Bearer <jwt_token>
Content-Type: application/json

{
  "refresh_token": "refresh_token_here"
}
```

**Response:**
```json
{
  "message": "Logged out successfully"
}
```

#### Get Current User
```http
GET /api/v1/auth/me
Authorization: Bearer <jwt_token>
```

**Response:**
```json
{
  "user": {
    "id": 1,
    "email": "user@example.com",
    "username": "user",
    "created_at": "2024-01-01T00:00:00Z"
  }
}
```

---

### API Keys

#### List API Keys
```http
GET /api/v1/api-keys/
Authorization: Bearer <jwt_token>
```

**Response:**
```json
{
  "count": 2,
  "results": [
    {
      "id": 1,
      "name": "Production Site Key",
      "key_prefix": "sk_siloq_AbCd...",
      "is_active": true,
      "created_at": "2024-01-01T00:00:00Z",
      "last_used_at": "2024-01-02T00:00:00Z",
      "usage_count": 42
    }
  ]
}
```

#### Create API Key
```http
POST /api/v1/api-keys/
Authorization: Bearer <jwt_token>
Content-Type: application/json

{
  "name": "Production Site Key",
  "site_id": 1
}
```

**Response:**
```json
{
  "message": "API key created successfully",
  "key": {
    "id": 1,
    "name": "Production Site Key",
    "key": "sk_siloq_AbCdEf123456...",
    "key_prefix": "sk_siloq_AbCd...",
    "created_at": "2024-01-01T00:00:00Z",
    "is_active": true
  }
}
```

**Note:** The full key is only shown once. Store it securely.

#### Revoke API Key
```http
DELETE /api/v1/api-keys/{id}/
Authorization: Bearer <jwt_token>
```

**Response:**
```json
{
  "message": "API key revoked successfully"
}
```

---

### Sites

#### List Sites
```http
GET /api/v1/sites/
Authorization: Bearer <jwt_token>
```

**Response:**
```json
{
  "count": 2,
  "results": [
    {
      "id": 1,
      "name": "My WordPress Site",
      "url": "https://example.com",
      "is_active": true,
      "page_count": 25,
      "api_key_count": 1,
      "last_synced_at": "2024-01-02T00:00:00Z",
      "created_at": "2024-01-01T00:00:00Z"
    }
  ]
}
```

#### Create Site
```http
POST /api/v1/sites/
Authorization: Bearer <jwt_token>
Content-Type: application/json

{
  "name": "My WordPress Site",
  "url": "https://example.com"
}
```

**Response:**
```json
{
  "id": 1,
  "name": "My WordPress Site",
  "url": "https://example.com",
  "is_active": true,
  "page_count": 0,
  "api_key_count": 0,
  "created_at": "2024-01-01T00:00:00Z"
}
```

#### Get Site Details
```http
GET /api/v1/sites/{id}/
Authorization: Bearer <jwt_token>
```

**Response:** Same as Create Site response

#### Get Site Overview
```http
GET /api/v1/sites/{id}/overview/
Authorization: Bearer <jwt_token>
```

**Response:**
```json
{
  "site_id": 1,
  "site_name": "My WordPress Site",
  "health_score": 72.5,
  "total_pages": 25,
  "total_issues": 15,
  "last_synced_at": "2024-01-02T00:00:00Z"
}
```

---

### Pages

#### List Pages
```http
GET /api/v1/pages/?site_id=1
Authorization: Bearer <jwt_token>
```

**Response:**
```json
{
  "count": 25,
  "results": [
    {
      "id": 1,
      "url": "https://example.com/my-page",
      "title": "My Page",
      "status": "publish",
      "published_at": "2024-01-01T00:00:00Z",
      "last_synced_at": "2024-01-02T00:00:00Z",
      "seo_score": 85,
      "issue_count": 2
    }
  ]
}
```

#### Get Page Details
```http
GET /api/v1/pages/{id}/
Authorization: Bearer <jwt_token>
```

**Response:**
```json
{
  "id": 1,
  "site": {
    "id": 1,
    "name": "My WordPress Site",
    "url": "https://example.com"
  },
  "wp_post_id": 123,
  "url": "https://example.com/my-page",
  "title": "My Page",
  "content": "Page content...",
  "status": "publish",
  "seo_data": {
    "id": 1,
    "meta_title": "SEO Title",
    "meta_description": "SEO Description",
    "h1_count": 1,
    "h1_text": "Main Heading",
    "seo_score": 85,
    "issues": [
      {
        "type": "missing_meta_description",
        "severity": "high",
        "message": "Missing meta description"
      }
    ],
    "scanned_at": "2024-01-02T00:00:00Z"
  }
}
```

#### Get Page SEO Data
```http
GET /api/v1/pages/{id}/seo/
Authorization: Bearer <jwt_token>
```

**Response:** Same as `seo_data` field in Page Details response

---

## WordPress Plugin API Endpoints

### Verify API Key
```http
POST /api/v1/auth/verify
Authorization: Bearer sk_siloq_xxx
```

**Response:**
```json
{
  "valid": true,
  "site_id": 1,
  "site_name": "My WordPress Site",
  "site_url": "https://example.com"
}
```

### Sync Page
```http
POST /api/v1/pages/sync
Authorization: Bearer sk_siloq_xxx
Content-Type: application/json

{
  "wp_post_id": 123,
  "url": "https://example.com/my-page",
  "title": "My Page Title",
  "content": "Full page content...",
  "excerpt": "Page excerpt...",
  "status": "publish",
  "published_at": "2024-01-01T00:00:00Z",
  "modified_at": "2024-01-02T00:00:00Z",
  "slug": "my-page",
  "parent_id": null,
  "menu_order": 0,
  "yoast_title": "SEO Title",
  "yoast_description": "SEO Description",
  "featured_image": "https://example.com/image.jpg"
}
```

**Response:**
```json
{
  "page_id": 1,
  "message": "Page synced successfully",
  "created": true
}
```

### Sync SEO Data
```http
POST /api/v1/pages/{page_id}/seo-data/
Authorization: Bearer sk_siloq_xxx
Content-Type: application/json

{
  "meta_title": "Page Title",
  "meta_description": "Page description",
  "h1_count": 1,
  "h1_text": "Main Heading",
  "h2_count": 3,
  "h2_texts": ["Section 1", "Section 2"],
  "internal_links_count": 5,
  "external_links_count": 2,
  "images_count": 10,
  "images_without_alt": 2,
  "word_count": 1500,
  "seo_score": 85,
  "issues": [
    {
      "type": "missing_meta_description",
      "severity": "high",
      "message": "Missing meta description"
    }
  ],
  "recommendations": [
    "Add meta description",
    "Add alt text to images"
  ]
}
```

**Response:**
```json
{
  "seo_data_id": 1,
  "message": "SEO data synced successfully",
  "created": true
}
```

### Create Scan
```http
POST /api/v1/scans
Authorization: Bearer sk_siloq_xxx
Content-Type: application/json

{
  "url": "https://example.com",
  "scan_type": "full"
}
```

**Response:**
```json
{
  "id": 1,
  "url": "https://example.com",
  "status": "completed",
  "scan_type": "full",
  "score": 72,
  "pages_analyzed": 1,
  "scan_duration_seconds": 2.5,
  "results": {
    "technical_score": 80,
    "content_score": 70,
    "seo_score": 72,
    "issues": [...],
    "recommendations": [...]
  },
  "created_at": "2024-01-01T00:00:00Z"
}
```

### Get Scan Status
```http
GET /api/v1/scans/{scan_id}
Authorization: Bearer sk_siloq_xxx
```

**Response:** Same as Create Scan response

### Get Scan Report
```http
GET /api/v1/scans/{scan_id}/report
Authorization: Bearer sk_siloq_xxx
```

**Response:**
```json
{
  "scan_id": 1,
  "url": "https://example.com",
  "score": 72,
  "pages_analyzed": 1,
  "scan_duration_seconds": 2.5,
  "completed_at": "2024-01-01T00:00:00Z",
  "results": {
    "technical_score": 80,
    "content_score": 70,
    "seo_score": 72,
    "issues": [...],
    "recommendations": [...]
  },
  "keyword_cannibalization": {
    "issues_found": 2,
    "recommendations": [...]
  }
}
```

---

## Error Responses

All endpoints may return error responses:

**400 Bad Request:**
```json
{
  "error": "Invalid request data",
  "detail": {
    "field_name": ["Error message"]
  }
}
```

**401 Unauthorized:**
```json
{
  "detail": "Invalid API key"
}
```

**404 Not Found:**
```json
{
  "detail": "Not found."
}
```

**500 Internal Server Error:**
```json
{
  "error": "Internal server error"
}
```

---

## Pagination

List endpoints support pagination:

```http
GET /api/v1/pages/?page=2&page_size=20
```

**Response:**
```json
{
  "count": 100,
  "next": "http://localhost:8000/api/v1/pages/?page=3",
  "previous": "http://localhost:8000/api/v1/pages/?page=1",
  "results": [...]
}
```

---

## Filtering

### Pages by Site
```http
GET /api/v1/pages/?site_id=1
```

### Sites (automatic - only user's sites)

---

## Rate Limiting

Currently no rate limiting implemented. Consider adding in production.

---

## CORS

CORS is configured for:
- `http://localhost:3000`
- `http://127.0.0.1:3000`

Update `CORS_ALLOWED_ORIGINS` in settings for production.
