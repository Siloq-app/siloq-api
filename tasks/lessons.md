# tasks/lessons.md — Siloq API Lessons Learned

## Lesson 14 — Entity Extraction Coordination
Multiple agents creating migrations independently pick duplicate numbers. Always check the highest existing migration in `seo/migrations/` before naming a new one. Use `0016_` only if `0015_` is the current max.

## Lesson 15 — No-Op Migrations Are Valid
When a table already exists from a prior deploy, use `operations = []` in the migration. Don't try to create it again.

## Lesson 16 — Pre-Merge Migration Audit Required
Always check the release branch migration numbers before merging any agent branch. Parallel agents will pick the same migration numbers independently.

## Lesson 17 — Parallel Agent Integration = Cascading Failures
Multiple agents building independently from the same base branch all pick duplicate migration numbers, duplicate model definitions, and conflicting URL patterns. Coordinate merge order and check for conflicts before each merge.

## Lesson 18 — Gunicorn Timeout for AI Endpoints
The default Gunicorn timeout is 30s. AI analysis calls (GSC fetch + WP fetch + Claude API) take 30-60s. Always set `--timeout 120` minimum for any app running AI endpoints.

## Lesson 19 — Next.js Proxy Routes Must Match API Endpoints
Every backend API endpoint called from the dashboard frontend needs a corresponding Next.js proxy route file at `app/api/v1/...`. Missing proxy routes cause "Failed to fetch" errors in the browser. Check for missing routes before debugging backend.

## Lesson 20 — NEVER GENERATE FAKE TESTIMONIALS OR REVIEWS
CRO recommendations were generating fabricated customer quotes with fake names (e.g., "Jane D."). This is a legal liability for customers. All testimonials and social proof content must come from real review sources (GBP via Places API, on-site reviews) or be omitted with a clear prompt to connect the review source. The AI system prompt now explicitly prohibits this.

## Lesson 21 — API Response Shape Must Match Frontend Type Definitions
When the frontend TypeScript interface defines `geo_score`, `overall_score` etc. as top-level fields, the API serializer must return them at the top level — not nested inside a `scores: {}` object. Always cross-reference the TypeScript interface when building serializers.

## Lesson 22 — WP Plugin Event Types Must Be Registered
Sending an unregistered event type to the WordPress webhook endpoint (e.g., `content.apply_optimization`) silently returns a 400. The API response was not being checked, so the dashboard showed "Applied" when nothing happened. Always match event type strings to the plugin's `route_event()` switch statement.
