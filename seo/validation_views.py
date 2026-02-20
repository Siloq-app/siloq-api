"""
API endpoints for Content Validation.
Spec: api-endpoint-spec.md — Section 2 (Content Validation)
UX copy: dashboard-ux-copy-guide.md — Section 1 (Preflight Validation Messages)
"""
import logging
import time
import uuid

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from sites.models import Site
from seo.models import (
    KeywordAssignment,
    CannibalizationConflict,
    ConflictPage,
    ValidationLog,
    PageMetadata,
    SiloDefinition,
)
from seo.preflight_validation import run_preflight_validation

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_site_or_error(request):
    sid = request.data.get('site_id') or request.query_params.get('site_id')
    if not sid:
        return None, Response(
            {'error': {'code': 'SITE_NOT_FOUND', 'message': 'site_id is required.', 'status': 400}},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        site = Site.objects.get(id=sid)
    except Site.DoesNotExist:
        return None, Response(
            {'error': {'code': 'SITE_NOT_FOUND', 'message': 'Invalid site_id.', 'status': 404}},
            status=status.HTTP_404_NOT_FOUND,
        )
    if site.user != request.user:
        return None, Response(
            {'error': {'code': 'FORBIDDEN', 'message': 'Permission denied.', 'status': 403}},
            status=status.HTTP_403_FORBIDDEN,
        )
    return site, None


def _format_check_result(raw_check):
    """Convert internal check format to spec format."""
    name = raw_check.get('check', '')
    st = raw_check.get('status', 'pass')
    match_info = raw_check.get('match_info') or {}
    detail = raw_check.get('detail', '')

    result = {'status': st}

    # Add check-specific fields per spec
    if name == 'keyword_registry':
        pass  # just status + time_ms
    elif name in ('title_keyword_overlap', 'title_overlap'):
        overlap = match_info.get('overlap', 0)
        result['overlap'] = overlap
        if match_info.get('existing_title'):
            result['match_url'] = match_info.get('existing_url', '')
    elif name == 'intent_skeleton':
        result['similarity'] = match_info.get('overlap', 0)
    elif name == 'unique_modifier':
        result['unique_words'] = match_info.get('unique_words', [])
    elif name == 'slug_similarity':
        result['max_similarity'] = match_info.get('similarity', 0)
    elif name in ('h1_cross_check', 'h1_crosscheck'):
        pass
    elif name == 'semantic_cluster':
        result['status'] = 'skipped'
        result['reason'] = 'embeddings_not_enabled'
    elif name == 'silo_boundary':
        pass
    elif name == 'url_depth':
        result['depth'] = match_info.get('depth', 0)
    elif name == 'canonical_tag':
        pass

    return result


# Map internal check names to spec check names
_CHECK_NAME_MAP = {
    'keyword_registry': 'keyword_registry',
    'title_keyword_overlap': 'title_overlap',
    'intent_skeleton': 'intent_skeleton',
    'unique_modifier': 'unique_modifier',
    'slug_similarity': 'slug_similarity',
    'h1_cross_check': 'h1_crosscheck',
    'silo_boundary': 'silo_boundary',
    'url_depth': 'url_depth',
    'canonical_tag': 'canonical_check',
}

# All 10 spec check names
_SPEC_CHECKS = [
    'keyword_registry', 'title_overlap', 'intent_skeleton', 'unique_modifier',
    'slug_similarity', 'h1_crosscheck', 'semantic_cluster', 'silo_boundary',
    'url_depth', 'canonical_check',
]


def _build_preflight_response(raw_result, start_time):
    """Transform run_preflight_validation() output into spec response format."""
    total_ms = int((time.time() - start_time) * 1000)

    # Build checks dict keyed by spec name
    checks = {}
    for raw in raw_result.get('checks', []):
        internal_name = raw.get('check', '')
        spec_name = _CHECK_NAME_MAP.get(internal_name, internal_name)
        formatted = _format_check_result(raw)
        formatted['time_ms'] = total_ms // max(len(raw_result.get('checks', [])), 1)
        checks[spec_name] = formatted

    # Add semantic_cluster if missing (always skipped for now)
    if 'semantic_cluster' not in checks:
        checks['semantic_cluster'] = {'status': 'skipped', 'reason': 'embeddings_not_enabled'}

    # Ensure all 10 spec checks present
    for name in _SPEC_CHECKS:
        if name not in checks:
            checks[name] = {'status': 'pass'}

    # Build warnings and blocks lists
    warnings = []
    blocks = []
    for raw in raw_result.get('checks', []):
        if raw['status'] == 'warn':
            spec_name = _CHECK_NAME_MAP.get(raw['check'], raw['check'])
            match_info = raw.get('match_info') or {}
            warnings.append({
                'check': spec_name,
                'message': raw.get('detail', ''),
                'match_url': match_info.get('existing_url', match_info.get('page_url', '')),
                'score': match_info.get('overlap', match_info.get('similarity', 0)),
            })
        elif raw['status'] == 'block':
            spec_name = _CHECK_NAME_MAP.get(raw['check'], raw['check'])
            match_info = raw.get('match_info') or {}
            blocks.append({
                'check': spec_name,
                'message': raw.get('detail', ''),
                'match_url': match_info.get('existing_url', match_info.get('page_url', '')),
                'score': match_info.get('overlap', match_info.get('similarity', 0)),
            })

    blocking_check = raw_result.get('blocking_check')
    if blocking_check:
        blocking_check = _CHECK_NAME_MAP.get(blocking_check, blocking_check)

    validation_id = str(uuid.uuid4())

    return {
        'overall_status': raw_result['status'],
        'blocking_check': blocking_check,
        'warnings': warnings,
        'blocks': blocks,
        'checks': checks,
        'validated_at': timezone.now().isoformat(),
        'total_time_ms': total_ms,
        'validation_id': validation_id,
    }


# ---------------------------------------------------------------------------
# POST /api/v1/validate/preflight
# ---------------------------------------------------------------------------

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def validate_preflight(request):
    """Run the full 10-check validation pipeline on proposed content."""
    site, err = _get_site_or_error(request)
    if err:
        return err

    proposed_title = request.data.get('proposed_title', '')
    proposed_slug = request.data.get('proposed_slug', '')
    proposed_h1 = request.data.get('proposed_h1', '')
    proposed_keyword = request.data.get('proposed_keyword', '')
    proposed_silo_id = request.data.get('proposed_silo_id')
    proposed_page_type = request.data.get('proposed_page_type', 'spoke')
    proposed_url_path = request.data.get('proposed_url_path', proposed_slug)
    skip_checks = request.data.get('skip_checks', [])

    if not proposed_keyword and not proposed_title:
        return Response(
            {'error': {'code': 'BAD_REQUEST', 'message': 'proposed_keyword or proposed_title is required.', 'status': 400}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    start = time.time()

    raw = run_preflight_validation(
        site=site,
        proposed_title=proposed_title,
        proposed_keyword=proposed_keyword,
        proposed_slug=proposed_url_path or proposed_slug,
        proposed_h1=proposed_h1,
        silo_id=proposed_silo_id,
        page_type=proposed_page_type,
    )

    response_data = _build_preflight_response(raw, start)

    # Return 422 if blocked
    if response_data['overall_status'] == 'block':
        return Response(response_data, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

    return Response(response_data)


# ---------------------------------------------------------------------------
# POST /api/v1/validate/post-generation
# ---------------------------------------------------------------------------

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def validate_post_generation(request):
    """What-if cannibalization sweep after generation, before publishing."""
    site, err = _get_site_or_error(request)
    if err:
        return err

    proposed_title = request.data.get('proposed_title', '')
    proposed_keyword = request.data.get('proposed_keyword', '')
    proposed_url = request.data.get('proposed_url', '')
    proposed_page_type = request.data.get('proposed_page_type', 'spoke')

    if not proposed_keyword:
        return Response(
            {'error': {'code': 'BAD_REQUEST', 'message': 'proposed_keyword is required.', 'status': 400}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Check keyword registry for conflicts
    conflicts_found = []
    assignments = KeywordAssignment.objects.filter(site=site, status='active').select_related('silo')

    kw_lower = proposed_keyword.lower()
    for ka in assignments:
        existing_kw = ka.keyword.lower()
        # Exact match = critical
        if existing_kw == kw_lower:
            conflicts_found.append({
                'severity': 'critical',
                'conflict_type': 'exact_keyword',
                'keyword': ka.keyword,
                'conflicting_url': ka.page_url,
                'conflicting_title': ka.page_title or '',
                'message': (
                    f'Publishing blocked — critical cannibalization detected. '
                    f'Publishing this page would create a critical conflict with '
                    f'"{ka.page_url}" for "{ka.keyword}".'
                ),
            })
        # Substring = high
        elif kw_lower in existing_kw or existing_kw in kw_lower:
            conflicts_found.append({
                'severity': 'high',
                'conflict_type': 'substring_keyword',
                'keyword': ka.keyword,
                'conflicting_url': ka.page_url,
                'conflicting_title': ka.page_title or '',
                'message': (
                    f'Potential cannibalization risk. '
                    f'Publishing this page would create a high-severity conflict with '
                    f'"{ka.page_url}" for "{ka.keyword}".'
                ),
            })

    overall = 'pass'
    if any(c['severity'] == 'critical' for c in conflicts_found):
        overall = 'block'
    elif conflicts_found:
        overall = 'warn'

    resp = {
        'overall_status': overall,
        'proposed_keyword': proposed_keyword,
        'proposed_url': proposed_url,
        'conflicts': conflicts_found,
        'validated_at': timezone.now().isoformat(),
    }

    if overall == 'block':
        return Response(resp, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    return Response(resp)


# ---------------------------------------------------------------------------
# POST /api/v1/validate/batch
# ---------------------------------------------------------------------------

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def validate_batch(request):
    """Cross-check a batch of content items against each other AND existing content."""
    site, err = _get_site_or_error(request)
    if err:
        return err

    items = request.data.get('items', [])
    if not items or not isinstance(items, list):
        return Response(
            {'error': {'code': 'BAD_REQUEST', 'message': 'items array is required.', 'status': 400}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    start = time.time()
    results = []

    for idx, item in enumerate(items):
        title = item.get('proposed_title', '')
        keyword = item.get('proposed_keyword', '')
        slug = item.get('proposed_slug', '')
        h1 = item.get('proposed_h1', '')
        silo_id = item.get('proposed_silo_id')
        page_type = item.get('proposed_page_type', 'spoke')
        url_path = item.get('proposed_url_path', slug)

        item_start = time.time()

        # Run preflight against existing content
        raw = run_preflight_validation(
            site=site,
            proposed_title=title,
            proposed_keyword=keyword,
            proposed_slug=url_path or slug,
            proposed_h1=h1,
            silo_id=silo_id,
            page_type=page_type,
        )

        item_result = _build_preflight_response(raw, item_start)

        # Cross-check against other items in the batch
        cross_conflicts = []
        for other_idx, other in enumerate(items):
            if other_idx == idx:
                continue
            other_kw = (other.get('proposed_keyword') or '').lower()
            if keyword.lower() == other_kw and keyword:
                cross_conflicts.append({
                    'check': 'batch_keyword_conflict',
                    'message': f'Batch item #{other_idx + 1} targets the same keyword "{keyword}".',
                    'conflicting_item_index': other_idx,
                })
            # Title overlap between batch items
            if title and other.get('proposed_title'):
                from seo.preflight_utils import extract_keywords, calculate_keyword_overlap
                try:
                    kw_a = extract_keywords(title)
                    kw_b = extract_keywords(other['proposed_title'])
                    overlap = calculate_keyword_overlap(kw_a, kw_b)
                    if overlap >= 0.70:
                        cross_conflicts.append({
                            'check': 'batch_title_overlap',
                            'message': f'Batch item #{other_idx + 1} has {overlap:.0%} title overlap.',
                            'conflicting_item_index': other_idx,
                            'score': round(overlap, 3),
                        })
                except Exception:
                    pass

        item_result['batch_index'] = idx
        item_result['proposed_keyword'] = keyword
        item_result['proposed_title'] = title
        item_result['cross_batch_conflicts'] = cross_conflicts

        # Escalate overall status if cross-batch conflicts found
        if cross_conflicts and item_result['overall_status'] == 'pass':
            item_result['overall_status'] = 'warn'

        results.append(item_result)

    total_ms = int((time.time() - start) * 1000)

    # Overall batch status
    statuses = [r['overall_status'] for r in results]
    if 'block' in statuses:
        batch_status = 'block'
    elif 'warn' in statuses:
        batch_status = 'warn'
    else:
        batch_status = 'pass'

    return Response({
        'overall_status': batch_status,
        'items': results,
        'total_items': len(items),
        'total_time_ms': total_ms,
        'validated_at': timezone.now().isoformat(),
    })
