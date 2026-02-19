"""
Page Content Optimization Views — Three-Layer Content Model (GEO + SEO + CRO).

Endpoints:
  POST   /api/v1/sites/{site_id}/pages/analyze/
  GET    /api/v1/sites/{site_id}/pages/analysis/
  GET    /api/v1/sites/{site_id}/pages/analysis/{analysis_id}/
  POST   /api/v1/sites/{site_id}/pages/analysis/{analysis_id}/approve/
  POST   /api/v1/sites/{site_id}/pages/analysis/{analysis_id}/apply/
"""

import json
import logging
import os
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from integrations.gsc import fetch_page_search_analytics
from integrations.gsc_views import _get_valid_access_token
from integrations.wordpress_webhook import send_webhook_to_wordpress
from seo.models import Page, PageAnalysis, SEOData
from sites.models import Site

logger = logging.getLogger(__name__)

# ── AI configuration ─────────────────────────────────────────────────────────

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
ANTHROPIC_MODEL = 'claude-sonnet-4-20250514'
OPENAI_MODEL = 'gpt-4o'
MAX_TOKENS = 4096

PAGE_ANALYSIS_SYSTEM_PROMPT = """You are Siloq's Content Optimization Engine. You analyze individual web pages against the Three-Layer Content Model and generate specific, actionable recommendations.

The Three-Layer Content Model:
1. GEO (Teachability) — Structure content so AI systems (ChatGPT, Gemini, Perplexity) will cite this page. Focus on: clear direct answers, named entity coverage, authoritative language, FAQ/HowTo structure opportunities.
2. SEO (Findability) — Optimize for traditional search rankings. Focus on: keyword targeting, title tag, meta description, H2 structure, word count, internal linking, schema markup.
3. CRO (Convertibility) — Convert visitors to customers/leads. Focus on: CTA placement, trust signals, pricing transparency, conversion path clarity, social proof.

For each layer, score the page 0-100 and provide specific recommendations.

RULES:
- Every recommendation must be specific and actionable — not "improve your content" but "add a paragraph answering 'how much does basement remodeling cost'"
- Recommendations must reference actual content from the page (the before/after fields)
- Prioritize recommendations by impact: high/medium/low
- Maximum 3 recommendations per layer (total 9 max)
- Only recommend things that will genuinely improve the page

OUTPUT FORMAT — respond with ONLY valid JSON:
{
  "geo_score": 0-100,
  "seo_score": 0-100,
  "cro_score": 0-100,
  "geo_recommendations": [
    {
      "id": "geo_1",
      "layer": "GEO",
      "priority": "high|medium|low",
      "issue": "What's wrong",
      "recommendation": "Specific fix",
      "before": "Current text or 'Not present'",
      "after": "Improved version",
      "field": "content_body|title|meta_description|h1|schema"
    }
  ],
  "seo_recommendations": [...],
  "cro_recommendations": [...]
}"""

# ── Helpers ───────────────────────────────────────────────────────────────────


def _normalize_page_url(site_base_url: str, page_url: str) -> str:
    """
    Ensure page_url is an absolute URL using the site's base domain.

    Accepts paths like '/services/remodeling/' or full URLs like
    'https://example.com/services/remodeling/'.
    """
    if page_url.startswith(('http://', 'https://')):
        return page_url.rstrip('/') + '/'
    base = site_base_url.rstrip('/')
    path = page_url.lstrip('/')
    return f"{base}/{path}"


def _fetch_gsc_data_for_page(site: Site, absolute_url: str) -> dict:
    """
    Fetch GSC search analytics scoped to a single page.

    Returns a dict with summary metrics and a ranked list of queries.
    Returns an empty dict if GSC is not connected or returns no data.
    """
    if not site.gsc_site_url or not site.gsc_refresh_token:
        logger.info("GSC not connected for site %s — skipping GSC fetch", site.id)
        return {}

    access_token = _get_valid_access_token(site)
    if not access_token:
        logger.warning("Could not obtain GSC access token for site %s", site.id)
        return {}

    rows = fetch_page_search_analytics(
        access_token=access_token,
        site_url=site.gsc_site_url,
        page_url=absolute_url,
        row_limit=50,
    )

    if not rows:
        return {}

    total_clicks = sum(r['clicks'] for r in rows)
    total_impressions = sum(r['impressions'] for r in rows)
    positions = [r['position'] for r in rows if r['position'] > 0]
    avg_position = round(sum(positions) / len(positions), 1) if positions else 0.0

    return {
        'total_clicks': total_clicks,
        'total_impressions': total_impressions,
        'avg_position': avg_position,
        'top_queries': rows[:20],
    }


def _fetch_wp_meta_for_page(site: Site, absolute_url: str) -> dict:
    """
    Collect WordPress page metadata for analysis.

    Strategy (in order of preference):
      1. Page + SEOData models in the database (most complete).
      2. WordPress REST API /wp-json/wp/v2/pages?slug=... (live fallback).
      3. Return whatever partial data is available.
    """
    parsed = urlparse(absolute_url)
    path = parsed.path.strip('/')
    slug = path.split('/')[-1] if '/' in path else path

    meta: dict[str, Any] = {
        'url': absolute_url,
        'slug': slug,
        'title': '',
        'h1': '',
        'meta_description': '',
        'word_count': 0,
        'has_schema': False,
        'schema_types': [],
        'focus_keyword': '',
        'content_snippet': '',
        'h2_headings': [],
        'internal_links_count': 0,
        'source': 'unknown',
    }

    # ── Strategy 1: local Page model ────────────────────────
    page_qs = Page.objects.filter(site=site, url__icontains=slug).select_related('seo_data').first()
    if not page_qs:
        # Try exact URL match variants
        page_qs = (
            Page.objects
            .filter(site=site)
            .filter(url__in=[absolute_url, absolute_url.rstrip('/'), absolute_url.rstrip('/') + '/'])
            .select_related('seo_data')
            .first()
        )

    if page_qs:
        meta['title'] = page_qs.title or ''
        meta['content_snippet'] = (page_qs.content or '')[:2000]
        meta['word_count'] = len((page_qs.content or '').split())
        meta['source'] = 'db_page'

        try:
            seo = page_qs.seo_data
            meta['h1'] = seo.h1_text or ''
            meta['meta_description'] = seo.meta_description or ''
            meta['has_schema'] = seo.has_schema
            meta['schema_types'] = [seo.schema_type] if seo.schema_type else []
            meta['h2_headings'] = seo.h2_texts or []
            meta['internal_links_count'] = seo.internal_links_count or 0
            if not meta['word_count']:
                meta['word_count'] = seo.word_count or 0
            meta['source'] = 'db_seo_data'
        except Exception:
            pass

        if meta['title']:
            return meta

    # ── Strategy 2: WordPress REST API ──────────────────────
    try:
        wp_api_url = f"{site.url.rstrip('/')}/wp-json/wp/v2/pages"
        params = {'slug': slug, '_fields': 'title,excerpt,content,slug,link,acf,yoast_head_json'}
        resp = requests.get(wp_api_url, params=params, timeout=8)
        if resp.status_code == 200:
            pages = resp.json()
            if pages:
                wp = pages[0]
                meta['title'] = wp.get('title', {}).get('rendered', '') or meta['title']
                raw_content = wp.get('content', {}).get('rendered', '')
                meta['content_snippet'] = _strip_html(raw_content)[:2000]
                meta['word_count'] = len(meta['content_snippet'].split()) or meta['word_count']

                yoast = wp.get('yoast_head_json') or {}
                meta['meta_description'] = (
                    yoast.get('og_description', '')
                    or yoast.get('description', '')
                    or meta['meta_description']
                )
                meta['h1'] = (
                    yoast.get('og_title', '')
                    or _extract_h1(raw_content)
                    or meta['h1']
                )
                meta['source'] = 'wp_rest_api'
    except Exception as exc:
        logger.debug("WP REST API fetch failed for %s: %s", absolute_url, exc)

    return meta


def _strip_html(html: str) -> str:
    """Remove HTML tags and decode basic entities."""
    text = re.sub(r'<[^>]+>', ' ', html)
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    return re.sub(r'\s+', ' ', text).strip()


def _extract_h1(html: str) -> str:
    """Extract first H1 text from HTML content."""
    match = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.IGNORECASE | re.DOTALL)
    if match:
        return _strip_html(match.group(1))
    return ''


def _build_analysis_prompt(absolute_url: str, gsc_data: dict, wp_meta: dict) -> str:
    """
    Build the user-side message for the AI analysis call.
    Assembles all available page signals into a structured context block.
    """
    top_queries = gsc_data.get('top_queries', [])
    query_summary = ''
    if top_queries:
        lines = [f"  #{i+1}: \"{q['query']}\" — pos {q['position']}, {q['impressions']} impr" for i, q in enumerate(top_queries[:10])]
        query_summary = '\n'.join(lines)
    else:
        query_summary = '  (GSC not connected or no data for this page)'

    h2_headings = wp_meta.get('h2_headings', [])
    h2_summary = ', '.join(f'"{h}"' for h in h2_headings[:6]) if h2_headings else 'None detected'

    return f"""Analyze this page against the Three-Layer Content Model.

PAGE URL: {absolute_url}

=== SEO METADATA ===
Title tag: {wp_meta.get('title') or 'Not set'}
H1: {wp_meta.get('h1') or 'Not set'}
Meta description: {wp_meta.get('meta_description') or 'Not set'}
Word count: {wp_meta.get('word_count', 0)}
H2 headings: {h2_summary}
Has schema markup: {wp_meta.get('has_schema', False)}
Schema types: {', '.join(wp_meta.get('schema_types', [])) or 'None'}
Internal links out: {wp_meta.get('internal_links_count', 0)}
Focus keyword: {wp_meta.get('focus_keyword') or 'Not set'}

=== CONTENT PREVIEW (first 1500 chars) ===
{(wp_meta.get('content_snippet') or 'Content not available')[:1500]}

=== GOOGLE SEARCH CONSOLE DATA (last 90 days) ===
Total clicks: {gsc_data.get('total_clicks', 0)}
Total impressions: {gsc_data.get('total_impressions', 0)}
Average position: {gsc_data.get('avg_position', 0)}

Top ranking queries for this page:
{query_summary}

Generate GEO, SEO, and CRO scores and specific recommendations based on the ACTUAL content shown above. Every recommendation must reference specific text from this page."""


def _call_ai_for_analysis(user_message: str) -> dict:
    """
    Call AI to analyze the page. Uses Anthropic Claude as primary provider
    and falls back to OpenAI if unavailable.

    Returns a validated dict with geo_score, seo_score, cro_score,
    geo_recommendations, seo_recommendations, cro_recommendations.

    Raises RuntimeError if all providers fail.
    """
    if ANTHROPIC_API_KEY:
        try:
            return _call_claude(user_message)
        except Exception as exc:
            logger.warning("Claude analysis call failed (%s) — falling back to OpenAI", exc)

    if OPENAI_API_KEY:
        try:
            return _call_openai(user_message)
        except Exception as exc:
            logger.error("OpenAI analysis call also failed: %s", exc)
            raise RuntimeError(f"All AI providers failed. Last error: {exc}") from exc

    raise RuntimeError(
        "No AI provider configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY."
    )


def _call_claude(user_message: str) -> dict:
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=MAX_TOKENS,
        temperature=0.3,
        system=PAGE_ANALYSIS_SYSTEM_PROMPT,
        messages=[{'role': 'user', 'content': user_message}],
    )
    text = ''.join(block.text for block in message.content if block.type == 'text')
    return _parse_ai_json(text)


def _call_openai(user_message: str) -> dict:
    import openai
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=0.3,
        max_tokens=MAX_TOKENS,
        response_format={'type': 'json_object'},
        messages=[
            {'role': 'system', 'content': PAGE_ANALYSIS_SYSTEM_PROMPT},
            {'role': 'user', 'content': user_message},
        ],
    )
    return _parse_ai_json(response.choices[0].message.content)


def _parse_ai_json(text: str) -> dict:
    """Strip markdown fences and parse JSON, then validate structure."""
    cleaned = re.sub(r'```(?:json)?\s*', '', text).strip().rstrip('`').strip()
    data = json.loads(cleaned)
    _validate_analysis_response(data)
    return data


def _validate_analysis_response(data: dict) -> None:
    """Raise ValueError if required top-level keys are missing or scores are out of range."""
    required = ('geo_score', 'seo_score', 'cro_score', 'geo_recommendations', 'seo_recommendations', 'cro_recommendations')
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(f"AI response missing fields: {missing}")

    for key in ('geo_score', 'seo_score', 'cro_score'):
        val = data[key]
        if not isinstance(val, (int, float)) or not (0 <= val <= 100):
            raise ValueError(f"Invalid score for {key}: {val!r}")

    for layer_key in ('geo_recommendations', 'seo_recommendations', 'cro_recommendations'):
        recs = data[layer_key]
        if not isinstance(recs, list):
            raise ValueError(f"{layer_key} must be a list, got {type(recs)}")
        if len(recs) > 3:
            data[layer_key] = recs[:3]


def _stamp_recommendation_status(recs: list) -> list:
    """Ensure every recommendation dict has a 'status' field set to 'pending'."""
    for rec in recs:
        rec.setdefault('status', 'pending')
    return recs


def _apply_recommendation_to_wordpress(site: Site, analysis: PageAnalysis, rec: dict) -> dict:
    """
    Push a single approved recommendation to WordPress via the Siloq plugin webhook.

    Uses the 'page.update_meta' event which the WP plugin handles natively.
    Maps recommendation field names to the payload keys the plugin expects.

    Returns a dict with 'success' (bool), 'rec_id' (str), and 'error' (str|None).
    """
    field = rec.get('field', '')
    after = rec.get('after', '')
    rec_id = rec.get('id')

    # Fields not yet automatable via page.update_meta
    if field == 'content_body':
        logger.info('Skipping content_body rec %s — manual application required', rec_id)
        return {'rec_id': rec_id, 'success': False, 'error': 'content_body updates require manual application in WordPress'}
    if field == 'schema':
        logger.info('Skipping schema rec %s — not yet automated', rec_id)
        return {'rec_id': rec_id, 'success': False, 'error': 'schema updates not yet automated'}

    # Build page.update_meta payload — WP plugin expects {url, title?, meta_description?, h1?}
    data: dict = {'url': analysis.page_url}
    if field == 'title':
        data['title'] = after
    elif field == 'meta_description':
        data['meta_description'] = after
    elif field == 'h1':
        data['h1'] = after
    else:
        # Pass through any other string fields (future proofing)
        data[field] = after

    result = send_webhook_to_wordpress(
        site=site,
        event_type='page.update_meta',
        data=data,
    )
    return {
        'rec_id': rec_id,
        'success': result.get('success', False),
        'error': result.get('error'),
    }


# ── View: POST /api/v1/sites/{site_id}/pages/analyze/ ─────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def analyze_page(request, site_id: int):
    """
    Trigger a Three-Layer Content Model analysis for a single page.

    Body:
        { "page_url": "/services/basement-remodeling/" }

    Fetches live GSC data + WordPress meta, calls Claude/OpenAI, saves
    a PageAnalysis record, and returns the full analysis.
    """
    site = get_object_or_404(Site, id=site_id, user=request.user)

    page_url_input = (request.data.get('page_url') or '').strip()
    if not page_url_input:
        return Response({'error': 'page_url is required'}, status=status.HTTP_400_BAD_REQUEST)

    absolute_url = _normalize_page_url(site.url, page_url_input)

    # ── Create pending record immediately ──────────────────
    analysis = PageAnalysis.objects.create(
        site=site,
        page_url=absolute_url,
        status='analyzing',
    )

    try:
        # Step 1: GSC data for this page
        gsc_data = _fetch_gsc_data_for_page(site, absolute_url)

        # Step 2: WordPress meta
        wp_meta = _fetch_wp_meta_for_page(site, absolute_url)

        # Step 3: Build AI prompt
        user_message = _build_analysis_prompt(absolute_url, gsc_data, wp_meta)

        # Step 4: Call AI
        ai_result = _call_ai_for_analysis(user_message)

        # Step 5: Compute overall score (weighted: GEO 30%, SEO 40%, CRO 30%)
        geo_score = int(ai_result['geo_score'])
        seo_score = int(ai_result['seo_score'])
        cro_score = int(ai_result['cro_score'])
        overall_score = round(geo_score * 0.30 + seo_score * 0.40 + cro_score * 0.30)

        geo_recs = _stamp_recommendation_status(ai_result.get('geo_recommendations', []))
        seo_recs = _stamp_recommendation_status(ai_result.get('seo_recommendations', []))
        cro_recs = _stamp_recommendation_status(ai_result.get('cro_recommendations', []))

        # Step 6: Persist
        analysis.page_title = wp_meta.get('title', '')
        analysis.gsc_data = gsc_data
        analysis.wp_meta = wp_meta
        analysis.geo_score = geo_score
        analysis.seo_score = seo_score
        analysis.cro_score = cro_score
        analysis.overall_score = overall_score
        analysis.geo_recommendations = geo_recs
        analysis.seo_recommendations = seo_recs
        analysis.cro_recommendations = cro_recs
        analysis.status = 'complete'
        analysis.completed_at = timezone.now()
        analysis.save()

    except Exception as exc:
        logger.exception("PageAnalysis failed for %s (site %s): %s", absolute_url, site_id, exc)
        analysis.status = 'failed'
        analysis.error_message = str(exc)
        analysis.save(update_fields=['status', 'error_message'])
        return Response(
            {'error': f'Analysis failed: {exc}', 'analysis_id': analysis.id},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    return Response(_serialize_analysis(analysis), status=status.HTTP_201_CREATED)


# ── View: GET /api/v1/sites/{site_id}/pages/analysis/ ─────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_analyses(request, site_id: int):
    """
    Return the most recent PageAnalysis per URL for this site.

    GET /api/v1/sites/{site_id}/pages/analysis/
    """
    site = get_object_or_404(Site, id=site_id, user=request.user)

    # Latest analysis per page URL using a subquery
    from django.db.models import Max, OuterRef, Subquery

    latest_ids = (
        PageAnalysis.objects
        .filter(site=site)
        .values('page_url')
        .annotate(latest_id=Max('id'))
        .values('latest_id')
    )

    analyses = (
        PageAnalysis.objects
        .filter(id__in=latest_ids)
        .order_by('-created_at')
    )

    # Filter by page_url if provided as query param
    page_url_filter = request.query_params.get('page_url')
    if page_url_filter:
        analyses = analyses.filter(page_url=page_url_filter)

    return Response({
        'count': analyses.count(),
        'results': [_serialize_analysis_summary(a) for a in analyses],
    })


# ── View: GET /api/v1/sites/{site_id}/pages/analysis/{analysis_id}/ ───────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_analysis(request, site_id: int, analysis_id: int):
    """
    Return full PageAnalysis with all recommendations.

    GET /api/v1/sites/{site_id}/pages/analysis/{analysis_id}/
    """
    site = get_object_or_404(Site, id=site_id, user=request.user)
    analysis = get_object_or_404(PageAnalysis, id=analysis_id, site=site)
    return Response(_serialize_analysis(analysis))


# ── View: POST /api/v1/sites/{site_id}/pages/analysis/{analysis_id}/approve/ ──

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def approve_recommendations(request, site_id: int, analysis_id: int):
    """
    Mark specific recommendations as 'approved' for later application.

    Body:
        { "recommendation_ids": ["geo_1", "seo_2"] }
    """
    site = get_object_or_404(Site, id=site_id, user=request.user)
    analysis = get_object_or_404(PageAnalysis, id=analysis_id, site=site)

    if analysis.status != 'complete':
        return Response(
            {'error': 'Only complete analyses can have recommendations approved'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    rec_ids = request.data.get('recommendation_ids')
    if not rec_ids or not isinstance(rec_ids, list):
        return Response(
            {'error': 'recommendation_ids must be a non-empty list'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    rec_ids_set = set(rec_ids)
    approved_count = 0

    for layer_key in ('geo_recommendations', 'seo_recommendations', 'cro_recommendations'):
        recs = getattr(analysis, layer_key)
        changed = False
        for rec in recs:
            if rec.get('id') in rec_ids_set:
                rec['status'] = 'approved'
                approved_count += 1
                changed = True
        if changed:
            setattr(analysis, layer_key, recs)

    if not approved_count:
        return Response(
            {'error': 'No matching recommendation IDs found'},
            status=status.HTTP_404_NOT_FOUND,
        )

    analysis.save(update_fields=['geo_recommendations', 'seo_recommendations', 'cro_recommendations'])

    return Response({
        'approved_count': approved_count,
        'analysis_id': analysis.id,
        'recommendations': _all_recommendations(analysis),
    })


# ── View: POST /api/v1/sites/{site_id}/pages/analysis/{analysis_id}/apply/ ────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def apply_recommendations(request, site_id: int, analysis_id: int):
    """
    Push all 'approved' recommendations to WordPress via the Siloq plugin webhook.

    Returns:
        { "applied": [...rec_ids], "failed": [...{ "rec_id": ..., "error": ...}] }
    """
    site = get_object_or_404(Site, id=site_id, user=request.user)
    analysis = get_object_or_404(PageAnalysis, id=analysis_id, site=site)

    if analysis.status != 'complete':
        return Response(
            {'error': 'Only complete analyses can have recommendations applied'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    approved_recs = [
        rec
        for layer_key in ('geo_recommendations', 'seo_recommendations', 'cro_recommendations')
        for rec in getattr(analysis, layer_key)
        if rec.get('status') == 'approved'
    ]

    if not approved_recs:
        return Response(
            {'error': 'No approved recommendations to apply. Use the approve endpoint first.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    applied = []
    failed = []

    for rec in approved_recs:
        result = _apply_recommendation_to_wordpress(site, analysis, rec)
        if result['success']:
            applied.append(result['rec_id'])
            # Update status to 'applied' in the stored analysis
            for layer_key in ('geo_recommendations', 'seo_recommendations', 'cro_recommendations'):
                recs = getattr(analysis, layer_key)
                for r in recs:
                    if r.get('id') == result['rec_id']:
                        r['status'] = 'applied'
                setattr(analysis, layer_key, recs)
        else:
            failed.append({'rec_id': result['rec_id'], 'error': result['error']})

    analysis.save(update_fields=['geo_recommendations', 'seo_recommendations', 'cro_recommendations'])

    return Response({
        'applied': applied,
        'failed': failed,
        'analysis_id': analysis.id,
    })


# ── Serializers ───────────────────────────────────────────────────────────────

def _serialize_analysis(analysis: PageAnalysis) -> dict:
    """Full serialization including all recommendations and input data."""
    geo_recs = analysis.geo_recommendations or []
    seo_recs = analysis.seo_recommendations or []
    cro_recs = analysis.cro_recommendations or []
    return {
        'id': analysis.id,
        'site_id': analysis.site_id,
        'page_url': analysis.page_url,
        'page_title': analysis.page_title,
        'status': analysis.status,
        'error_message': analysis.error_message or None,
        # Flat fields — match the frontend PageAnalysis interface
        'geo_score': analysis.geo_score,
        'seo_score': analysis.seo_score,
        'cro_score': analysis.cro_score,
        'overall_score': analysis.overall_score,
        'geo_recommendations': geo_recs,
        'seo_recommendations': seo_recs,
        'cro_recommendations': cro_recs,
        'scores': {
            'geo': analysis.geo_score,
            'seo': analysis.seo_score,
            'cro': analysis.cro_score,
            'overall': analysis.overall_score,
        },
        # Nested alias kept for backwards compat
        'recommendations': {
            'geo': geo_recs,
            'seo': seo_recs,
            'cro': cro_recs,
        },
        'input_data': {
            'gsc_summary': {
                k: v for k, v in analysis.gsc_data.items() if k != 'top_queries'
            } if analysis.gsc_data else {},
            'gsc_top_queries': analysis.gsc_data.get('top_queries', [])[:10],
            'wp_meta': {
                k: v for k, v in analysis.wp_meta.items() if k != 'content_snippet'
            } if analysis.wp_meta else {},
        },
        'created_at': analysis.created_at.isoformat() if analysis.created_at else None,
        'completed_at': analysis.completed_at.isoformat() if analysis.completed_at else None,
    }


def _serialize_analysis_summary(analysis: PageAnalysis) -> dict:
    """Compact serialization for list views — includes flat fields matching PageAnalysis interface."""
    geo_recs = analysis.geo_recommendations or []
    seo_recs = analysis.seo_recommendations or []
    cro_recs = analysis.cro_recommendations or []
    all_recs = list(geo_recs) + list(seo_recs) + list(cro_recs)
    pending_count = sum(1 for r in all_recs if r.get('status') == 'pending')
    approved_count = sum(1 for r in all_recs if r.get('status') == 'approved')
    applied_count = sum(1 for r in all_recs if r.get('status') == 'applied')

    return {
        'id': analysis.id,
        'page_url': analysis.page_url,
        'page_title': analysis.page_title,
        'status': analysis.status,
        # Flat score fields — match frontend PageAnalysis interface
        'geo_score': analysis.geo_score,
        'seo_score': analysis.seo_score,
        'cro_score': analysis.cro_score,
        'overall_score': analysis.overall_score,
        # Flat recommendation fields
        'geo_recommendations': geo_recs,
        'seo_recommendations': seo_recs,
        'cro_recommendations': cro_recs,
        'scores': {
            'geo': analysis.geo_score,
            'seo': analysis.seo_score,
            'cro': analysis.cro_score,
            'overall': analysis.overall_score,
        },
        'recommendation_counts': {
            'total': len(all_recs),
            'pending': pending_count,
            'approved': approved_count,
            'applied': applied_count,
        },
        'created_at': analysis.created_at.isoformat() if analysis.created_at else None,
        'completed_at': analysis.completed_at.isoformat() if analysis.completed_at else None,
    }


def _all_recommendations(analysis: PageAnalysis) -> list:
    """Return all recommendations across all three layers as a flat list."""
    return (
        list(analysis.geo_recommendations)
        + list(analysis.seo_recommendations)
        + list(analysis.cro_recommendations)
    )
