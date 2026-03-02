"""
Keyword Assignment Registry — the single source of truth for which keyword
belongs to which page on a site.

Core invariant: one keyword per site (enforced by DB unique constraint).
"""
import logging
import re
from typing import Optional
from urllib.parse import urlparse

from django.db import IntegrityError, transaction
from django.utils import timezone

from seo.models import KeywordAssignment, Page

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_primary_keyword(page: Page) -> Optional[str]:
    """
    Extract the best primary keyword for a page, trying in order:
      1. AIOSEO / Yoast focus keyword (stored in page meta if synced)
      2. H1 / page title
      3. URL slug
    Returns a normalised lowercase keyword string, or None.
    """

    # 1. Focus keyword from SEO plugin meta
    #    We check seo_data.meta_keywords first (AIOSEO stores focus kw there).
    try:
        seo = page.seo_data
        if seo and seo.meta_keywords:
            kw = seo.meta_keywords.strip().split(',')[0].strip()
            if kw:
                return kw.lower()
    except Exception:
        pass

    # 2. Page title / H1
    if page.title:
        # Strip common suffixes like " | Site Name", " - Site Name"
        title = re.split(r'\s*[|–—-]\s*', page.title)[0].strip()
        if title and len(title) > 2:
            return title.lower()

    # 3. URL slug
    if page.slug:
        slug_kw = page.slug.replace('-', ' ').strip()
        if slug_kw:
            return slug_kw.lower()

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def bootstrap_keyword_registry(site) -> dict:
    """
    Crawl all published, non-noindex pages for *site* and create
    KeywordAssignment records.

    Returns:
        {
            total_pages: int,
            keywords_assigned: int,
            conflicts_found: int,
            conflict_details: [ {keyword, pages: [{id, title, url}, ...]} ]
        }
    """
    pages = Page.objects.filter(
        site=site,
        status='publish',
        is_noindex=False,
    )

    total_pages = pages.count()
    assigned = 0
    conflicts = []

    # keyword -> list of pages that want it (for conflict detection)
    keyword_pages: dict[str, list] = {}

    for page in pages:
        kw = _extract_primary_keyword(page)
        if not kw:
            continue
        keyword_pages.setdefault(kw, []).append(page)

    for kw, page_list in keyword_pages.items():
        # Pick the first page as the "winner" (could be smarter later)
        winner = page_list[0]

        # Determine page_type heuristic
        if winner.is_homepage:
            pt = 'homepage'
        elif winner.is_money_page:
            pt = 'hub'
        elif winner.parent_silo_id:
            pt = 'spoke'
        elif winner.post_type == 'product':
            pt = 'product'
        elif winner.post_type == 'post':
            pt = 'blog'
        else:
            pt = 'general'

        try:
            KeywordAssignment.objects.update_or_create(
                keyword=kw,
                site=site,
                defaults={
                    'page': winner,
                    'page_type': pt,
                    'silo_id': winner.parent_silo_id,
                    'assignment_source': 'auto_bootstrap',
                    'status': 'active',
                },
            )
            assigned += 1
        except Exception as exc:
            logger.exception("Failed to assign keyword '%s' for site %s: %s", kw, site.id, exc)
            continue

        if len(page_list) > 1:
            conflicts.append({
                'keyword': kw,
                'pages': [
                    {'id': p.id, 'title': p.title, 'url': p.url}
                    for p in page_list
                ],
            })

    if conflicts:
        logger.warning(
            "Bootstrap for site %s found %d pre-existing keyword conflicts",
            site.id, len(conflicts),
        )

    return {
        'total_pages': total_pages,
        'keywords_assigned': assigned,
        'conflicts_found': len(conflicts),
        'conflict_details': conflicts,
    }


def check_keyword_available(site, keyword: str, exclude_page_id: Optional[int] = None) -> bool:
    """
    Return True if *keyword* is not actively assigned to any page on *site*.
    Optionally exclude a page (useful for reassignment checks).
    """
    qs = KeywordAssignment.objects.filter(
        site=site,
        keyword=keyword.lower(),
        status='active',
    )
    if exclude_page_id:
        qs = qs.exclude(page_id=exclude_page_id)
    return not qs.exists()


def get_keyword_owner(site, keyword: str) -> Optional[KeywordAssignment]:
    """Return the active KeywordAssignment for *keyword* on *site*, or None."""
    return KeywordAssignment.objects.filter(
        site=site,
        keyword=keyword.lower(),
        status='active',
    ).select_related('page').first()


def assign_keyword(
    site,
    page,
    keyword: str,
    silo_id: Optional[int] = None,
    page_type: str = 'general',
    source: str = 'manual',
) -> KeywordAssignment:
    """
    Assign *keyword* to *page* on *site*.
    Raises IntegrityError if the keyword is already taken on this site.
    """
    return KeywordAssignment.objects.create(
        site=site,
        page=page,
        keyword=keyword.lower(),
        silo_id=silo_id,
        page_type=page_type,
        assignment_source=source,
        status='active',
    )


@transaction.atomic
def reassign_keyword(site, keyword: str, new_page, reason: str = '') -> KeywordAssignment:
    """
    Move *keyword* from its current owner to *new_page*.

    - Marks the old assignment as 'reassigned'
    - Creates a new active assignment pointing to *new_page*
    - Preserves audit trail via reassigned_from_page / reassigned_at
    """
    kw_lower = keyword.lower()

    old = KeywordAssignment.objects.select_for_update().filter(
        site=site,
        keyword=kw_lower,
        status='active',
    ).first()

    old_page = old.page if old else None

    if old:
        old.status = 'reassigned'
        old.reassigned_at = timezone.now()
        old.save(update_fields=['status', 'reassigned_at', 'updated_at'])

    # Delete the row so the unique constraint is free, then create new
    if old:
        old.delete()

    new_assignment = KeywordAssignment.objects.create(
        site=site,
        page=new_page,
        keyword=kw_lower,
        silo_id=new_page.parent_silo_id,
        page_type='general',
        assignment_source='manual',
        status='active',
        reassigned_from_page=old_page,
        reassigned_at=timezone.now() if old_page else None,
    )

    logger.info(
        "Reassigned keyword '%s' on site %s: page %s → page %s. Reason: %s",
        kw_lower, site.id,
        old_page.id if old_page else 'none',
        new_page.id, reason,
    )

    return new_assignment
