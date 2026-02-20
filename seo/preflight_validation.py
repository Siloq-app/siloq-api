"""
9-check preflight validation pipeline for content generation.
Runs before any content is generated to prevent keyword cannibalization.
"""
import logging
from django.utils import timezone

from .preflight_utils import (
    extract_keywords,
    get_intent_skeleton,
    levenshtein_similarity,
    calculate_keyword_overlap,
)

logger = logging.getLogger(__name__)


def _make_check(name, status, detail=None, match_info=None):
    return {
        'check': name,
        'status': status,  # 'pass', 'warn', 'block'
        'detail': detail or '',
        'match_info': match_info,
    }


def _check_keyword_registry(site, proposed_keyword):
    """Check 1: Keyword Registry Lookup — exact match (BLOCK), substring (WARN)."""
    from .models import KeywordAssignment
    try:
        assignments = KeywordAssignment.objects.filter(site=site, status='active')
        for ka in assignments:
            if ka.keyword.lower() == proposed_keyword.lower():
                return _make_check(
                    'keyword_registry', 'block',
                    f'Exact keyword "{proposed_keyword}" already assigned to page: {ka.page}',
                    {'existing_keyword': ka.keyword, 'page_id': ka.page_id},
                )
        # Substring check
        for ka in assignments:
            kw_lower = ka.keyword.lower()
            pk_lower = proposed_keyword.lower()
            if pk_lower in kw_lower or kw_lower in pk_lower:
                return _make_check(
                    'keyword_registry', 'warn',
                    f'Substring overlap: "{proposed_keyword}" ↔ "{ka.keyword}" (page: {ka.page})',
                    {'existing_keyword': ka.keyword, 'page_id': ka.page_id},
                )
    except Exception as e:
        logger.warning(f"Keyword registry check failed (graceful): {e}")
    return _make_check('keyword_registry', 'pass')


def _check_title_keyword_overlap(site, proposed_title):
    """Check 2: Title Keyword Overlap — BLOCK ≥85%, WARN ≥70%."""
    from .models import Page
    try:
        proposed_kws = extract_keywords(proposed_title)
        if not proposed_kws:
            return _make_check('title_keyword_overlap', 'pass')
        existing_pages = Page.objects.filter(site=site, status='publish').values_list('title', flat=True)
        for title in existing_pages:
            existing_kws = extract_keywords(title)
            overlap = calculate_keyword_overlap(proposed_kws, existing_kws)
            if overlap >= 0.85:
                return _make_check(
                    'title_keyword_overlap', 'block',
                    f'{overlap:.0%} keyword overlap with "{title}"',
                    {'existing_title': title, 'overlap': round(overlap, 3)},
                )
            if overlap >= 0.70:
                return _make_check(
                    'title_keyword_overlap', 'warn',
                    f'{overlap:.0%} keyword overlap with "{title}"',
                    {'existing_title': title, 'overlap': round(overlap, 3)},
                )
    except Exception as e:
        logger.warning(f"Title keyword overlap check failed (graceful): {e}")
    return _make_check('title_keyword_overlap', 'pass')


def _check_intent_skeleton(site, proposed_title):
    """Check 3: Intent Skeleton Match — BLOCK ≥90%, WARN ≥75%."""
    from .models import Page
    try:
        proposed_skel = get_intent_skeleton(proposed_title)
        if not proposed_skel:
            return _make_check('intent_skeleton', 'pass')
        existing_pages = Page.objects.filter(site=site, status='publish').values_list('title', flat=True)
        for title in existing_pages:
            existing_skel = get_intent_skeleton(title)
            overlap = calculate_keyword_overlap(proposed_skel, existing_skel)
            if overlap >= 0.90:
                return _make_check(
                    'intent_skeleton', 'block',
                    f'{overlap:.0%} skeleton match with "{title}"',
                    {'existing_title': title, 'overlap': round(overlap, 3)},
                )
            if overlap >= 0.75:
                return _make_check(
                    'intent_skeleton', 'warn',
                    f'{overlap:.0%} skeleton match with "{title}"',
                    {'existing_title': title, 'overlap': round(overlap, 3)},
                )
    except Exception as e:
        logger.warning(f"Intent skeleton check failed (graceful): {e}")
    return _make_check('intent_skeleton', 'pass')


def _check_unique_modifier(site, proposed_title, silo_id):
    """Check 4: Unique Modifier Check — BLOCK if 0 unique modifiers in silo."""
    if not silo_id:
        return _make_check('unique_modifier', 'pass', 'No silo_id provided, skipping.')
    from .models import KeywordAssignment, Page
    try:
        # Get all titles in this silo
        silo_assignments = KeywordAssignment.objects.filter(
            site=site, silo_id=silo_id, status='active'
        ).select_related('page')
        silo_titles = [ka.page.title for ka in silo_assignments if ka.page]
        if not silo_titles:
            return _make_check('unique_modifier', 'pass', 'No existing titles in silo.')

        proposed_kws = set(extract_keywords(proposed_title))
        all_other_kws = set()
        for t in silo_titles:
            all_other_kws.update(extract_keywords(t))

        unique = proposed_kws - all_other_kws
        if len(unique) == 0:
            return _make_check(
                'unique_modifier', 'block',
                f'No unique modifiers vs {len(silo_titles)} existing silo titles',
                {'silo_titles_count': len(silo_titles)},
            )
    except Exception as e:
        logger.warning(f"Unique modifier check failed (graceful): {e}")
    return _make_check('unique_modifier', 'pass')


def _check_slug_similarity(site, proposed_slug):
    """Check 5: Slug Similarity — BLOCK ≥85%, WARN ≥70%."""
    if not proposed_slug:
        return _make_check('slug_similarity', 'pass', 'No slug provided, skipping.')
    from .models import Page
    try:
        existing_pages = Page.objects.filter(site=site, status='publish')
        for page in existing_pages:
            # Extract slug from URL
            existing_slug = page.url.rstrip('/').split('/')[-1] if page.url else ''
            if not existing_slug:
                continue
            sim = levenshtein_similarity(proposed_slug, existing_slug)
            if sim >= 0.85:
                return _make_check(
                    'slug_similarity', 'block',
                    f'{sim:.0%} slug similarity: "{proposed_slug}" vs "{existing_slug}"',
                    {'existing_slug': existing_slug, 'similarity': round(sim, 3)},
                )
            if sim >= 0.70:
                return _make_check(
                    'slug_similarity', 'warn',
                    f'{sim:.0%} slug similarity: "{proposed_slug}" vs "{existing_slug}"',
                    {'existing_slug': existing_slug, 'similarity': round(sim, 3)},
                )
    except Exception as e:
        logger.warning(f"Slug similarity check failed (graceful): {e}")
    return _make_check('slug_similarity', 'pass')


def _check_h1_cross(site, proposed_title, proposed_h1):
    """Check 6: H1 Cross-Check — compare title+H1 vs all existing titles+H1s. BLOCK ≥80%."""
    try:
        # Try PageMetadata model first (v2 schema), fall back to Page
        try:
            from .models import PageMetadata
            pages = PageMetadata.objects.filter(site_id=site.id, is_indexable=True).values_list('title_tag', 'h1_tag')
            existing_texts = []
            for title_tag, h1_tag in pages:
                if title_tag:
                    existing_texts.append(title_tag)
                if h1_tag:
                    existing_texts.append(h1_tag)
        except (ImportError, Exception):
            from .models import Page
            existing_texts = list(Page.objects.filter(site=site, status='publish').values_list('title', flat=True))

        proposed_texts = [t for t in [proposed_title, proposed_h1] if t]
        for proposed in proposed_texts:
            proposed_kws = extract_keywords(proposed)
            for existing in existing_texts:
                existing_kws = extract_keywords(existing)
                overlap = calculate_keyword_overlap(proposed_kws, existing_kws)
                if overlap >= 0.80:
                    return _make_check(
                        'h1_cross_check', 'block',
                        f'{overlap:.0%} overlap: "{proposed}" vs "{existing}"',
                        {'proposed': proposed, 'existing': existing, 'overlap': round(overlap, 3)},
                    )
    except Exception as e:
        logger.warning(f"H1 cross-check failed (graceful): {e}")
    return _make_check('h1_cross_check', 'pass')


def _check_silo_boundary(site, proposed_keyword, silo_id):
    """Check 7: Silo Boundary Enforcement — keyword must belong to assigned silo."""
    if not silo_id:
        return _make_check('silo_boundary', 'pass', 'No silo_id, skipping.')
    try:
        try:
            from .models import SiloKeyword
            # Check if keyword exists in another silo
            other_silo = SiloKeyword.objects.filter(
                site_id=site.id, keyword__iexact=proposed_keyword
            ).exclude(silo_id=silo_id).first()
            if other_silo:
                return _make_check(
                    'silo_boundary', 'block',
                    f'Keyword "{proposed_keyword}" belongs to silo {other_silo.silo_id}, not {silo_id}',
                    {'wrong_silo_id': str(other_silo.silo_id), 'assigned_silo_id': str(silo_id)},
                )
        except (ImportError, Exception):
            # Check via KeywordAssignment if SiloKeyword not available
            from .models import KeywordAssignment
            other = KeywordAssignment.objects.filter(
                site=site, keyword__iexact=proposed_keyword, status='active'
            ).exclude(silo_id=silo_id).first()
            if other:
                return _make_check(
                    'silo_boundary', 'block',
                    f'Keyword "{proposed_keyword}" assigned to silo {other.silo_id}, not {silo_id}',
                    {'wrong_silo_id': other.silo_id, 'assigned_silo_id': silo_id},
                )
    except Exception as e:
        logger.warning(f"Silo boundary check failed (graceful): {e}")
    return _make_check('silo_boundary', 'pass')


def _check_url_depth(proposed_slug, page_type):
    """Check 8: URL Depth Check — Hub=1, Spoke=2, WARN at 3+."""
    if not proposed_slug:
        return _make_check('url_depth', 'pass', 'No slug provided, skipping.')
    depth = proposed_slug.strip('/').count('/') + 1
    expected = 1 if page_type == 'hub' else 2
    if depth > expected and depth >= 3:
        return _make_check(
            'url_depth', 'warn',
            f'URL depth {depth} exceeds expected {expected} for {page_type} page',
            {'depth': depth, 'expected': expected, 'page_type': page_type},
        )
    return _make_check('url_depth', 'pass')


def _check_canonical_tag(site, proposed_slug):
    """Check 9: Canonical Tag Check — no other page should canonical to similar URL."""
    if not proposed_slug:
        return _make_check('canonical_tag', 'pass', 'No slug provided, skipping.')
    try:
        try:
            from .models import PageMetadata
            pages = PageMetadata.objects.filter(site_id=site.id).exclude(
                canonical_url__isnull=True
            ).exclude(canonical_url='').values_list('canonical_url', 'page_url')
            for canonical_url, page_url in pages:
                sim = levenshtein_similarity(proposed_slug, canonical_url.rstrip('/').split('/')[-1])
                if sim >= 0.85:
                    return _make_check(
                        'canonical_tag', 'block',
                        f'Page "{page_url}" has canonical pointing to similar URL (sim={sim:.0%})',
                        {'page_url': page_url, 'canonical_url': canonical_url, 'similarity': round(sim, 3)},
                    )
        except (ImportError, Exception):
            pass  # No PageMetadata table yet — skip gracefully
    except Exception as e:
        logger.warning(f"Canonical tag check failed (graceful): {e}")
    return _make_check('canonical_tag', 'pass')


def _log_validation(site, proposed_title, proposed_keyword, proposed_slug,
                    proposed_h1, silo_id, page_type, result):
    """Log validation run to ValidationLog if available."""
    try:
        from .models import ValidationLog
        ValidationLog.objects.create(
            site_id=site.id,
            proposed_title=proposed_title,
            proposed_slug=proposed_slug,
            proposed_h1=proposed_h1,
            proposed_keyword=proposed_keyword,
            proposed_silo_id=silo_id,
            proposed_page_type=page_type,
            overall_status=result['status'],
            blocking_check=result.get('blocking_check'),
            check_results=result['checks'],
            validation_source='generation',
        )
    except Exception as e:
        logger.warning(f"Failed to log validation (non-fatal): {e}")


def run_preflight_validation(site, proposed_title, proposed_keyword,
                             proposed_slug=None, proposed_h1=None,
                             silo_id=None, page_type='spoke'):
    """
    Run all 9 preflight checks sequentially.

    Returns:
        {
            'status': 'pass' | 'warn' | 'block',
            'blocking_check': str | None,
            'checks': [list of check results],
            'warnings': [list of warning check results],
        }
    """
    checks = []
    warnings = []
    blocking_check = None
    overall_status = 'pass'

    check_funcs = [
        lambda: _check_keyword_registry(site, proposed_keyword),
        lambda: _check_title_keyword_overlap(site, proposed_title),
        lambda: _check_intent_skeleton(site, proposed_title),
        lambda: _check_unique_modifier(site, proposed_title, silo_id),
        lambda: _check_slug_similarity(site, proposed_slug),
        lambda: _check_h1_cross(site, proposed_title, proposed_h1),
        lambda: _check_silo_boundary(site, proposed_keyword, silo_id),
        lambda: _check_url_depth(proposed_slug, page_type),
        lambda: _check_canonical_tag(site, proposed_slug),
    ]

    for func in check_funcs:
        result = func()
        checks.append(result)
        if result['status'] == 'block' and overall_status != 'block':
            overall_status = 'block'
            blocking_check = result['check']
        elif result['status'] == 'warn':
            warnings.append(result)
            if overall_status == 'pass':
                overall_status = 'warn'

    final = {
        'status': overall_status,
        'blocking_check': blocking_check,
        'checks': checks,
        'warnings': warnings,
    }

    # Log asynchronously (best-effort)
    _log_validation(site, proposed_title, proposed_keyword, proposed_slug,
                    proposed_h1, silo_id, page_type, final)

    return final
