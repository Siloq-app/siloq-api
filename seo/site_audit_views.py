"""
POST /api/v1/sites/{site_id}/audit/ — Site audit scoring engine + AI recommendations.

Track 2: Algorithm Rebuild — deterministic scoring with AI-powered recommendations
for pages scoring below 80.
"""
import json
import logging
import uuid

from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from sites.models import Site
from seo.models import SiteAudit
from ai.providers import call_ai

logger = logging.getLogger(__name__)

UNLIMITED_TIERS = {'builder_plus', 'architect', 'empire'}

AUDIT_SYSTEM_PROMPT = """You are an SEO technical auditor for local service businesses.
Given a page's on-page SEO data and the business context, generate specific, actionable
recommendations to improve the page's SEO performance.

Rules:
- Each recommendation must be specific to THIS page — never generic.
- Reference the business name, services, and service cities where relevant.
- Prioritize by impact: structural issues first, then content, then schema.
- Return valid JSON only — no markdown, no commentary.

Return format:
{
  "recommendations": [
    {
      "priority": 1,
      "category": "STRUCTURAL|CONTENT|SCHEMA|CLASSIFICATION",
      "type": "short_snake_case_identifier",
      "severity": "critical|high|warning|medium|info",
      "title": "Human readable title",
      "recommendation": "Specific actionable recommendation text.",
      "auto_fixable": false
    }
  ]
}

Generate up to 5 recommendations maximum. Focus on highest-impact issues."""


def _compute_score(page_data: dict) -> int:
    score = 100

    if not page_data.get('title'):
        score -= 20

    meta_status = page_data.get('meta_description_status', '')
    if meta_status in ('broken_fallback', 'missing') or not page_data.get('meta_description'):
        score -= 15

    h1 = page_data.get('h1')
    if not h1:
        score -= 15

    word_count = page_data.get('word_count', 0) or 0
    if word_count < 150:
        score -= 25
    elif word_count < 300:
        score -= 15

    inbound = page_data.get('inbound_links', 0) or 0
    page_type = page_data.get('page_type', '')
    if inbound == 0 and page_type != 'apex_hub':
        score -= 10

    images_missing_alt = page_data.get('images_missing_alt', 0) or 0
    if images_missing_alt > 0:
        score -= min(images_missing_alt * 5, 15)

    schema_types = page_data.get('schema_types') or []
    if not schema_types:
        score -= 10

    if page_data.get('has_duplicate_title'):
        score -= 20

    return max(0, score)


def _build_deterministic_actions(page_data: dict, score: int) -> list:
    actions = []
    priority = 0

    if not page_data.get('title'):
        priority += 1
        actions.append({
            'priority': priority,
            'category': 'STRUCTURAL',
            'type': 'missing_title',
            'severity': 'critical',
            'title': 'Missing page title',
            'recommendation': 'Add a unique, keyword-rich title tag (50-60 characters).',
            'auto_fixable': False,
        })

    meta_status = page_data.get('meta_description_status', '')
    if meta_status == 'missing' or (not page_data.get('meta_description') and meta_status != 'broken_fallback'):
        priority += 1
        actions.append({
            'priority': priority,
            'category': 'STRUCTURAL',
            'type': 'missing_meta_description',
            'severity': 'critical',
            'title': 'Missing meta description',
            'recommendation': 'Add a 120-160 character meta description targeting the primary keyword.',
            'auto_fixable': False,
        })
    elif meta_status == 'broken_fallback':
        priority += 1
        actions.append({
            'priority': priority,
            'category': 'STRUCTURAL',
            'type': 'broken_meta_description',
            'severity': 'critical',
            'title': 'Broken meta description (full page content dumped)',
            'recommendation': 'Your SEO plugin is outputting the entire page content as the meta description. Write a proper 120-160 character summary.',
            'auto_fixable': False,
        })

    if not page_data.get('h1'):
        priority += 1
        actions.append({
            'priority': priority,
            'category': 'STRUCTURAL',
            'type': 'missing_h1',
            'severity': 'critical',
            'title': 'Missing H1 heading',
            'recommendation': 'Add a single H1 heading that includes the primary keyword for this page.',
            'auto_fixable': False,
        })

    if page_data.get('has_duplicate_title'):
        priority += 1
        actions.append({
            'priority': priority,
            'category': 'STRUCTURAL',
            'type': 'duplicate_title',
            'severity': 'critical',
            'title': 'Duplicate title tag',
            'recommendation': 'This page shares its title with another page. Create a unique title to avoid cannibalization.',
            'auto_fixable': False,
        })

    word_count = page_data.get('word_count', 0) or 0
    if word_count < 150:
        priority += 1
        actions.append({
            'priority': priority,
            'category': 'CONTENT',
            'type': 'very_thin_content',
            'severity': 'critical',
            'title': f'Very thin content ({word_count} words)',
            'recommendation': 'This page has fewer than 150 words. Add substantial content (500+ words recommended for service pages).',
            'auto_fixable': False,
        })
    elif word_count < 300:
        priority += 1
        actions.append({
            'priority': priority,
            'category': 'CONTENT',
            'type': 'thin_content',
            'severity': 'high',
            'title': f'Thin content ({word_count} words)',
            'recommendation': 'This page has fewer than 300 words. Expand content to at least 500 words for better ranking potential.',
            'auto_fixable': False,
        })

    inbound = page_data.get('inbound_links', 0) or 0
    page_type = page_data.get('page_type', '')
    if inbound == 0 and page_type != 'apex_hub':
        priority += 1
        actions.append({
            'priority': priority,
            'category': 'CONTENT',
            'type': 'orphan_page',
            'severity': 'high',
            'title': 'No inbound internal links (orphan page)',
            'recommendation': 'Add internal links from related hub or supporting pages to improve discoverability.',
            'auto_fixable': False,
        })

    images_missing_alt = page_data.get('images_missing_alt', 0) or 0
    if images_missing_alt > 0:
        priority += 1
        actions.append({
            'priority': priority,
            'category': 'CONTENT',
            'type': 'images_missing_alt',
            'severity': 'warning',
            'title': f'{images_missing_alt} image(s) missing alt text',
            'recommendation': 'Add descriptive alt text to all images for accessibility and image search visibility.',
            'auto_fixable': False,
        })

    schema_types = page_data.get('schema_types') or []
    if not schema_types:
        priority += 1
        actions.append({
            'priority': priority,
            'category': 'SCHEMA',
            'type': 'no_schema',
            'severity': 'warning',
            'title': 'No structured data (schema) detected',
            'recommendation': 'Add appropriate schema markup for this page type to improve rich result eligibility.',
            'auto_fixable': False,
        })

    return actions


def _get_ai_recommendations(page_data: dict, site_context: dict) -> tuple:
    context_payload = {
        'page': {
            'url': page_data.get('url', ''),
            'title': page_data.get('title', ''),
            'meta_description': page_data.get('meta_description', ''),
            'h1': page_data.get('h1', ''),
            'word_count': page_data.get('word_count', 0),
            'page_type': page_data.get('page_type', ''),
            'inbound_links': page_data.get('inbound_links', 0),
            'outbound_links': page_data.get('outbound_links', 0),
            'schema_types': page_data.get('schema_types', []),
            'images_missing_alt': page_data.get('images_missing_alt', 0),
            'has_duplicate_title': page_data.get('has_duplicate_title', False),
        },
        'business': site_context,
    }

    try:
        result, provider, model = call_ai(
            system_prompt=AUDIT_SYSTEM_PROMPT,
            context_payload=context_payload,
            action='site_audit_recommendations',
        )
        recs = result.get('recommendations', [])[:5]
        return recs, provider, model
    except Exception as e:
        logger.warning(f"AI recommendations failed: {e}")
        return [], '', ''


def _get_page_limit(subscription) -> int:
    if subscription.is_staff_exempt:
        return 999999
    tier = subscription.tier
    if tier in UNLIMITED_TIERS:
        return 999999
    if tier == 'pro':
        return getattr(subscription, 'trial_pages_limit', 50)
    return 10  # free_trial


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def site_audit(request, site_id: int):
    """POST /api/v1/sites/{site_id}/audit/ — Run site audit with scoring + AI recommendations."""
    site = get_object_or_404(Site, id=site_id, user=request.user)

    # Entitlement check
    try:
        subscription = request.user.subscription
    except Exception:
        subscription = None

    if subscription:
        page_limit = _get_page_limit(subscription)
    else:
        page_limit = 10  # default free_trial

    pages_data = request.data.get('pages', [])
    site_context = request.data.get('site_context', {})

    if len(pages_data) > page_limit:
        return Response(
            {'error': 'upgrade_required', 'limit': page_limit},
            status=status.HTTP_402_PAYMENT_REQUIRED,
        )

    if not pages_data:
        return Response(
            {'error': 'No pages provided in request body.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    page_results = []
    total_score = 0
    ai_provider = ''
    ai_model = ''

    for page_data in pages_data:
        score = _compute_score(page_data)
        actions = _build_deterministic_actions(page_data, score)

        # AI recommendations for low-scoring pages
        if score < 80:
            ai_recs, provider, model = _get_ai_recommendations(page_data, site_context)
            if provider:
                ai_provider = provider
                ai_model = model
            # Merge AI recs — offset priority to come after deterministic actions
            base_priority = len(actions)
            for rec in ai_recs:
                rec['priority'] = base_priority + rec.get('priority', 1)
                actions.append(rec)

        page_results.append({
            'post_id': page_data.get('post_id'),
            'score': score,
            'tier': page_data.get('page_type', 'supporting'),
            'actions': actions,
        })
        total_score += score

    site_score = round(total_score / len(pages_data)) if pages_data else 0

    # Persist audit
    audit = SiteAudit.objects.create(
        site=site,
        user=request.user,
        status='complete',
        site_score=site_score,
        site_context=site_context,
        results=page_results,
        ai_provider=ai_provider,
        ai_model=ai_model,
        pages_audited=len(pages_data),
    )

    return Response({
        'audit_id': str(audit.id),
        'status': 'complete',
        'site_score': site_score,
        'pages': page_results,
    })
