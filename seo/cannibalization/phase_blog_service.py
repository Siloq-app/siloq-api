"""
Phase: Blog vs Service Page Conflict Detection

Detects two distinct patterns:

1. BLOG_SERVICE_OVERLAP
   A blog post targets the same primary keyword as a service/product page.
   This is NOT high-severity cannibalization — it is a supportive conflict.
   Blog posts should reinforce the service hub, not compete with it.

   Severity:  MEDIUM  (blogs are far less damaging than two service pages)
   Badge:     CONFIRMED  — if GSC shows both pages ranking for the same query
              POTENTIAL  — if only structural (slug token) overlap detected
   Bucket:    BLOG_OVERLAP

   Resolution options (chosen based on blog word count):
   - MERGE_INTO_SERVICE   if blog word_count < 300 (thin content)
   - REWRITE_AS_SPOKE     default — pivot blog to informational angle + CTA to service page
   - ADD_INTERNAL_LINKS   when blog content is strong and worth preserving as-is

2. BLOG_CONSOLIDATION
   Three or more blog posts targeting similar keywords (Jaccard ≥ 0.4).
   Rather than one strong pillar, there are multiple thin/fragmented posts.

   Severity:  MEDIUM
   Badge:     POTENTIAL
   Bucket:    BLOG_OVERLAP
   Action:    REWRITE_AS_SPOKE (consolidate into one comprehensive pillar)

Approval queue risk badge: "Content Change" (blue) — NOT destructive.

CoCo Events NYC example:
  /blog/corporate-event-planning-tips/  →  BLOG_SERVICE_OVERLAP with
  /services/corporate-events/
  Resolution: REWRITE_AS_SPOKE — "How to Plan a Corporate Event" blog links
  prominently to the Corporate Events service page.
"""
from typing import List, Dict, Optional
from collections import defaultdict

from .models import PageClassification
from .phase1_ingest import get_intent_type
from .utils import normalize_full_url
from .constants import (
    SLUG_STOP_WORDS,
    THIN_BLOG_WORD_COUNT,
    BLOG_SERVICE_MIN_TOKEN_OVERLAP,
    BLOG_CONSOLIDATION_MIN_COUNT,
    BLOG_CONSOLIDATION_JACCARD_THRESHOLD,
    MIN_IMPRESSIONS_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_phase_blog_service(
    classifications: List[PageClassification],
    gsc_data: Optional[List[Dict]] = None,
) -> List[Dict]:
    """
    Detect blog vs service page conflicts.

    Args:
        classifications: All PageClassification objects from Phase 1.
        gsc_data:        Optional GSC aggregate rows
                         (keys: query, page, clicks, impressions, position).
                         When provided, overlaps that appear in GSC together
                         are upgraded from POTENTIAL → CONFIRMED.

    Returns:
        List of conflict dicts compatible with the Phase 6 clustering input.
    """
    issues: List[Dict] = []

    # Partition pages by intent type
    blog_pages: List[PageClassification] = []
    service_pages: List[PageClassification] = []

    for pc in classifications:
        intent = get_intent_type(pc.classified_type)
        if intent == 'informational':
            blog_pages.append(pc)
        elif intent == 'transactional':
            service_pages.append(pc)

    if not blog_pages:
        return issues

    # Build GSC co-ranking lookup: frozenset({url_a, url_b}) → query list
    gsc_co_ranking = _build_gsc_co_ranking(gsc_data) if gsc_data else {}

    # --- Detection 1: BLOG_SERVICE_OVERLAP ---
    if service_pages:
        overlap_issues = _detect_blog_service_overlap(
            blog_pages, service_pages, gsc_co_ranking
        )
        issues.extend(overlap_issues)

    # --- Detection 2: BLOG_CONSOLIDATION ---
    consolidation_issues = _detect_blog_consolidation(blog_pages)
    issues.extend(consolidation_issues)

    return issues


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_gsc_co_ranking(gsc_data: List[Dict]) -> Dict:
    """
    Build a lookup of page-pairs that co-rank in GSC.

    Returns:
        Dict mapping frozenset({normalized_url_a, normalized_url_b}) →
        list of queries where both pages have impressions >= MIN_IMPRESSIONS_THRESHOLD.
    """
    # query → set of normalized URLs with meaningful impressions
    query_to_urls: Dict[str, set] = defaultdict(set)

    for row in gsc_data:
        impressions = int(row.get('impressions', 0))
        if impressions < MIN_IMPRESSIONS_THRESHOLD:
            continue
        query = row.get('query', '').strip().lower()
        page_url = row.get('page', '').strip()
        if not query or not page_url:
            continue
        normalized = normalize_full_url(page_url)
        query_to_urls[query].add(normalized)

    # Build pair lookup
    co_ranking: Dict[frozenset, List[str]] = defaultdict(list)
    for query, url_set in query_to_urls.items():
        url_list = sorted(url_set)
        for i in range(len(url_list)):
            for j in range(i + 1, len(url_list)):
                pair = frozenset({url_list[i], url_list[j]})
                co_ranking[pair].append(query)

    return co_ranking


def _get_significant_tokens(page: PageClassification) -> set:
    """Return slug tokens after stripping stop words."""
    tokens = set(page.slug_tokens_json) if page.slug_tokens_json else set()
    return tokens - SLUG_STOP_WORDS


def _token_overlap(page_a: PageClassification, page_b: PageClassification) -> int:
    """Number of shared significant tokens between two pages."""
    return len(_get_significant_tokens(page_a) & _get_significant_tokens(page_b))


def _jaccard_similarity(page_a: PageClassification, page_b: PageClassification) -> float:
    """Jaccard similarity of slug token sets (stop words removed)."""
    tokens_a = _get_significant_tokens(page_a)
    tokens_b = _get_significant_tokens(page_b)
    if not tokens_a and not tokens_b:
        return 0.0
    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    return intersection / union if union > 0 else 0.0


def _choose_action_code(blog_page: PageClassification) -> str:
    """
    Choose the best action code for a blog/service overlap.

    Rules (from spec):
    - Thin blog (< 300 words): MERGE_INTO_SERVICE
    - Default: REWRITE_AS_SPOKE (pivot blog to informational angle)
    """
    if blog_page.is_thin_content:
        return 'MERGE_INTO_SERVICE'
    return 'REWRITE_AS_SPOKE'


def _build_resolution_detail(
    blog_page: PageClassification,
    service_page: PageClassification,
    action_code: str,
    gsc_queries: Optional[List[str]] = None,
) -> str:
    """
    Build a human-readable resolution recommendation for the approval queue.
    """
    blog_url = blog_page.url
    service_url = service_page.url
    blog_title = blog_page.title or blog_page.slug_last
    service_title = service_page.title or service_page.slug_last
    query_hint = f' (shared query: "{gsc_queries[0]}")' if gsc_queries else ''

    if action_code == 'MERGE_INTO_SERVICE':
        return (
            f'Blog post "{blog_title}" ({blog_url}) is thin '
            f'({blog_page.word_count} words) and targets a keyword owned by '
            f'"{service_title}" ({service_url}){query_hint}. '
            f'Migrate any unique sentences into the service page, then add a '
            f'301 redirect from {blog_url} → {service_url}. '
            f'Risk: Content Change (blue) — not destructive; content is preserved.'
        )

    if action_code == 'REWRITE_AS_SPOKE':
        return (
            f'Blog post "{blog_title}" ({blog_url}) targets the same keyword as '
            f'service page "{service_title}" ({service_url}){query_hint}. '
            f'Rewrite the blog with an informational angle (e.g. "How to…", "What is…") '
            f'and add a prominent CTA linking to {service_url}. '
            f'Alternative: if blog content is strong enough, simply ADD_INTERNAL_LINKS '
            f'rather than rewriting. '
            f'Risk: Content Change (blue) — blog URL stays live.'
        )

    return (
        f'Blog post "{blog_title}" overlaps with service page "{service_title}". '
        f'Add internal links from the blog to the service page.'
    )


def _detect_blog_service_overlap(
    blog_pages: List[PageClassification],
    service_pages: List[PageClassification],
    gsc_co_ranking: Dict,
) -> List[Dict]:
    """
    For each blog post that shares significant slug tokens with a service page,
    generate a BLOG_SERVICE_OVERLAP conflict.

    Badge escalation:
    - POTENTIAL  — structural overlap only
    - CONFIRMED  — both pages co-rank in GSC for the same query
    """
    issues: List[Dict] = []
    seen_pairs: set = set()  # Avoid duplicate pair detection

    for blog in blog_pages:
        for service in service_pages:
            pair_key = (min(blog.page_id, service.page_id), max(blog.page_id, service.page_id))
            if pair_key in seen_pairs:
                continue

            overlap = _token_overlap(blog, service)
            if overlap < BLOG_SERVICE_MIN_TOKEN_OVERLAP:
                continue

            seen_pairs.add(pair_key)

            # GSC co-ranking check
            gsc_pair_key = frozenset({blog.normalized_url, service.normalized_url})
            gsc_queries = gsc_co_ranking.get(gsc_pair_key)
            badge = 'CONFIRMED' if gsc_queries else 'POTENTIAL'

            action_code = _choose_action_code(blog)
            resolution = _build_resolution_detail(blog, service, action_code, gsc_queries)

            # Severity is always MEDIUM for blog/service conflicts — they are
            # supportive relationships, not destructive cannibalization.
            severity = 'MEDIUM'

            issue: Dict = {
                'conflict_type': 'BLOG_SERVICE_OVERLAP',
                'bucket': 'BLOG_OVERLAP',
                'badge': badge,
                'severity': severity,
                'action_code': action_code,
                'pages': [blog, service],
                'metadata': {
                    'blog_url': blog.url,
                    'blog_title': blog.title,
                    'blog_word_count': blog.word_count,
                    'blog_is_thin': blog.is_thin_content,
                    'service_url': service.url,
                    'service_title': service.title,
                    'service_type': service.classified_type,
                    'token_overlap_count': overlap,
                    'shared_tokens': sorted(
                        _get_significant_tokens(blog) & _get_significant_tokens(service)
                    ),
                    'gsc_confirmed': bool(gsc_queries),
                    'gsc_queries': gsc_queries or [],
                },
                'recommendation': resolution,
                'risk_badge': 'Content Change',
                'risk_badge_color': 'blue',
            }

            issues.append(issue)

    return issues


def _detect_blog_consolidation(blog_pages: List[PageClassification]) -> List[Dict]:
    """
    Detect groups of 3+ blog posts targeting similar keywords.

    Algorithm:
    1. Build token sets for each blog post.
    2. Greedy grouping: add a blog to an existing group if its Jaccard similarity
       to the group's representative (first member) exceeds the threshold.
    3. Groups with >= BLOG_CONSOLIDATION_MIN_COUNT members become issues.
    """
    issues: List[Dict] = []

    if len(blog_pages) < BLOG_CONSOLIDATION_MIN_COUNT:
        return issues

    # Greedy grouping by slug token Jaccard similarity
    groups: List[List[PageClassification]] = []

    for blog in blog_pages:
        if not _get_significant_tokens(blog):
            continue  # Skip pages with no tokens

        placed = False
        for group in groups:
            rep = group[0]
            sim = _jaccard_similarity(blog, rep)
            if sim >= BLOG_CONSOLIDATION_JACCARD_THRESHOLD:
                group.append(blog)
                placed = True
                break

        if not placed:
            groups.append([blog])

    # Only flag groups with enough members
    for group in groups:
        if len(group) < BLOG_CONSOLIDATION_MIN_COUNT:
            continue

        # Collect all shared tokens across the group
        all_tokens: set = set()
        for pc in group:
            all_tokens |= _get_significant_tokens(pc)

        # Intersection: tokens shared by ALL members
        shared_tokens: set = _get_significant_tokens(group[0])
        for pc in group[1:]:
            shared_tokens &= _get_significant_tokens(pc)

        page_list = ', '.join(
            f'"{pc.title or pc.slug_last}" ({pc.url})' for pc in group[:5]
        )
        if len(group) > 5:
            page_list += f' … and {len(group) - 5} more'

        recommendation = (
            f'{len(group)} blog posts target similar keywords '
            f'(shared tokens: {sorted(shared_tokens) if shared_tokens else sorted(all_tokens)[:5]}). '
            f'Consolidate into one comprehensive pillar post, then 301-redirect '
            f'the thinner posts to the pillar. Pages: {page_list}. '
            f'Risk: Content Change (blue) — not destructive; content is merged upward.'
        )

        issue: Dict = {
            'conflict_type': 'BLOG_CONSOLIDATION',
            'bucket': 'BLOG_OVERLAP',
            'badge': 'POTENTIAL',
            'severity': 'MEDIUM',
            'action_code': 'REWRITE_AS_SPOKE',
            'pages': group,
            'metadata': {
                'blog_count': len(group),
                'shared_tokens': sorted(shared_tokens),
                'all_tokens': sorted(all_tokens),
                'page_urls': [pc.url for pc in group],
            },
            'recommendation': recommendation,
            'risk_badge': 'Content Change',
            'risk_badge_color': 'blue',
        }

        issues.append(issue)

    return issues
