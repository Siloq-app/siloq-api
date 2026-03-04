"""
Internal Linking Context API
─────────────────────────────

GET  /api/v1/sites/{site_id}/pages/{page_id}/related-pages/
     → Returns the internal linking map for a page (Reverse Silo architecture)

POST /api/v1/sites/{site_id}/pages/{page_id}/suggest-widget-edit/
     → AI-powered content edit suggestions with internal link weaving
"""
import logging
import os
from collections import defaultdict
from urllib.parse import urlparse

from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from sites.models import Site
from seo.models import (
    Page,
    InternalLink,
    SiloDefinition,
    KeywordAssignment,
)

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')


# ─── Helpers ────────────────────────────────────────────────────────────────


def _normalize_url(url: str) -> str:
    """Strip scheme/host, lowercase, ensure trailing slash."""
    if not url:
        return ''
    parsed = urlparse(url)
    path = parsed.path.lower().rstrip('/') + '/'
    return path


def _get_primary_keyword(page: Page, site, silo_ids: list | None = None) -> str:
    """
    Return the primary keyword for a page.
    Priority: KeywordAssignment with is_primary or highest clicks → page title fallback.
    """
    qs = KeywordAssignment.objects.filter(
        site=site,
        page_id=page.id,
        status='active',
    )
    if silo_ids:
        qs = qs.filter(silo_id__in=silo_ids)

    # Prefer keyword with most clicks (best GSC signal)
    assignment = qs.order_by('-gsc_clicks', '-gsc_impressions').first()
    if assignment:
        return assignment.keyword

    # Fallback: try matching by URL
    normalized = _normalize_url(page.url)
    assignment_by_url = (
        KeywordAssignment.objects
        .filter(site=site, status='active')
        .extra(where=["LOWER(page_url) LIKE %s"], params=[f'%{normalized.rstrip("/")}%'])
        .order_by('-gsc_clicks', '-gsc_impressions')
        .first()
    )
    if assignment_by_url:
        return assignment_by_url.keyword

    return page.title


def _derive_anchor_text(keyword: str) -> str:
    """Derive a natural anchor text from a keyword (drop location suffixes if present)."""
    return keyword.strip()


def _get_page_silo_role(page: Page, site) -> tuple:
    """
    Determine a page's role in the silo architecture.

    Returns: (role, silo_definitions)
      role: 'hub' | 'spoke' | 'supporting' | 'unknown'
      silo_definitions: list of SiloDefinition objects this page belongs to
    """
    # Check if page is a hub
    hub_silos = list(SiloDefinition.objects.filter(
        site=site, status='active', hub_page_id=page.id,
    ))
    if hub_silos:
        return 'hub', hub_silos

    # Find silos via KeywordAssignment
    assignments = list(KeywordAssignment.objects.filter(
        site=site, page_id=page.id, status='active',
        silo_id__isnull=False,
    ).select_related('silo'))

    if not assignments:
        # Try matching by URL
        normalized = _normalize_url(page.url)
        assignments = list(KeywordAssignment.objects.filter(
            site=site, status='active', silo_id__isnull=False,
        ).select_related('silo').extra(
            where=["LOWER(page_url) LIKE %s"],
            params=[f'%{normalized.rstrip("/")}%'],
        ))

    if not assignments:
        return 'unknown', []

    silos = list({a.silo for a in assignments if a.silo})

    # Check assignment page_type field
    assigned_types = {(a.page_type or '').lower() for a in assignments}

    if assigned_types & {'hub', 'pillar'}:
        return 'hub', silos

    # Money pages in a silo are spokes
    if page.page_type_classification == 'money':
        return 'spoke', silos

    # Supporting content pages
    if page.page_type_classification == 'supporting':
        return 'supporting', silos

    # Default: if it's in a silo but not the hub, treat as spoke
    return 'spoke', silos


def _serialize_related_page(
    page: Page,
    relationship: str,
    primary_keyword: str,
    already_linked: bool,
) -> dict:
    return {
        'id': page.id,
        'title': page.title,
        'url': page.url,
        'page_type': page.page_type_classification,
        'primary_keyword': primary_keyword,
        'relationship': relationship,
        'suggested_anchor_text': _derive_anchor_text(primary_keyword),
        'already_linked': already_linked,
    }


# ─── GET /related-pages/ ────────────────────────────────────────────────────


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_related_pages(request, site_id: int, page_id: int):
    """
    GET /api/v1/sites/{site_id}/pages/{page_id}/related-pages/

    Returns the internal linking map for a page based on the Reverse Silo architecture.
    """
    site = get_object_or_404(Site, id=site_id, user=request.user)
    page = get_object_or_404(Page, id=page_id, site=site)

    role, silos = _get_page_silo_role(page, site)
    silo_ids = [s.id for s in silos]

    # Pre-fetch existing link pairs for this page
    outgoing_targets = set(
        InternalLink.objects
        .filter(site=site, source_page=page, is_valid=True)
        .values_list('target_page_id', flat=True)
    )
    incoming_sources = set(
        InternalLink.objects
        .filter(site=site, target_page=page, is_valid=True)
        .values_list('source_page_id', flat=True)
    )

    should_link_to = []
    should_link_from = []

    if role == 'hub':
        # Hub doesn't link up. should_link_from = all spoke/supporting pages in its silos.
        _collect_silo_pages_linking_from(
            site, page, silo_ids, incoming_sources, should_link_from,
        )

    elif role == 'spoke':
        # Spoke links TO its hub. should_link_from = supporting pages in the same silo.
        for silo in silos:
            hub_page = _resolve_hub_page(silo, site)
            if hub_page and hub_page.id != page.id:
                kw = _get_primary_keyword(hub_page, site, silo_ids)
                should_link_to.append(_serialize_related_page(
                    hub_page, 'hub', kw, hub_page.id in outgoing_targets,
                ))

        _collect_supporting_pages_linking_from(
            site, page, silo_ids, incoming_sources, should_link_from,
        )

    elif role == 'supporting':
        # Supporting links TO the spoke page in the same silo.
        _collect_spoke_pages_linking_to(
            site, page, silo_ids, outgoing_targets, should_link_to,
        )
        # should_link_from = [] for supporting pages

    else:
        # Unknown role — no silo relationships found
        pass

    primary_keyword = _get_primary_keyword(page, site, silo_ids)

    return Response({
        'current_page': {
            'id': page.id,
            'title': page.title,
            'url': page.url,
            'page_type': page.page_type_classification,
            'silo_role': role,
            'primary_keyword': primary_keyword,
        },
        'should_link_to': should_link_to,
        'should_link_from': should_link_from,
    })


def _resolve_hub_page(silo: SiloDefinition, site) -> Page | None:
    """Resolve the hub Page object for a silo."""
    if silo.hub_page_id:
        try:
            return Page.objects.get(id=silo.hub_page_id, site=site)
        except Page.DoesNotExist:
            pass
    if silo.hub_page_url:
        normalized = _normalize_url(silo.hub_page_url)
        for p in Page.objects.filter(site=site):
            if _normalize_url(p.url) == normalized:
                return p
    return None


def _get_silo_pages(site, silo_ids: list, exclude_page_id: int | None = None) -> list:
    """Get all pages assigned to the given silos."""
    assignments = KeywordAssignment.objects.filter(
        site=site, silo_id__in=silo_ids, status='active',
    ).values('page_id', 'page_type').distinct()

    page_ids = set()
    for a in assignments:
        pid = a.get('page_id')
        if pid and pid != exclude_page_id:
            page_ids.add(pid)

    if not page_ids:
        return []

    return list(Page.objects.filter(id__in=page_ids, site=site))


def _collect_silo_pages_linking_from(site, current_page, silo_ids, incoming_sources, result_list):
    """For a hub page: collect all spoke/supporting pages that should link to it."""
    pages = _get_silo_pages(site, silo_ids, exclude_page_id=current_page.id)
    for p in pages:
        kw = _get_primary_keyword(p, site, silo_ids)
        role_of_p, _ = _get_page_silo_role(p, site)
        relationship = role_of_p if role_of_p in ('spoke', 'supporting') else 'spoke'
        result_list.append(_serialize_related_page(
            p, relationship, kw, p.id in incoming_sources,
        ))


def _collect_supporting_pages_linking_from(site, current_page, silo_ids, incoming_sources, result_list):
    """For a spoke page: collect supporting pages in the same silo."""
    pages = _get_silo_pages(site, silo_ids, exclude_page_id=current_page.id)
    for p in pages:
        # Only supporting pages link FROM to spoke
        if p.page_type_classification != 'supporting':
            continue
        # Skip hub pages
        hub_check = SiloDefinition.objects.filter(
            site=current_page.site, hub_page_id=p.id, status='active',
        ).exists()
        if hub_check:
            continue
        kw = _get_primary_keyword(p, site, silo_ids)
        result_list.append(_serialize_related_page(
            p, 'supporting', kw, p.id in incoming_sources,
        ))


def _collect_spoke_pages_linking_to(site, current_page, silo_ids, outgoing_targets, result_list):
    """For a supporting page: collect spoke pages it should link TO."""
    pages = _get_silo_pages(site, silo_ids, exclude_page_id=current_page.id)
    for p in pages:
        # Supporting links to spoke (money) pages
        if p.page_type_classification != 'money':
            continue
        # Skip hub pages
        hub_check = SiloDefinition.objects.filter(
            site=current_page.site, hub_page_id=p.id, status='active',
        ).exists()
        if hub_check:
            continue
        kw = _get_primary_keyword(p, site, silo_ids)
        result_list.append(_serialize_related_page(
            p, 'spoke', kw, p.id in outgoing_targets,
        ))


# ─── POST /suggest-widget-edit/ ─────────────────────────────────────────────


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def suggest_widget_edit(request, site_id: int, page_id: int):
    """
    POST /api/v1/sites/{site_id}/pages/{page_id}/suggest-widget-edit/

    Body:
    {
      "widget_content": "<p>Current widget HTML…</p>",
      "edit_instruction": "Make this section more compelling",
      "related_pages": [
        {"title": "...", "url": "...", "suggested_anchor_text": "..."}
      ]
    }

    Returns:
    {
      "suggestion": "<p>Edited HTML with internal links woven in…</p>",
      "link_opportunities": [
        {"url": "/target-page/", "anchor_text": "...", "inserted": true}
      ]
    }
    """
    site = get_object_or_404(Site, id=site_id, user=request.user)
    page = get_object_or_404(Page, id=page_id, site=site)

    widget_content = (request.data.get('widget_content') or '').strip()
    edit_instruction = (request.data.get('edit_instruction') or '').strip()
    related_pages = request.data.get('related_pages') or []

    if not widget_content:
        return Response(
            {'error': 'widget_content is required'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not edit_instruction:
        return Response(
            {'error': 'edit_instruction is required'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Validate related_pages structure
    validated_links = []
    for rp in related_pages:
        if not isinstance(rp, dict):
            continue
        url = (rp.get('url') or '').strip()
        anchor = (rp.get('suggested_anchor_text') or rp.get('title') or '').strip()
        title = (rp.get('title') or '').strip()
        if url and anchor:
            validated_links.append({
                'title': title,
                'url': url,
                'suggested_anchor_text': anchor,
            })

    # Build AI prompt
    link_context = ''
    if validated_links:
        link_lines = []
        for lnk in validated_links:
            link_lines.append(
                f"  - \"{lnk['suggested_anchor_text']}\" → {lnk['url']} (page: {lnk['title']})"
            )
        link_context = (
            "\n\nInternal Link Opportunities — naturally weave in links to these related pages "
            "where contextually appropriate. Use the suggested anchor text. Each link should appear as: "
            '<a href="{url}">{anchor_text}</a>. Do NOT force links where they don\'t fit naturally.\n'
            + '\n'.join(link_lines)
        )

    system_prompt = (
        "You are a professional SEO content editor. You edit website content widgets "
        "to improve clarity, engagement, and SEO value while maintaining the original voice and intent. "
        "Return ONLY the edited HTML — no explanation, no markdown fences."
    )

    user_prompt = (
        f"Page: {page.title}\nURL: {page.url}\n\n"
        f"Edit instruction: {edit_instruction}\n\n"
        f"Current widget content:\n{widget_content}"
        f"{link_context}"
    )

    # Call Claude API
    suggestion = _call_claude(system_prompt, user_prompt)

    if suggestion is None:
        return Response(
            {'error': 'AI generation failed. Check API key configuration.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    # Determine which links were actually inserted
    link_opportunities = []
    for lnk in validated_links:
        inserted = lnk['url'] in suggestion
        link_opportunities.append({
            'url': lnk['url'],
            'anchor_text': lnk['suggested_anchor_text'],
            'title': lnk['title'],
            'inserted': inserted,
        })

    return Response({
        'suggestion': suggestion,
        'link_opportunities': link_opportunities,
    })


def _call_claude(system_prompt: str, user_prompt: str) -> str | None:
    """Call Claude API for content generation. Returns generated text or None on failure."""
    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY not configured")
        return None

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return message.content[0].text
    except Exception:
        logger.exception("Claude API call failed")
        return None
