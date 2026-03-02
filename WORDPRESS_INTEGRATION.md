# WordPress Plugin Integration Guide

This document explains how the WordPress plugin should integrate with the Django backend.

## Authentication

The WordPress plugin authenticates using API keys generated in the dashboard.

### API Key Format

- Prefix: `sk_siloq_`
- Format: `sk_siloq_<random_token>`
- Example: `sk_siloq_AbCdEf123456...`

### Authentication Headers

The plugin can send the API key in two ways:

1. **Authorization Header (Preferred):**
```
Authorization: Bearer sk_siloq_xxx
```

2. **X-API-Key Header:**
```
X-API-Key: sk_siloq_xxx
```

## Endpoints

### 1. Verify API Key

**Endpoint:** `POST /api/v1/auth/verify`

**Headers:**
```
Authorization: Bearer sk_siloq_xxx
Content-Type: application/json
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

**Usage:** Call this when user clicks "Test Connection" in WordPress admin.

### 2. Sync Page

**Endpoint:** `POST /api/v1/pages/sync`

**Headers:**
```
Authorization: Bearer sk_siloq_xxx
Content-Type: application/json
```

**Request Body:**
```json
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

**Usage:** Call this when:
- A page/post is published or updated (if auto-sync enabled)
- User manually clicks "Sync to Siloq" button
- Bulk sync all pages

### 3. Sync SEO Data

**Endpoint:** `POST /api/v1/pages/{page_id}/seo-data/`

**Headers:**
```
Authorization: Bearer sk_siloq_xxx
Content-Type: application/json
```

**Request Body:**
```json
{
  "meta_title": "Page Title",
  "meta_description": "Page description",
  "h1_count": 1,
  "h1_text": "Main Heading",
  "h2_count": 3,
  "h2_texts": ["Section 1", "Section 2", "Section 3"],
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

**Usage:** Call this after scanning a page for SEO metrics.

### 4. Create Scan (Lead Gen Scanner)

**Endpoint:** `POST /api/v1/scans`

**Headers:**
```
Authorization: Bearer sk_siloq_xxx
Content-Type: application/json
```

**Request Body:**
```json
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
  "status": "pending",
  "scan_type": "full",
  "created_at": "2024-01-01T00:00:00Z"
}
```

**Usage:** Call this when user submits website URL in lead gen scanner.

### 5. Get Scan Status

**Endpoint:** `GET /api/v1/scans/{scan_id}`

**Headers:**
```
Authorization: Bearer sk_siloq_xxx
```

**Response:**
```json
{
  "id": 1,
  "url": "https://example.com",
  "status": "completed",
  "score": 72,
  "pages_analyzed": 1,
  "scan_duration_seconds": 2.5,
  "results": {
    "technical_score": 80,
    "content_score": 70,
    "seo_score": 72,
    "issues": [...],
    "recommendations": [...]
  }
}
```

**Usage:** Poll this endpoint to check scan status (pending → processing → completed).

### 6. Get Full Scan Report

**Endpoint:** `GET /api/v1/scans/{scan_id}/report`

**Headers:**
```
Authorization: Bearer sk_siloq_xxx
```

**Response:**
```json
{
  "scan_id": 1,
  "url": "https://example.com",
  "score": 72,
  "pages_analyzed": 1,
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

**Usage:** Call this when user requests full report after viewing teaser results.

## Error Handling

All endpoints return standard HTTP status codes:

- `200 OK` - Success
- `201 Created` - Resource created
- `400 Bad Request` - Invalid request data
- `401 Unauthorized` - Invalid or missing API key
- `404 Not Found` - Resource not found
- `500 Internal Server Error` - Server error

Error response format:
```json
{
  "error": "Error message",
  "detail": "Detailed error information"
}
```

## Implementation Example (PHP)

```php
class Siloq_API_Client {
    private $api_url;
    private $api_key;
    
    public function __construct($api_url, $api_key) {
        $this->api_url = rtrim($api_url, '/');
        $this->api_key = $api_key;
    }
    
    private function make_request($method, $endpoint, $data = []) {
        $url = $this->api_url . $endpoint;
        
        $args = [
            'method' => $method,
            'headers' => [
                'Authorization' => 'Bearer ' . $this->api_key,
                'Content-Type' => 'application/json',
            ],
            'timeout' => 30,
        ];
        
        if (!empty($data)) {
            $args['body'] = json_encode($data);
        }
        
        $response = wp_remote_request($url, $args);
        
        if (is_wp_error($response)) {
            return $response;
        }
        
        $status_code = wp_remote_retrieve_response_code($response);
        $body = json_decode(wp_remote_retrieve_body($response), true);
        
        if ($status_code >= 200 && $status_code < 300) {
            return $body;
        }
        
        return new WP_Error('api_error', $body['error'] ?? 'API request failed', ['status' => $status_code]);
    }
    
    public function verify_api_key() {
        return $this->make_request('POST', '/api/v1/auth/verify');
    }
    
    public function sync_page($post_id) {
        $post = get_post($post_id);
        if (!$post) {
            return new WP_Error('invalid_post', 'Post not found');
        }
        
        $data = [
            'wp_post_id' => $post->ID,
            'url' => get_permalink($post->ID),
            'title' => $post->post_title,
            'content' => $post->post_content,
            'excerpt' => $post->post_excerpt,
            'status' => $post->post_status,
            'published_at' => $post->post_date_gmt,
            'modified_at' => $post->post_modified_gmt,
            'slug' => $post->post_name,
            'yoast_title' => get_post_meta($post->ID, '_yoast_wpseo_title', true),
            'yoast_description' => get_post_meta($post->ID, '_yoast_wpseo_metadesc', true),
            'featured_image' => get_the_post_thumbnail_url($post->ID, 'full'),
        ];
        
        return $this->make_request('POST', '/api/v1/pages/sync', $data);
    }
    
    public function create_scan($url) {
        return $this->make_request('POST', '/api/v1/scans', [
            'url' => $url,
            'scan_type' => 'full',
        ]);
    }
    
    public function get_scan($scan_id) {
        return $this->make_request('GET', '/api/v1/scans/' . $scan_id);
    }
    
    public function get_scan_report($scan_id) {
        return $this->make_request('GET', '/api/v1/scans/' . $scan_id . '/report');
    }
}
```

## Testing

Use curl to test endpoints:

```bash
# Set API key
API_KEY="sk_siloq_xxx"
API_URL="http://localhost:8000/api/v1"

# Verify API key
curl -X POST "$API_URL/auth/verify" \
  -H "Authorization: Bearer $API_KEY"

# Sync page
curl -X POST "$API_URL/pages/sync" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "wp_post_id": 123,
    "url": "https://example.com/page",
    "title": "Test Page",
    "status": "publish"
  }'
```

## Notes

- API keys are site-specific. Each site has its own API keys.
- API keys are hashed and never returned in full after creation.
- The plugin should store the API key securely in WordPress options.
- Always use HTTPS in production.
- Implement retry logic for network errors.
- Cache scan results to avoid unnecessary API calls.
