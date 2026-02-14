# Content Recommendations API

The Content Recommendations API powers the Content Hub, providing intelligent content suggestions and one-click generation for business owners.

## Endpoints

### 1. Get Content Recommendations

```
GET /api/v1/sites/{site_id}/content-recommendations/
```

Returns a prioritized list of recommended content pieces.

**Authentication:** Bearer token (user must own the site)

**Query Parameters:**
- `limit` (optional): Max number of recommendations (default: 10)
- `priority` (optional): Filter by priority (`high`, `medium`, or `low`)

**Response:**
```json
{
  "recommendations": [
    {
      "id": "rec_a1b2c3d4",
      "title": "Hail Damage Roof Repair",
      "silo": "Full Roofing System",
      "silo_id": 42,
      "reason": "No supporting content for \"Full Roofing System\" yet",
      "priority": "high",
      "content_type": "supporting_article",
      "estimated_searches": null
    }
  ],
  "total": 5,
  "site_id": 10
}
```

**Recommendation Logic:**

1. **Silo Gaps** (High Priority)
   - Identifies money pages with 0-3 supporting pages
   - Suggests related topics based on money page keywords

2. **Service Coverage** (High Priority)
   - Cross-references `site.primary_services` with existing page titles
   - Recommends pages for uncovered services

3. **Industry Standards** (Medium Priority)
   - Suggests common content types based on `site.business_type`
   - Templates: FAQ, cost guides, comparison articles, how-to guides

**Priority Levels:**
- `high`: Money page has 0-1 supporting pages OR primary service has no page
- `medium`: Money page has 2-3 supporting pages OR industry-standard topic missing
- `low`: Nice-to-have supplementary content

---

### 2. Generate Content from Recommendation

```
POST /api/v1/sites/{site_id}/content-recommendations/{rec_id}/generate/
```

Generates content for a specific recommendation using OpenAI.

**Authentication:** Bearer token (user must own the site)

**Request Body (optional):**
```json
{
  "custom_title": "Override the suggested title",
  "custom_topic": "Additional context for generation"
}
```

**Response:**
```json
{
  "recommendation_id": "rec_a1b2c3d4",
  "title": "Hail Damage Roof Repair: Complete Guide",
  "content": "<h2>What is Hail Damage?</h2>\n<p>...</p>",
  "meta_description": "Learn about hail damage roof repair...",
  "suggested_slug": "hail-damage-roof-repair",
  "word_count": 1250,
  "silo_id": 42,
  "status": "draft",
  "model_used": "gpt-4o-mini",
  "tokens_used": 2400
}
```

**Notes:**
- Uses existing `seo/content_generation.py` engine
- Content is optimized for the target silo/money page
- Returns JSON format ready for approval

---

### 3. Approve and Create Content

```
POST /api/v1/sites/{site_id}/content/approve/
```

Creates a new Page in the database as status='draft' and triggers a webhook to WordPress.

**Authentication:** Bearer token (user must own the site)

**Request Body:**
```json
{
  "title": "Hail Damage Roof Repair: Complete Guide",
  "content": "<h2>What is Hail Damage?</h2>\n<p>...</p>",
  "silo_id": 42,
  "meta_description": "Learn about hail damage roof repair...",
  "slug": "hail-damage-roof-repair"
}
```

**Required Fields:**
- `title`: Page title
- `content`: Page content (HTML)

**Optional Fields:**
- `silo_id`: Parent money page ID (for silo structure)
- `meta_description`: SEO meta description
- `slug`: URL slug (auto-generated from title if not provided)

**Response:**
```json
{
  "page_id": 123,
  "title": "Hail Damage Roof Repair: Complete Guide",
  "slug": "hail-damage-roof-repair",
  "url": "https://example.com/hail-damage-roof-repair/",
  "status": "draft",
  "silo_id": 42,
  "message": "Page created as draft. Sync with WordPress to publish."
}
```

**Notes:**
- Page is created with `status='draft'` and `wp_post_id=0`
- WordPress plugin should poll for new drafts or receive webhook
- In production, would trigger immediate WordPress API call to create draft post

---

## Example Workflow

### Frontend: Content Hub Dashboard

1. **Load Recommendations**
   ```javascript
   const response = await fetch('/api/v1/sites/10/content-recommendations/?limit=5');
   const { recommendations } = await response.json();
   
   // Display cards with title, reason, priority badge
   ```

2. **User Clicks "Generate"**
   ```javascript
   const recId = 'rec_a1b2c3d4';
   const response = await fetch(`/api/v1/sites/10/content-recommendations/${recId}/generate/`, {
     method: 'POST',
   });
   const draft = await response.json();
   
   // Show editor with title, content, meta description
   ```

3. **User Reviews and Approves**
   ```javascript
   const response = await fetch('/api/v1/sites/10/content/approve/', {
     method: 'POST',
     body: JSON.stringify({
       title: draft.title,
       content: draft.content,
       silo_id: draft.silo_id,
       meta_description: draft.meta_description,
     }),
   });
   const page = await response.json();
   
   // Show success: "Page created! Syncing with WordPress..."
   ```

---

## Security

- All endpoints require `IsAuthenticated` permission
- Site ownership verified: `site.user == request.user`
- Returns 403 Forbidden if user doesn't own the site
- Returns 404 Not Found for invalid site_id or rec_id

---

## Future Enhancements

1. **Async Generation**: Use Celery/RQ for long-running content generation
2. **Search Volume Data**: Integrate keyword research API for `estimated_searches`
3. **Recommendation Caching**: Cache recommendations for faster subsequent loads
4. **WordPress Integration**: Direct WordPress REST API calls on approval
5. **A/B Testing**: Track which recommendations convert best
6. **Custom Templates**: Allow users to create their own content templates
7. **Semantic Search**: Use embeddings to better detect service coverage gaps

---

## Testing

```bash
# Get recommendations
curl -X GET "http://localhost:8000/api/v1/sites/10/content-recommendations/" \
  -H "Authorization: Bearer <token>"

# Generate content
curl -X POST "http://localhost:8000/api/v1/sites/10/content-recommendations/rec_a1b2c3d4/generate/" \
  -H "Authorization: Bearer <token>"

# Approve content
curl -X POST "http://localhost:8000/api/v1/sites/10/content/approve/" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Test Page",
    "content": "<p>Test content</p>",
    "silo_id": 42
  }'
```
