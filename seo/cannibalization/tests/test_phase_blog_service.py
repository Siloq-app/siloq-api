"""
Tests for phase_blog_service.py — Blog vs Service Page conflict detection.

Test scenarios are based on CoCo Events NYC:
  - A service business (event planning) that also publishes blog posts
    targeting some of the same service keywords.
  - Example: /blog/corporate-event-planning-tips/ vs /services/corporate-events/

Key invariants verified:
  1. BLOG_SERVICE_OVERLAP is MEDIUM severity, never HIGH or SEVERE
  2. Thin blog (< 300 words) → action_code is MERGE_INTO_SERVICE
  3. Normal blog (≥ 300 words) → action_code is REWRITE_AS_SPOKE
  4. No keyword overlap → no conflict raised
  5. GSC co-ranking → badge upgrades from POTENTIAL to CONFIRMED
  6. 3+ similar blogs → BLOG_CONSOLIDATION detected
  7. < 3 similar blogs → no BLOG_CONSOLIDATION raised
  8. Blog consolidation action_code is always REWRITE_AS_SPOKE
  9. Risk badge is always "Content Change" (blue) — not destructive
"""
import pytest
from unittest.mock import MagicMock
from ..phase_blog_service import (
    run_phase_blog_service,
    _detect_blog_service_overlap,
    _detect_blog_consolidation,
    _choose_action_code,
    _build_gsc_co_ranking,
    _token_overlap,
)
from ..phase1_ingest import get_intent_type
from ..utils import normalize_full_url


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_page(
    page_id: int,
    url: str,
    classified_type: str,
    slug_tokens=None,
    word_count: int = 500,
    title: str = '',
):
    """Create a minimal PageClassification mock."""
    pc = MagicMock()
    pc.page_id = page_id
    pc.url = url
    pc.normalized_url = normalize_full_url(url)
    pc.title = title or url.rstrip('/').split('/')[-1]
    pc.classified_type = classified_type
    pc.slug_tokens_json = slug_tokens or []
    pc.word_count = word_count
    pc.is_thin_content = word_count > 0 and word_count < 300
    pc.is_critically_thin = word_count > 0 and word_count < 100
    pc.slug_last = url.rstrip('/').split('/')[-1]
    return pc


def _make_gsc_row(query: str, page_url: str, impressions: int = 100) -> dict:
    return {
        'query': query,
        'page': page_url,
        'clicks': 5,
        'impressions': impressions,
        'position': 10.0,
    }


# ---------------------------------------------------------------------------
# CoCo Events NYC test fixtures
# ---------------------------------------------------------------------------

COCO_BLOG_CORPORATE = _make_page(
    101, 'https://cocoevents.com/blog/corporate-event-planning-tips/', 'blog',
    ['corporate', 'event', 'planning', 'tips'], 650, 'Corporate Event Planning Tips'
)
COCO_SERVICE_CORPORATE = _make_page(
    201, 'https://cocoevents.com/services/corporate-events/', 'service_spoke',
    ['corporate', 'events'], 900, 'Corporate Events Service'
)
COCO_BLOG_WEDDING = _make_page(
    102, 'https://cocoevents.com/blog/wedding-planning-guide/', 'blog',
    ['wedding', 'planning', 'guide'], 720, 'Wedding Planning Guide'
)
COCO_SERVICE_WEDDING = _make_page(
    202, 'https://cocoevents.com/services/wedding-events/', 'service_spoke',
    ['wedding', 'events'], 850, 'Wedding Events Service'
)
COCO_BLOG_THIN = _make_page(
    103, 'https://cocoevents.com/blog/party-venue-ideas/', 'blog',
    ['party', 'venue', 'ideas'], 180, 'Party Venue Ideas'
)
COCO_SERVICE_PARTY = _make_page(
    203, 'https://cocoevents.com/services/party-planning/', 'service_spoke',
    ['party', 'planning'], 800, 'Party Planning Service'
)
COCO_BLOG_TIPS_1 = _make_page(
    110, 'https://cocoevents.com/blog/event-planning-tips/', 'blog',
    ['event', 'planning', 'tips'], 400
)
COCO_BLOG_TIPS_2 = _make_page(
    111, 'https://cocoevents.com/blog/event-planning-ideas/', 'blog',
    ['event', 'planning', 'ideas'], 350
)
COCO_BLOG_TIPS_3 = _make_page(
    112, 'https://cocoevents.com/blog/event-planning-checklist/', 'blog',
    ['event', 'planning', 'checklist'], 300
)
COCO_BLOG_UNRELATED = _make_page(
    115, 'https://cocoevents.com/blog/new-york-skyline/', 'blog',
    ['new', 'york', 'skyline'], 600
)


# ---------------------------------------------------------------------------
# Tests: get_intent_type
# ---------------------------------------------------------------------------

class TestGetIntentType:
    def test_blog_is_informational(self):
        assert get_intent_type('blog') == 'informational'

    def test_service_hub_is_transactional(self):
        assert get_intent_type('service_hub') == 'transactional'

    def test_service_spoke_is_transactional(self):
        assert get_intent_type('service_spoke') == 'transactional'

    def test_product_is_transactional(self):
        assert get_intent_type('product') == 'transactional'

    def test_category_woo_is_transactional(self):
        assert get_intent_type('category_woo') == 'transactional'

    def test_homepage_is_other(self):
        assert get_intent_type('homepage') == 'other'

    def test_location_is_other(self):
        assert get_intent_type('location') == 'other'

    def test_wp_post_type_post_overrides_to_informational(self):
        assert get_intent_type('uncategorized', wp_post_type='post') == 'informational'

    def test_wp_post_type_page_uses_classified_type(self):
        assert get_intent_type('service_hub', wp_post_type='page') == 'transactional'

    def test_portfolio_is_informational(self):
        assert get_intent_type('portfolio') == 'informational'


# ---------------------------------------------------------------------------
# Tests: _choose_action_code
# ---------------------------------------------------------------------------

class TestChooseActionCode:
    def test_thin_blog_gets_merge(self):
        thin = _make_page(1, 'https://x.com/blog/t/', 'blog', word_count=150)
        assert _choose_action_code(thin) == 'MERGE_INTO_SERVICE'

    def test_normal_blog_gets_rewrite_as_spoke(self):
        normal = _make_page(2, 'https://x.com/blog/n/', 'blog', word_count=600)
        assert _choose_action_code(normal) == 'REWRITE_AS_SPOKE'

    def test_exactly_300_words_is_not_thin(self):
        boundary = _make_page(3, 'https://x.com/blog/b/', 'blog', word_count=300)
        assert _choose_action_code(boundary) == 'REWRITE_AS_SPOKE'

    def test_299_words_is_thin(self):
        thin = _make_page(4, 'https://x.com/blog/t/', 'blog', word_count=299)
        assert _choose_action_code(thin) == 'MERGE_INTO_SERVICE'


# ---------------------------------------------------------------------------
# Tests: BLOG_SERVICE_OVERLAP
# ---------------------------------------------------------------------------

class TestBlogServiceOverlap:
    def test_coco_corporate_blog_vs_service_detected(self):
        """Core CoCo Events scenario: corporate blog conflicts with corporate service page."""
        issues = _detect_blog_service_overlap(
            [COCO_BLOG_CORPORATE], [COCO_SERVICE_CORPORATE], {}
        )
        assert len(issues) == 1
        issue = issues[0]
        assert issue['conflict_type'] == 'BLOG_SERVICE_OVERLAP'
        assert issue['severity'] == 'MEDIUM'
        assert issue['badge'] == 'POTENTIAL'
        assert issue['bucket'] == 'BLOG_OVERLAP'
        assert issue['action_code'] == 'REWRITE_AS_SPOKE'

    def test_severity_is_always_medium_not_high(self):
        """CRITICAL: blog vs service MUST be MEDIUM, never HIGH or SEVERE."""
        issues = _detect_blog_service_overlap(
            [COCO_BLOG_CORPORATE, COCO_BLOG_WEDDING],
            [COCO_SERVICE_CORPORATE, COCO_SERVICE_WEDDING],
            {}
        )
        for issue in issues:
            assert issue['severity'] == 'MEDIUM', (
                f"Blog/service conflict must be MEDIUM, got {issue['severity']}"
            )

    def test_thin_blog_gets_merge_action(self):
        issues = _detect_blog_service_overlap([COCO_BLOG_THIN], [COCO_SERVICE_PARTY], {})
        assert len(issues) == 1
        assert issues[0]['action_code'] == 'MERGE_INTO_SERVICE'
        assert issues[0]['metadata']['blog_is_thin'] is True

    def test_no_overlap_no_conflict(self):
        issues = _detect_blog_service_overlap([COCO_BLOG_UNRELATED], [COCO_SERVICE_CORPORATE], {})
        assert len(issues) == 0

    def test_gsc_co_ranking_upgrades_to_confirmed(self):
        pair = frozenset({COCO_BLOG_CORPORATE.normalized_url, COCO_SERVICE_CORPORATE.normalized_url})
        gsc_map = {pair: ['corporate event planning nyc']}
        issues = _detect_blog_service_overlap([COCO_BLOG_CORPORATE], [COCO_SERVICE_CORPORATE], gsc_map)
        assert len(issues) == 1
        assert issues[0]['badge'] == 'CONFIRMED'
        assert 'corporate event planning nyc' in issues[0]['metadata']['gsc_queries']

    def test_duplicate_pairs_deduplicated(self):
        issues = _detect_blog_service_overlap(
            [COCO_BLOG_CORPORATE, COCO_BLOG_CORPORATE], [COCO_SERVICE_CORPORATE], {}
        )
        assert len(issues) == 1  # Same page_id pair deduped

    def test_risk_badge_is_content_change_blue(self):
        issues = _detect_blog_service_overlap([COCO_BLOG_CORPORATE], [COCO_SERVICE_CORPORATE], {})
        assert len(issues) == 1
        assert issues[0]['risk_badge'] == 'Content Change'
        assert issues[0]['risk_badge_color'] == 'blue'

    def test_both_pages_in_conflict(self):
        issues = _detect_blog_service_overlap([COCO_BLOG_CORPORATE], [COCO_SERVICE_CORPORATE], {})
        page_ids = {p.page_id for p in issues[0]['pages']}
        assert COCO_BLOG_CORPORATE.page_id in page_ids
        assert COCO_SERVICE_CORPORATE.page_id in page_ids

    def test_shared_tokens_in_metadata(self):
        issues = _detect_blog_service_overlap([COCO_BLOG_CORPORATE], [COCO_SERVICE_CORPORATE], {})
        shared = issues[0]['metadata']['shared_tokens']
        assert len(shared) >= 1  # At least 'corporate' or 'event' shared


# ---------------------------------------------------------------------------
# Tests: BLOG_CONSOLIDATION
# ---------------------------------------------------------------------------

class TestBlogConsolidation:
    def test_three_similar_blogs_triggers_consolidation(self):
        issues = _detect_blog_consolidation([COCO_BLOG_TIPS_1, COCO_BLOG_TIPS_2, COCO_BLOG_TIPS_3])
        assert len(issues) == 1
        issue = issues[0]
        assert issue['conflict_type'] == 'BLOG_CONSOLIDATION'
        assert issue['severity'] == 'MEDIUM'
        assert issue['badge'] == 'POTENTIAL'
        assert issue['action_code'] == 'REWRITE_AS_SPOKE'
        assert issue['bucket'] == 'BLOG_OVERLAP'
        assert issue['metadata']['blog_count'] >= 3

    def test_two_similar_blogs_no_consolidation(self):
        issues = _detect_blog_consolidation([COCO_BLOG_TIPS_1, COCO_BLOG_TIPS_2])
        assert len(issues) == 0

    def test_consolidation_risk_badge_is_content_change(self):
        issues = _detect_blog_consolidation([COCO_BLOG_TIPS_1, COCO_BLOG_TIPS_2, COCO_BLOG_TIPS_3])
        assert issues[0]['risk_badge'] == 'Content Change'

    def test_unrelated_blogs_not_grouped(self):
        issues = _detect_blog_consolidation([
            COCO_BLOG_CORPORATE, COCO_BLOG_WEDDING, COCO_BLOG_UNRELATED
        ])
        assert len(issues) == 0  # Tokens are too different

    def test_consolidation_recommendation_mentions_pillar(self):
        issues = _detect_blog_consolidation([COCO_BLOG_TIPS_1, COCO_BLOG_TIPS_2, COCO_BLOG_TIPS_3])
        rec = issues[0]['recommendation'].lower()
        assert 'pillar' in rec or 'consolidat' in rec


# ---------------------------------------------------------------------------
# Tests: run_phase_blog_service (integration)
# ---------------------------------------------------------------------------

class TestRunPhaseBlogService:
    def test_coco_events_full_scenario(self):
        all_pages = [
            COCO_BLOG_CORPORATE, COCO_BLOG_WEDDING, COCO_BLOG_THIN,
            COCO_SERVICE_CORPORATE, COCO_SERVICE_WEDDING, COCO_SERVICE_PARTY,
        ]
        issues = run_phase_blog_service(all_pages)
        overlap_issues = [i for i in issues if i['conflict_type'] == 'BLOG_SERVICE_OVERLAP']
        assert len(overlap_issues) >= 2  # At minimum corporate + party blog overlap

    def test_no_blog_pages_returns_empty(self):
        issues = run_phase_blog_service([COCO_SERVICE_CORPORATE, COCO_SERVICE_WEDDING])
        assert issues == []

    def test_no_service_pages_only_consolidation(self):
        issues = run_phase_blog_service([COCO_BLOG_TIPS_1, COCO_BLOG_TIPS_2, COCO_BLOG_TIPS_3])
        overlap = [i for i in issues if i['conflict_type'] == 'BLOG_SERVICE_OVERLAP']
        consolidation = [i for i in issues if i['conflict_type'] == 'BLOG_CONSOLIDATION']
        assert len(overlap) == 0
        assert len(consolidation) == 1

    def test_gsc_data_upgrades_to_confirmed(self):
        gsc_data = [
            _make_gsc_row('corporate event planning nyc', COCO_BLOG_CORPORATE.normalized_url),
            _make_gsc_row('corporate event planning nyc', COCO_SERVICE_CORPORATE.normalized_url),
        ]
        issues = run_phase_blog_service([COCO_BLOG_CORPORATE, COCO_SERVICE_CORPORATE], gsc_data=gsc_data)
        overlap = [i for i in issues if i['conflict_type'] == 'BLOG_SERVICE_OVERLAP']
        confirmed = [i for i in overlap if i['badge'] == 'CONFIRMED']
        assert len(confirmed) >= 1

    def test_all_severities_are_medium_or_lower(self):
        """No blog/service conflict should ever be HIGH or SEVERE."""
        all_pages = [
            COCO_BLOG_CORPORATE, COCO_BLOG_WEDDING, COCO_BLOG_THIN,
            COCO_SERVICE_CORPORATE, COCO_SERVICE_WEDDING, COCO_SERVICE_PARTY,
            COCO_BLOG_TIPS_1, COCO_BLOG_TIPS_2, COCO_BLOG_TIPS_3,
        ]
        issues = run_phase_blog_service(all_pages)
        for issue in issues:
            assert issue['severity'] in ('MEDIUM', 'LOW'), (
                f"Blog/service conflict should never exceed MEDIUM severity, "
                f"got {issue['severity']} for {issue['conflict_type']}"
            )


# ---------------------------------------------------------------------------
# Tests: _build_gsc_co_ranking
# ---------------------------------------------------------------------------

class TestBuildGscCoRanking:
    def test_co_ranking_pair_detected(self):
        gsc_data = [
            _make_gsc_row('event planning', 'https://example.com/blog/a/', 150),
            _make_gsc_row('event planning', 'https://example.com/services/events/', 200),
        ]
        co = _build_gsc_co_ranking(gsc_data)
        # normalize_full_url strips the scheme; keys in co use normalized form
        pair = frozenset({
            normalize_full_url('https://example.com/blog/a/'),
            normalize_full_url('https://example.com/services/events/'),
        })
        assert pair in co
        assert 'event planning' in co[pair]

    def test_low_impression_rows_excluded(self):
        gsc_data = [
            _make_gsc_row('obscure', 'https://x.com/a/', impressions=3),
            _make_gsc_row('obscure', 'https://x.com/b/', impressions=3),
        ]
        assert len(_build_gsc_co_ranking(gsc_data)) == 0

    def test_single_page_query_no_pair(self):
        gsc_data = [_make_gsc_row('solo', 'https://x.com/blog/only/', 100)]
        assert len(_build_gsc_co_ranking(gsc_data)) == 0
