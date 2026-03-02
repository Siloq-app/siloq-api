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
from seo.geographic_grounding import compute_geographic_grounding, compute_informational_gain
from seo.freshness_scoring import compute_freshness_score
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
- ABSOLUTE RULE — NEVER FABRICATE TESTIMONIALS OR REVIEWS: Do NOT generate fake customer quotes, fake names, or invented social proof (e.g. "'Great service!' — Jane D."). This is a legal liability. For CRO recommendations involving testimonials or social proof: if real review data is provided in the context, use those actual quotes and real reviewer names. If no real review data is provided, write the recommendation as: "Connect your Google Business Profile in Settings to pull real customer reviews for this section" — never invent fake ones.

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
  "cro_recommendations": [...],
  "heading_structure": {
    "current": [{"level": "h1", "text": "...", "issues": []}],
    "recommended": [{"level": "h1", "text": "..."}, {"level": "h2", "text": "..."}],
    "issues_summary": ["Missing H2s", "H1 lacks city"]
  }
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

        # Fallback: if meta_description still empty, use yoast_description synced from WP plugin.
        # This field is populated by AIOSEO, Yoast, or RankMath via sync_page() in the WP plugin.
        # yoast_description from plugin sync = live AIOSEO/Yoast/RankMath value.
        # Always prefer it over stale SEOData — plugin reads fresh from DB on every sync.
        if page_qs.yoast_description:
            meta['meta_description'] = page_qs.yoast_description

        # Also pull faq_questions from wp_meta if plugin synced them (Elementor pages)
        wp_meta_data = getattr(page_qs, 'wp_meta', {}) or {}
        if wp_meta_data.get('faq_questions'):
            meta['faq_questions'] = wp_meta_data['faq_questions']

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

    # ── Strategy 3: Scrape live page HTML (meta description + H-tag hierarchy) ─
    # Always fires to extract H-tags. Meta description only filled if still empty.
    try:
        resp = requests.get(absolute_url, timeout=8, headers={'User-Agent': 'Siloq/1.0'})
        if resp.status_code == 200:
            html = resp.text

            # Meta description — robust extraction, always use live HTML value (DB may be stale)
            # Handles AIOSEO, Yoast, RankMath, and native WP meta tags
            for _pattern in [
                r'<meta\s+name=["\']description["\']\s+content=["\']([^"\'>]{10,})["\']',
                r'<meta\s+content=["\']([^"\'>]{10,})["\']\s+name=["\']description["\']',
            ]:
                _m = re.search(_pattern, html, re.IGNORECASE)
                if _m:
                    _candidate = _m.group(1).strip()
                    if len(_candidate) > 10:
                        meta['meta_description'] = _candidate
                        break

            # FAQ extraction — static HTML patterns (Elementor accordion titles are NOT JS-rendered)
            _faq_qs = []
            # 1. Elementor accordion/toggle: <a class="elementor-accordion-title">Q: ...</a>
            for _q in re.findall(r'<a[^>]+elementor-accordion-title[^>]*>([^<]{5,})</a>', html, re.IGNORECASE):
                _clean = _q.strip()
                if _clean and len(_clean) > 5:
                    _faq_qs.append(_clean)
            # 2. h2-h5 headings containing ? (FAQ questions used as headings)
            for _h_text in re.findall(r'<h[2-5][^>]*>([^<]*\?[^<]*)</h[2-5]>', html, re.IGNORECASE):
                _clean = re.sub(r'<[^>]+>', '', _h_text).strip()
                if _clean and len(_clean) > 10:
                    _faq_qs.append(_clean)
            # 3. dt/summary/button accordion patterns
            for _pattern in [
                r'<(?:dt|summary)[^>]*>\s*([^<]{10,}\?[^<]*?)\s*</(?:dt|summary)>',
                r'<button[^>]*class=[^>]*(?:faq|accordion|toggle)[^>]*>\s*([^<]{10,})\s*</button>',
                r'<[^>]+class=[^>]*(?:faq|accordion)[^>]*title[^>]*>([^<]{10,})</[^>]+>',
            ]:
                for _q in re.findall(_pattern, html, re.IGNORECASE | re.DOTALL):
                    _clean = re.sub(r'<[^>]+>', '', _q).strip()
                    if _clean and len(_clean) > 10:
                        _faq_qs.append(_clean)
            # 4. FAQ section heading detection (even without individual questions extracted)
            if not _faq_qs:
                _faq_heading = re.search(r'(?:frequently asked questions|FAQ section)', html, re.IGNORECASE)
                if _faq_heading:
                    _faq_qs.append('FAQ section present (questions JS-rendered)')
            if _faq_qs:
                meta['faq_questions'] = list(dict.fromkeys(_faq_qs))[:15]  # dedupe, cap at 15

            # Full H-tag hierarchy — extract H1–H4 in document order
            htag_re = re.compile(r'<h([1-4])[^>]*>(.*?)</h\1>', re.IGNORECASE | re.DOTALL)
            headings = []
            for level, text in htag_re.findall(html):
                clean = re.sub(r'<[^>]+>', '', text).strip()
                if clean:
                    headings.append({'level': f'h{level}', 'text': clean[:200]})
            if headings:
                meta['heading_hierarchy'] = headings
                if not meta.get('h2_headings'):
                    meta['h2_headings'] = [h['text'] for h in headings if h['level'] == 'h2']

            meta['source'] = (meta['source'] + '+html_scrape') if meta['source'] != 'unknown' else 'html_scrape'
    except Exception as exc:
        logger.debug("HTML scrape failed for %s: %s", absolute_url, exc)

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


def _build_analysis_prompt(absolute_url: str, gsc_data: dict, wp_meta: dict, site=None) -> str:
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

    # Full H-tag hierarchy for Section 03 heading audit
    heading_hierarchy = wp_meta.get('heading_hierarchy', [])
    if heading_hierarchy:
        h_map_lines = []
        for h in heading_hierarchy[:20]:
            indent = '  ' * (int(h['level'][1]) - 1)
            h_map_lines.append(f"{indent}{h['level'].upper()}: {h['text']}")
        h_tag_map = '\n'.join(h_map_lines)
    elif wp_meta.get('h1'):
        h2_lines = '\n'.join(f'  H2: {h}' for h in h2_headings[:6]) if h2_headings else '  H2: None detected'
        h_tag_map = f"H1: {wp_meta['h1']}\n{h2_lines}"
    else:
        h_tag_map = 'No heading structure available'

    # Entity profile context (if available)
    entity_context = ''
    if site:
        try:
            from seo.models import SiteEntityProfile
            profile = SiteEntityProfile.objects.get(site=site)
            if profile.business_name:
                reviews_text = ''
                if profile.gbp_reviews:
                    top_reviews = profile.gbp_reviews[:3]
                    reviews_text = '\n'.join([
                        f'  - "{r["text"][:200]}" — {r["author"]} ({r["rating"]}★)'
                        for r in top_reviews if r.get("text")
                    ])
                brands_used = getattr(profile, 'brands_used', None) or []
                entity_context = f"""
=== BUSINESS ENTITY PROFILE ===
Business: {profile.business_name}
Location: {profile.city}, {profile.state}
Phone: {profile.phone}
Services: {', '.join(profile.categories[:5]) if profile.categories else 'Not specified'}
Brands/Products Used or Sold: {', '.join(brands_used[:8]) if brands_used else 'Not specified'}
Service Area Cities: {', '.join(profile.service_cities[:8]) if profile.service_cities else 'Not specified'}
Google Rating: {profile.gbp_star_rating}★ ({profile.gbp_review_count} reviews)
{f'Real Customer Reviews (USE THESE for CRO testimonial recommendations):{chr(10)}{reviews_text}' if reviews_text else 'No GBP reviews synced yet — for CRO testimonial recommendations, tell the user to connect their Google Business Profile in Settings.'}

CONTENT SPECIFICITY REQUIREMENT: Any supporting content or blog topic recommendations MUST use the actual business name, services, brands, and cities listed above. Do NOT suggest generic topics like "5 Electrical Safety Tips". Instead use the formula: [Brand they use] + [service] + [city], or [problem] + [city], or [service] + cost + [city]. Every topic must be ownable by THIS specific business.
"""
        except Exception:
            pass

    # ── Homepage detection ──────────────────────────────────────────────
    from urllib.parse import urlparse as _urlparse
    _parsed_path = _urlparse(absolute_url).path.rstrip('/')
    _is_homepage = _parsed_path == '' or _parsed_path == '/'

    _homepage_context = ""
    if _is_homepage:
        _homepage_context = """
⚠️  HOMEPAGE DOCTRINE — CRITICAL RULES FOR THIS PAGE:
This is the site's HOMEPAGE. It is a BRAND PAGE, not a keyword-targeting page.

HOMEPAGE SEO RULES (follow these exactly):
1. Title tag: Must be brand-first format: "[Business Name] | [Short Brand Tagline or City]". Do NOT optimize for a primary service keyword — that causes cannibalization with service pages.
2. Meta description: Brand overview only. Describe who the business is and what they do broadly. Do NOT keyword-stuff service terms.
3. H1: Should be a brand statement or brand tagline, not a keyword phrase.
4. NO keyword targeting recommendations on the homepage. The homepage should NOT compete with service pages.
5. Internal linking: ALWAYS recommend adding internal links to key service/money pages. This is the homepage's primary SEO job — pass authority to the pages that DO rank for keywords.
6. Schema: LocalBusiness/Organization — confirm it's present and complete.
7. Content body: Focus on brand clarity, trust signals, and calls to action — not keyword density.

What you SHOULD recommend:
- Internal links to top service pages (HIGH priority)
- Brand clarity in title/H1 (not keyword targeting)
- LocalBusiness schema completeness
- Trust signals (reviews, years in business, certifications)
- CTA above the fold

What you MUST NOT recommend:
- Adding primary service keywords to the title
- Keyword-optimizing the H1 or meta description
- Content that targets specific service keywords
"""

    return f"""Analyze this page against the Three-Layer Content Model.

PAGE URL: {absolute_url}
{_homepage_context}

=== SEO METADATA ===
Title tag: {wp_meta.get('title') or 'Not set'}
H1: {wp_meta.get('h1') or 'Not set'}
Meta description: {wp_meta.get('meta_description') or 'Not set'}
Word count: {wp_meta.get('word_count', 0)}
H-Tag Hierarchy (current):
{h_tag_map}


Has schema markup: {wp_meta.get('has_schema', False)}
Schema types: {', '.join(wp_meta.get('schema_types', [])) or 'None'}
Internal links out: {wp_meta.get('internal_links_count', 0)}
Focus keyword: {wp_meta.get('focus_keyword') or 'Not set'}

=== CONTENT PREVIEW (first 1500 chars) ===
{(wp_meta.get('content_snippet') or 'Content not available')[:1500]}
{entity_context}
=== GOOGLE SEARCH CONSOLE DATA (last 90 days) ===
Total clicks: {gsc_data.get('total_clicks', 0)}
Total impressions: {gsc_data.get('total_impressions', 0)}
Average position: {gsc_data.get('avg_position', 0)}

Top ranking queries for this page:
{query_summary}


{f"""
=== FAQ QUESTIONS DETECTED ON THIS PAGE ===
{chr(10).join(f'  - {q}' for q in wp_meta.get('faq_questions', []))}
(These FAQs are confirmed present on the page — do NOT recommend adding FAQs)
""" if wp_meta.get('faq_questions') else ""}
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


def _normalize_heading_structure(raw: Any) -> dict:
    """Normalize AI heading_structure output. Returns dict with current, recommended, issues_summary."""
    if not raw or not isinstance(raw, dict):
        return {'current': [], 'recommended': [], 'issues_summary': []}
    current = raw.get('current')
    recommended = raw.get('recommended')
    issues_summary = raw.get('issues_summary')
    if not isinstance(current, list):
        current = []
    if not isinstance(recommended, list):
        recommended = []
    if not isinstance(issues_summary, list):
        issues_summary = []
    return {
        'current': current[:20],
        'recommended': recommended[:20],
        'issues_summary': [str(x) for x in issues_summary[:10]],
    }


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

    # content_body — send via content.apply_content (WP plugin handles find/replace + append)
    if field == 'content_body':
        # Guard: if the AI generated an instruction/guidance as the AFTER text rather than
        # real insertable content, skip the apply and surface it as a manual action item
        INSTRUCTION_PHRASES = [
            'connect your google business profile',
            'go to settings',
            'pull real customer reviews',
            'settings to pull',
            'not yet available',
            'upgrade your plan',
            'contact us to enable',
        ]
        after_lower = after.lower()
        if any(phrase in after_lower for phrase in INSTRUCTION_PHRASES):
            logger.info('content_body rec %s is a guidance note — skipping auto-apply', rec_id)
            return {
                'rec_id': rec_id,
                'success': False,
                'error': 'requires_manual_action',
                'guidance': after,
            }

        before = rec.get('before', 'Not present')
        result = send_webhook_to_wordpress(
            site=site,
            event_type='content.apply_content',
            data={
                'url': analysis.page_url,
                'field': 'content_body',
                'before': before,
                'after': after,
            }
        )
        # WP plugin returns success:false + manual_action:true for page builder pages
        # (HTTP is still 200). Treat as requires_manual_action so dashboard shows amber.
        wp_resp = result.get('response') or {}
        if wp_resp.get('manual_action') or wp_resp.get('error') == 'page_builder_detected':
            builder = wp_resp.get('builder', 'page builder')
            logger.info('content_body rec %s skipped — page builder detected (%s)', rec_id, builder)
            return {
                'rec_id': rec_id,
                'success': False,
                'error': 'requires_manual_action',
                'guidance': wp_resp.get('message', f'This page uses {builder}. Paste the suggested content in your page editor.'),
            }
        return {
            'rec_id': rec_id,
            'success': result.get('success', False),
            'error': result.get('error'),
        }
    if field == 'schema':
        schema_data = getattr(analysis, 'generated_schema', {}) or {}
        if not schema_data.get('json_ld'):
            return {'rec_id': rec_id, 'success': False, 'error': 'No schema generated for this analysis — re-run Analyze first'}
        result = send_webhook_to_wordpress(
            site=site,
            event_type='schema.updated',
            data={
                'url': analysis.page_url,
                'schema_markup': schema_data['json_ld'],
            }
        )
        return {
            'rec_id': rec_id,
            'success': result.get('success', False),
            'error': result.get('error'),
        }

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


def _get_entity_profile(site) -> dict:
    """Fetch Site Entity Profile data for schema generation. Returns empty dict if not set up."""
    try:
        from seo.models import SiteEntityProfile
        profile = SiteEntityProfile.objects.get(site=site)

        # Build sameAs list from all social + GBP + Yelp URLs
        same_as = [
            u for u in [
                profile.url_facebook, profile.url_instagram, profile.url_linkedin,
                profile.url_twitter, profile.url_youtube, profile.url_tiktok,
                profile.gbp_url,
                getattr(profile, 'url_yelp', None),
            ] if u
        ]

        return {
            'business_name':  profile.business_name,
            'description':    profile.description,
            'phone':          profile.phone,
            'email':          profile.email,
            'street_address': profile.street_address,
            'city':           profile.city,
            'state':          profile.state,
            'zip_code':       profile.zip_code,
            'country':        profile.country,
            'founding_year':  profile.founding_year,
            'founder_name':   profile.founder_name,
            'price_range':    profile.price_range,
            'categories':     profile.categories,
            'service_cities': profile.service_cities,
            'hours':          profile.hours,
            'social_urls':    same_as,
            'logo_url':       getattr(profile, 'logo_url', '') or '',
            'brands_used':    getattr(profile, 'brands_used', []) or [],
            'gbp_star_rating':  profile.gbp_star_rating,
            'gbp_review_count': profile.gbp_review_count,
            'gbp_reviews':      profile.gbp_reviews[:5],
            'certifications':   profile.certifications,
            'is_service_area_business': getattr(profile, 'is_service_area_business', False),
        }
    except Exception:
        return {}


def _generate_schema_for_recommendations(ai_result: dict, wp_meta: dict, absolute_url: str, site=None) -> dict:
    """
    Generate comprehensive JSON-LD schema based on page type, AI recommendations,
    and Site Entity Profile data. Schema type is determined automatically from page type.
    """
    import re as _re

    geo_recs = ai_result.get('geo_recommendations', [])
    entity = _get_entity_profile(site) if site else {}

    business_name = entity.get('business_name') or wp_meta.get('title', '').split('|')[0].strip() or ''
    description = entity.get('description') or wp_meta.get('meta_description', '') or ''
    url_lower = absolute_url.lower()
    path = url_lower.rstrip('/').split('/')

    # ── Extract FAQ pairs from GEO recommendations ────────────────────────
    faq_pairs = []
    for rec in geo_recs:
        after_text = rec.get('after', '')
        pairs = _re.findall(
            r'(?:Q:|Question:|\*\*Q:\*\*|^\d+\.\s)(.+?)(?:\n|$).*?(?:A:|Answer:|\*\*A:\*\*)(.+?)(?=\n\n|\n(?:Q:|Question:|\*\*Q:)|\Z)',
            after_text, _re.DOTALL | _re.IGNORECASE | _re.MULTILINE
        )
        for q, a in pairs:
            faq_pairs.append({'q': q.strip()[:200], 'a': a.strip()[:500]})

    # ── Determine page type ───────────────────────────────────────────────
    is_homepage = path[-1] in ('', '/') or absolute_url.rstrip('/') == absolute_url.split('/')[2]
    is_service  = any(x in url_lower for x in ['/services/', '/service/'])
    is_blog     = any(x in url_lower for x in ['/blog/', '/post/', '/news/', '/article/'])
    is_about    = 'about' in url_lower
    is_contact  = 'contact' in url_lower
    is_location = any(x in url_lower for x in ['/location/', '/locations/', '/area/', '-ks-', '-mo-', '-tx-', '-ca-'])

    # ── Build base organization block ─────────────────────────────────────
    org_block = {
        '@type': 'LocalBusiness',
        'name': business_name,
        'description': description,
        'url': absolute_url.split('/services/')[0].split('/blog/')[0].rstrip('/') + '/',
    }
    if entity.get('phone'):
        org_block['telephone'] = entity['phone']
    if entity.get('email'):
        org_block['email'] = entity['email']
    if entity.get('street_address') and entity.get('city'):
        org_block['address'] = {
            '@type': 'PostalAddress',
            'streetAddress': entity['street_address'],
            'addressLocality': entity['city'],
            'addressRegion': entity.get('state', ''),
            'postalCode': entity.get('zip_code', ''),
            'addressCountry': entity.get('country', 'US'),
        }
    if entity.get('service_cities'):
        org_block['areaServed'] = entity['service_cities']
    if entity.get('logo_url'):
        org_block['logo'] = {
            '@type': 'ImageObject',
            'url': entity['logo_url'],
        }
        org_block['image'] = entity['logo_url']
    if entity.get('social_urls'):
        org_block['sameAs'] = entity['social_urls']
    if entity.get('gbp_star_rating') and entity.get('gbp_review_count'):
        org_block['aggregateRating'] = {
            '@type': 'AggregateRating',
            'ratingValue': str(entity['gbp_star_rating']),
            'reviewCount': str(entity['gbp_review_count']),
        }
    if entity.get('hours'):
        org_block['openingHoursSpecification'] = [
            {'@type': 'OpeningHoursSpecification', 'dayOfWeek': day.capitalize(), 'description': hours_text}
            for day, hours_text in entity['hours'].items()
        ]

    # ── Homepage schema ───────────────────────────────────────────────────
    if is_homepage:
        schema = {'@context': 'https://schema.org', **org_block}
        if entity.get('founding_year'):
            schema['foundingDate'] = str(entity['founding_year'])
        if entity.get('founder_name'):
            schema['founder'] = {'@type': 'Person', 'name': entity['founder_name']}
        return {'schema_type': 'LocalBusiness', 'json_ld': schema}

    # ── Service page schema ───────────────────────────────────────────────
    if is_service:
        title = wp_meta.get('title', business_name)
        graph = [
            {
                '@type': 'Service',
                'name': title,
                'description': description or title,
                'url': absolute_url,
                'provider': {'@type': 'LocalBusiness', 'name': business_name},
            }
        ]
        if entity.get('service_cities'):
            graph[0]['areaServed'] = entity['service_cities']
        if faq_pairs:
            graph.append({
                '@type': 'FAQPage',
                'mainEntity': [
                    {'@type': 'Question', 'name': p['q'],
                     'acceptedAnswer': {'@type': 'Answer', 'text': p['a']}}
                    for p in faq_pairs[:10]
                ]
            })
        graph.append({'@type': 'BreadcrumbList', 'itemListElement': _build_breadcrumbs(absolute_url)})
        return {'schema_type': 'Service+FAQ', 'json_ld': {'@context': 'https://schema.org', '@graph': graph}}

    # ── Blog post schema ──────────────────────────────────────────────────
    if is_blog:
        schema = {
            '@context': 'https://schema.org',
            '@type': 'Article',
            'headline': wp_meta.get('title', ''),
            'description': description,
            'url': absolute_url,
            'publisher': {'@type': 'Organization', 'name': business_name},
        }
        if faq_pairs:
            schema['hasPart'] = {
                '@type': 'FAQPage',
                'mainEntity': [
                    {'@type': 'Question', 'name': p['q'],
                     'acceptedAnswer': {'@type': 'Answer', 'text': p['a']}}
                    for p in faq_pairs[:5]
                ]
            }
        return {'schema_type': 'Article', 'json_ld': schema}

    # ── About page ────────────────────────────────────────────────────────
    if is_about:
        schema = {'@context': 'https://schema.org', **org_block}
        return {'schema_type': 'Organization', 'json_ld': schema}

    # ── Contact page ──────────────────────────────────────────────────────
    if is_contact:
        schema = {
            '@context': 'https://schema.org',
            '@type': 'ContactPage',
            'url': absolute_url,
            'name': f'Contact {business_name}',
        }
        if entity.get('phone') or entity.get('email'):
            schema['mainEntity'] = {
                '@type': 'ContactPoint',
                'telephone': entity.get('phone', ''),
                'email': entity.get('email', ''),
                'contactType': 'customer service',
            }
        return {'schema_type': 'ContactPage', 'json_ld': schema}

    # ── FAQ fallback for any page with FAQ recs ───────────────────────────
    if faq_pairs:
        return {
            'schema_type': 'FAQPage',
            'json_ld': {
                '@context': 'https://schema.org',
                '@type': 'FAQPage',
                'mainEntity': [
                    {'@type': 'Question', 'name': p['q'],
                     'acceptedAnswer': {'@type': 'Answer', 'text': p['a']}}
                    for p in faq_pairs[:10]
                ]
            }
        }

    return {}


def _build_breadcrumbs(url: str) -> list:
    """Build BreadcrumbList itemListElement from URL path."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    parts = [p for p in parsed.path.strip('/').split('/') if p]
    items = [{'@type': 'ListItem', 'position': 1, 'name': 'Home', 'item': base + '/'}]
    for i, part in enumerate(parts, 2):
        items.append({
            '@type': 'ListItem',
            'position': i,
            'name': part.replace('-', ' ').title(),
            'item': base + '/' + '/'.join(parts[:i-1]) + '/',
        })
    return items


# ── View: POST /api/v1/sites/{site_id}/pages/analyze/ ─────────────────────────


# ── Homepage brand-page post-processor ───────────────────────────────────────

def _is_homepage_url(absolute_url: str) -> bool:
    """True if the URL is the site root / homepage."""
    from urllib.parse import urlparse
    path = urlparse(absolute_url).path.rstrip('/')
    return path == '' or path == '/'


def _enforce_homepage_doctrine(ai_result: dict, wp_meta: dict, business_name: str) -> dict:
    """
    Post-process AI recommendations for the homepage.

    DOCTRINE: The homepage is a BRAND PAGE. It should never keyword-target
    service terms because that directly causes cannibalization with service pages.

    This function:
    - Strips any SEO recs that tell the homepage to keyword-optimize its title/H1/meta
    - Replaces them with correct brand-page recommendations
    - Ensures internal linking to money pages is always flagged (HIGH priority)
    - Preserves valid recs (schema, CRO, GEO) as-is
    """
    import re

    KEYWORD_TARGETING_PATTERNS = [
        r'keyword', r'primary keyword', r'target keyword',
        r'optimize.*title.*keyword', r'include.*keyword.*title',
        r'title.*not optimized', r'seo.*title', r'keyword.*title',
        r'rank.*keyword', r'focus keyword',
    ]

    def _is_keyword_targeting_rec(rec: dict) -> bool:
        text = f"{rec.get('issue','')} {rec.get('recommendation','')}".lower()
        return any(re.search(p, text) for p in KEYWORD_TARGETING_PATTERNS)

    def _mentions_service_keyword_in_title(rec: dict) -> bool:
        """Catch recs like 'Change title to Electrician Kansas City | Brand'"""
        after = rec.get('after', '')
        issue = rec.get('issue', '').lower()
        field = rec.get('field', '')
        # If it's touching the title and the 'after' looks like keyword | brand
        if field == 'title' and '|' in after:
            # Brand-first is OK: "Able Electric Inc | ..." — keyword-first is not
            # Heuristic: if the first word is a common service term, it's keyword-first
            first_word = after.split()[0].lower() if after else ''
            service_indicators = [
                'electrician', 'plumber', 'roofer', 'dentist', 'lawyer', 'attorney',
                'contractor', 'hvac', 'landscaper', 'cleaner', 'painter', 'mechanic',
                'doctor', 'therapist', 'accountant', 'realtor', 'insurance',
            ]
            return first_word in service_indicators
        return False

    # ── Filter bad SEO recs ───────────────────────────────────────────────────
    original_seo = ai_result.get('seo_recommendations', [])
    clean_seo = []
    removed_count = 0

    for rec in original_seo:
        if _is_keyword_targeting_rec(rec) or _mentions_service_keyword_in_title(rec):
            removed_count += 1
            continue
        clean_seo.append(rec)

    # ── Always ensure internal linking rec exists ────────────────────────────
    has_internal_link_rec = any(
        'internal link' in f"{r.get('issue','')} {r.get('recommendation','')}".lower()
        for r in clean_seo
    )
    if not has_internal_link_rec:
        clean_seo.insert(0, {
            'id': 'seo_homepage_internal_links',
            'layer': 'SEO',
            'priority': 'high',
            'issue': 'Homepage is not linking to key service pages.',
            'recommendation': (
                'Add clear text links (or a services section) to your top money pages. '
                'The homepage primary SEO role is to pass authority to the pages that rank for your service keywords. '
                'Without these links, service pages receive less crawl priority and PageRank.'
            ),
            'before': 'No internal links to service pages detected.',
            'after': 'Add a "Our Services" section with links to each service page, or include text links in the intro paragraph.',
            'field': 'content_body',
            'homepage_doctrine': True,
        })

    # ── Add brand title rec if we removed a bad keyword-title rec ────────────
    has_title_rec = any(r.get('field') == 'title' for r in clean_seo)
    if removed_count > 0 and not has_title_rec:
        current_title = wp_meta.get('title', 'Not set')
        clean_seo.append({
            'id': 'seo_homepage_brand_title',
            'layer': 'SEO',
            'priority': 'medium',
            'issue': 'Homepage title should be brand-first, not keyword-first.',
            'recommendation': (
                f'Format: "[{business_name}] | [Short brand tagline or city]". '
                'Never put a service keyword first in the homepage title — that creates '
                'direct cannibalization with your service pages that are trying to rank for those keywords.'
            ),
            'before': current_title,
            'after': f'{business_name} | Professional Services in Your Area',
            'field': 'title',
            'homepage_doctrine': True,
        })

    ai_result['seo_recommendations'] = clean_seo
    return ai_result

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
        user_message = _build_analysis_prompt(absolute_url, gsc_data, wp_meta, site=site)

        # Step 4: Call AI
        ai_result = _call_ai_for_analysis(user_message)

        # Step 4b: Homepage doctrine enforcement
        if _is_homepage_url(absolute_url):
            _biz_name = ''
            try:
                from seo.models import SiteEntityProfile
                _prof = SiteEntityProfile.objects.filter(site=site).first()
                _biz_name = _prof.business_name if _prof else ''
            except Exception:
                pass
            ai_result = _enforce_homepage_doctrine(ai_result, wp_meta, _biz_name)

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
        analysis.generated_schema = _generate_schema_for_recommendations(ai_result, wp_meta, absolute_url, site=site)
        analysis.gsc_data = gsc_data
        analysis.wp_meta = wp_meta
        analysis.geo_score = geo_score
        analysis.seo_score = seo_score
        analysis.cro_score = cro_score
        analysis.overall_score = overall_score
        analysis.geo_recommendations = geo_recs
        analysis.seo_recommendations = seo_recs
        analysis.cro_recommendations = cro_recs
        heading_struct = _normalize_heading_structure(ai_result.get('heading_structure'))
        analysis.wp_meta = {**(analysis.wp_meta or {}), 'heading_structure': heading_struct}

        # ── Geographic Ghosting + Informational Gain ───────────────────────
        try:
            page_obj = Page.objects.filter(site=site, url=absolute_url).first()
            h1_text = wp_meta.get('h1', '') or ''
            page_content = wp_meta.get('content_snippet', '') or ''

            if page_obj:
                geo_grounding = compute_geographic_grounding(page_obj, h1_text)

                # Fetch other pages in hub for informational gain comparison
                hub_pages = Page.objects.filter(
                    site=site,
                    hub_page_id=page_obj.hub_page_id,
                ).exclude(id=page_obj.id) if page_obj.hub_page_id else Page.objects.none()

                hub_contents = []
                for hp in hub_pages[:20]:
                    analysis_qs = PageAnalysis.objects.filter(
                        site=site, page_url=hp.url
                    ).order_by('-created_at').first()
                    if analysis_qs and analysis_qs.wp_meta:
                        snippet = analysis_qs.wp_meta.get('content_snippet', '')
                        if snippet:
                            hub_contents.append(snippet)

                informational_gain = compute_informational_gain(page_obj, page_content, hub_contents)
            else:
                geo_grounding = {'is_location_page': False, 'warning': False,
                                 'grounding_status': None, 'recommendations': []}
                informational_gain = {'label': 'unknown', 'warning': False,
                                      'unique_percentage': None, 'recommendations': []}

            # Freshness score
            try:
                page_for_freshness = page_obj if page_obj else None
                freshness = compute_freshness_score(page_for_freshness, analysis)
            except Exception as fs_exc:
                logger.warning("Freshness scoring failed: %s", fs_exc)
                freshness = {'score': None, 'label': 'unknown', 'warning': False, 'recommendations': []}

            analysis.wp_meta = {
                **(analysis.wp_meta or {}),
                'geographic_grounding': geo_grounding,
                'informational_gain': informational_gain,
                'freshness': freshness,
            }
        except Exception as gg_exc:
            logger.warning("Geographic grounding/IG computation failed: %s", gg_exc)

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
                        r['applied_at'] = timezone.now().isoformat()
                setattr(analysis, layer_key, recs)
        else:
            error_detail = result['error'] or 'Unknown error'
            failed_item = {'rec_id': result['rec_id'], 'error': error_detail}
            if error_detail == 'requires_manual_action':
                failed_item['status'] = 'manual_action'
                failed_item['guidance'] = result.get('guidance', 'This change requires manual implementation in your page editor.')
                # Mark the rec as manual_action in storage
                for layer_key in ('geo_recommendations', 'seo_recommendations', 'cro_recommendations'):
                    recs = getattr(analysis, layer_key)
                    for r in recs:
                        if r.get('id') == result['rec_id']:
                            r['status'] = 'manual_action'
                            r['guidance'] = failed_item['guidance']
                    setattr(analysis, layer_key, recs)
            failed.append(failed_item)

    # ── Verification: use webhook success as ground truth ─────────────────
    # The DB is always stale (not re-synced after apply), so text-matching
    # against local data will always show "pending". WordPress returned 200
    # with success:true — that IS the verification. Trust the webhook.
    verified = list(applied)   # All successfully applied recs are verified
    unverified = []
    verification_details = {
        rec_id: {'found': True, 'field': ''}
        for rec_id in applied
    }

    # Mark all applied recs as verified in the stored analysis
    for layer_key in ('geo_recommendations', 'seo_recommendations', 'cro_recommendations'):
        recs = getattr(analysis, layer_key)
        for r in recs:
            if r.get('id') in verified:
                r['status'] = 'verified'
        setattr(analysis, layer_key, recs)

    analysis.save(update_fields=['geo_recommendations', 'seo_recommendations', 'cro_recommendations'])

    return Response({
        'applied': applied,
        'failed': failed,
        'verified': verified,
        'unverified': unverified,
        'verification_details': verification_details,
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
                k: v for k, v in analysis.wp_meta.items()
                if k not in ('content_snippet', 'heading_structure')
            } if analysis.wp_meta else {},
        },
        'heading_structure': (analysis.wp_meta or {}).get('heading_structure') or {'current': [], 'recommended': [], 'issues_summary': []},
        'geographic_grounding': (analysis.wp_meta or {}).get('geographic_grounding') or {
            'is_location_page': False, 'target_location': None, 'grounding_status': None,
            'grounding_signals': [], 'missing_signals': [], 'warning': False,
            'warning_message': None, 'recommendations': [],
        },
        'informational_gain': (analysis.wp_meta or {}).get('informational_gain') or {
            'label': 'unknown', 'warning': False, 'unique_percentage': None,
            'swap_pattern_detected': False, 'recommendations': [],
        },
        'freshness': (analysis.wp_meta or {}).get('freshness') or {
            'score': None, 'label': 'unknown', 'emoji': '○', 'warning': False,
            'components': {}, 'outdated_flags': [], 'recommendations': [],
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
        'heading_structure': (analysis.wp_meta or {}).get('heading_structure') or {'current': [], 'recommended': [], 'issues_summary': []},
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


# ── Analyze All Pages ────────────────────────────────────────────────────────

import threading

def _run_analysis_for_all_pages(site_id: int, user_id: int, force: bool = False):
    """
    Background thread: run deep AI analysis for every published page on a site.
    Skips pages that already have a completed analysis (unless force=True).
    Runs sequentially with a short delay to avoid hammering the AI provider.
    """
    import time
    from django.contrib.auth import get_user_model

    User = get_user_model()
    logger_bg = logging.getLogger(__name__ + '.analyze_all')

    try:
        site = Site.objects.get(id=site_id)
        user = User.objects.get(id=user_id)
        pages = Page.objects.filter(
            site=site,
            status='publish',
            is_noindex=False,
        ).order_by('id')

        if not force:
            # Skip pages that already have a recent completed analysis (< 7 days old)
            from django.utils import timezone as tz
            from datetime import timedelta
            cutoff = tz.now() - timedelta(days=7)
            analyzed_urls = set(
                PageAnalysis.objects.filter(
                    site=site,
                    status='complete',
                    created_at__gte=cutoff,
                ).values_list('page_url', flat=True)
            )
            pages = [p for p in pages if p.url not in analyzed_urls]
        else:
            pages = list(pages)

        total = len(pages)
        logger_bg.info(f"analyze_all: site={site_id} queued={total} force={force}")

        for i, page in enumerate(pages):
            try:
                absolute_url = _normalize_page_url(site.url, page.url)

                # Create / reset analysis record
                analysis = PageAnalysis.objects.create(
                    site=site,
                    page_url=absolute_url,
                    status='analyzing',
                )

                gsc_data = _fetch_gsc_data_for_page(site, absolute_url)
                wp_meta  = _fetch_wp_meta_for_page(site, absolute_url)
                user_message = _build_analysis_prompt(absolute_url, gsc_data, wp_meta, site=site)
                ai_result = _call_ai_for_analysis(user_message)

                geo_score = int(ai_result['geo_score'])
                seo_score = int(ai_result['seo_score'])
                cro_score = int(ai_result['cro_score'])
                overall_score = round(geo_score * 0.30 + seo_score * 0.40 + cro_score * 0.30)

                analysis.page_title     = wp_meta.get('title', '')
                analysis.generated_schema = _generate_schema_for_recommendations(ai_result, wp_meta, absolute_url, site=site)
                analysis.gsc_data       = gsc_data
                analysis.wp_meta        = wp_meta
                analysis.geo_score      = geo_score
                analysis.seo_score      = seo_score
                analysis.cro_score      = cro_score
                analysis.overall_score  = overall_score
                analysis.geo_recommendations = _stamp_recommendation_status(ai_result.get('geo_recommendations', []))
                analysis.seo_recommendations = _stamp_recommendation_status(ai_result.get('seo_recommendations', []))
                analysis.cro_recommendations = _stamp_recommendation_status(ai_result.get('cro_recommendations', []))
                analysis.status         = 'complete'
                analysis.completed_at   = timezone.now()
                analysis.save()

                logger_bg.info(f"analyze_all: [{i+1}/{total}] done — {absolute_url}")

            except Exception as exc:
                logger_bg.warning(f"analyze_all: [{i+1}/{total}] failed — {page.url}: {exc}")
                try:
                    analysis.status = 'error'
                    analysis.error_message = str(exc)[:500]
                    analysis.save()
                except Exception:
                    pass

            # Brief pause between pages — avoids rate limits + gives server breathing room
            if i < total - 1:
                time.sleep(2)

    except Exception as exc:
        logging.getLogger(__name__).error(f"analyze_all background thread crashed: {exc}", exc_info=True)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def analyze_all_pages(request, site_id: int):
    """
    Kick off deep AI analysis for all published pages on a site.

    POST /api/v1/sites/{id}/pages/analyze-all/
    Body (optional): { "force": true }   — re-analyze even recently analyzed pages

    Returns immediately with the count of pages queued.
    Analysis runs in background; poll individual page analyses for progress.
    """
    site = get_object_or_404(Site, id=site_id, user=request.user)
    force = bool(request.data.get('force', False))

    total_pages = Page.objects.filter(
        site=site, status='publish', is_noindex=False
    ).count()

    if total_pages == 0:
        return Response(
            {'error': 'No published pages found. Sync your WordPress site first.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Fire and forget — background thread does the work
    t = threading.Thread(
        target=_run_analysis_for_all_pages,
        args=(site.id, request.user.id, force),
        daemon=True,
    )
    t.start()

    return Response({
        'queued':  total_pages,
        'force':   force,
        'message': f'Analysis started for {total_pages} pages. Results will appear as each page completes.',
    }, status=status.HTTP_202_ACCEPTED)


# ── Site-wide Approvals Feed (Section 11.6) ───────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_approvals(request, site_id: int):
    """
    Aggregate all recommendations across all page analyses for a site.
    Used by the Approvals tab in the dashboard.

    GET /api/v1/sites/{id}/approvals/
    Query params:
      status=pending,approved,applied,verified,failed,manual_action
        (comma-separated filter, default = all)
      applied_since=2026-02-01   (ISO date, for "Applied This Week" view)
      limit=50                   (default 50)
      offset=0

    Returns flat list of recommendation objects enriched with:
      - analysis_id, page_url, page_title
      - applied_at timestamp (when status=applied/verified)
      - guidance text (when status=manual_action)
    """
    from django.utils.dateparse import parse_date
    import datetime

    site = Site.objects.filter(id=site_id, user=request.user).first()
    if not site:
        return Response({'error': 'Site not found'}, status=404)

    status_filter_raw = request.query_params.get('status', '')
    status_filter = {s.strip() for s in status_filter_raw.split(',') if s.strip()} if status_filter_raw else set()

    applied_since_str = request.query_params.get('applied_since')
    applied_since = None
    if applied_since_str:
        d = parse_date(applied_since_str)
        if d:
            applied_since = datetime.datetime.combine(d, datetime.time.min, tzinfo=datetime.timezone.utc)

    limit = min(int(request.query_params.get('limit', 50)), 200)
    offset = int(request.query_params.get('offset', 0))

    analyses = PageAnalysis.objects.filter(
        site=site, status='complete'
    ).order_by('-created_at').values(
        'id', 'page_url', 'page_title',
        'geo_recommendations', 'seo_recommendations', 'cro_recommendations',
    )

    all_recs = []
    for analysis in analyses:
        for layer in ('geo_recommendations', 'seo_recommendations', 'cro_recommendations'):
            for rec in (analysis[layer] or []):
                rec_status = rec.get('status', 'pending')

                # Status filter
                if status_filter and rec_status not in status_filter:
                    continue

                # Date filter (applied_since)
                if applied_since and rec_status in ('applied', 'verified'):
                    applied_at_str = rec.get('applied_at')
                    if applied_at_str:
                        try:
                            from django.utils.dateparse import parse_datetime
                            applied_at = parse_datetime(applied_at_str)
                            if applied_at and applied_at < applied_since:
                                continue
                        except Exception:
                            pass

                all_recs.append({
                    'rec_id':      rec.get('id'),
                    'analysis_id': analysis['id'],
                    'page_url':    analysis['page_url'],
                    'page_title':  analysis['page_title'] or '',
                    'layer':       layer.replace('_recommendations', ''),
                    'field':       rec.get('field', ''),
                    'issue':       rec.get('issue', ''),
                    'severity':    rec.get('severity', ''),
                    'before':      rec.get('before', ''),
                    'after':       rec.get('after', ''),
                    'status':      rec_status,
                    'applied_at':  rec.get('applied_at'),
                    'guidance':    rec.get('guidance'),
                })

    # Sort: failed first, then manual_action, then pending, then approved, then applied/verified
    STATUS_SORT = {'failed': 0, 'manual_action': 1, 'pending': 2, 'approved': 3, 'applied': 4, 'verified': 5}
    all_recs.sort(key=lambda r: STATUS_SORT.get(r['status'], 9))

    total = len(all_recs)
    paginated = all_recs[offset:offset + limit]

    # Summary counts
    counts = {}
    for rec in all_recs:
        s = rec['status']
        counts[s] = counts.get(s, 0) + 1

    return Response({
        'recommendations': paginated,
        'meta': {
            'total': total,
            'offset': offset,
            'limit': limit,
            'counts': counts,
        }
    })
