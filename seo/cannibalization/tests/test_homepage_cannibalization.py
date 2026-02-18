"""
Tests for Homepage Cannibalization Detection

Covers:
- _detect_homepage_cannibalization(): hoarding pattern (homepage is primary)
- _detect_homepage_cannibalization(): split pattern (homepage secondary)
- HOMEPAGE_CANNIBALIZATION conflict type emitted with CONFIRMED badge + DE_OPTIMIZE_HOMEPAGE action
- winner_selection: absolute rule — homepage never wins vs service/product/location pages
- constants: HOMEPAGE_CANNIBALIZATION and DE_OPTIMIZE_HOMEPAGE defined correctly
"""
import pytest
from unittest.mock import MagicMock


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_page(classified_type: str, url: str, normalized_url: str = None):
    """Create a minimal PageClassification-like mock."""
    pc = MagicMock()
    pc.classified_type = classified_type
    pc.url = url
    pc.normalized_url = normalized_url or url
    pc.page_id = hash(url)
    return pc


def _make_row(page_class, url: str, impressions: int, clicks: int, position: float,
              query: str = 'test query'):
    """Build a query-group row dict as produced inside run_phase4."""
    return {
        'query': query,
        'page_url': url,
        'normalized_url': page_class.normalized_url,
        'page_class': page_class,
        'clicks': clicks,
        'impressions': impressions,
        'position': position,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Constants & action code tests
# ──────────────────────────────────────────────────────────────────────────────

class TestHomepageCannibalizationConstants:
    def test_homepage_cannibalization_conflict_type_exists(self):
        from seo.cannibalization.constants import CONFLICT_TYPES
        assert 'HOMEPAGE_CANNIBALIZATION' in CONFLICT_TYPES

    def test_homepage_cannibalization_bucket_is_search_conflict(self):
        from seo.cannibalization.constants import CONFLICT_TYPES
        ct = CONFLICT_TYPES['HOMEPAGE_CANNIBALIZATION']
        assert ct['bucket'] == 'SEARCH_CONFLICT'

    def test_homepage_cannibalization_badge_is_confirmed(self):
        from seo.cannibalization.constants import CONFLICT_TYPES
        ct = CONFLICT_TYPES['HOMEPAGE_CANNIBALIZATION']
        assert ct['badge'] == 'CONFIRMED'

    def test_homepage_cannibalization_action_code_is_de_optimize(self):
        from seo.cannibalization.constants import CONFLICT_TYPES
        ct = CONFLICT_TYPES['HOMEPAGE_CANNIBALIZATION']
        assert ct['action_code'] == 'DE_OPTIMIZE_HOMEPAGE'

    def test_de_optimize_homepage_action_code_exists(self):
        from seo.cannibalization.constants import ACTION_CODES
        assert 'DE_OPTIMIZE_HOMEPAGE' in ACTION_CODES

    def test_de_optimize_homepage_not_requires_user_input(self):
        from seo.cannibalization.constants import ACTION_CODES
        assert ACTION_CODES['DE_OPTIMIZE_HOMEPAGE']['requires_user_input'] is False

    def test_de_optimize_homepage_mentions_absolute_rule(self):
        from seo.cannibalization.constants import ACTION_CODES
        desc = ACTION_CODES['DE_OPTIMIZE_HOMEPAGE']['description']
        assert 'NEVER' in desc or 'never' in desc or 'absolute' in desc.lower()


# ──────────────────────────────────────────────────────────────────────────────
# _detect_homepage_cannibalization() unit tests
# ──────────────────────────────────────────────────────────────────────────────

class TestDetectHomepageCannibalization:
    """Tests for the private _detect_homepage_cannibalization function."""

    def _run(self, query_groups):
        from seo.cannibalization.phase4_gsc_validate import _detect_homepage_cannibalization
        return _detect_homepage_cannibalization(query_groups, {})

    def test_hoarding_pattern_detected(self):
        """Homepage is primary (highest impressions) — hoarding pattern."""
        hp = _make_page('homepage', 'https://example.com/', 'example.com')
        svc = _make_page('service', 'https://example.com/services/roofing/', 'example.com/services/roofing')

        query_groups = {
            'roofing company': [
                _make_row(hp, 'https://example.com/', 600, 10, 1.5, 'roofing company'),
                _make_row(svc, 'https://example.com/services/roofing/', 400, 8, 3.2, 'roofing company'),
            ]
        }

        issues = self._run(query_groups)
        assert len(issues) == 1
        issue = issues[0]
        assert issue['conflict_type'] == 'HOMEPAGE_CANNIBALIZATION'
        assert issue['badge'] == 'CONFIRMED'
        assert issue['bucket'] == 'SEARCH_CONFLICT'
        assert len(issue['metadata']['hoarded_queries']) == 1
        assert issue['metadata']['hoarded_queries'][0]['query'] == 'roofing company'

    def test_split_pattern_detected(self):
        """Homepage is secondary — splitting impressions with service page."""
        hp = _make_page('homepage', 'https://example.com/', 'example.com')
        svc = _make_page('service', 'https://example.com/services/roofing/', 'example.com/services/roofing')

        query_groups = {
            'roofing repair': [
                _make_row(svc, 'https://example.com/services/roofing/', 700, 15, 2.0, 'roofing repair'),
                _make_row(hp, 'https://example.com/', 300, 5, 4.5, 'roofing repair'),
            ]
        }

        issues = self._run(query_groups)
        assert len(issues) == 1
        issue = issues[0]
        assert issue['conflict_type'] == 'HOMEPAGE_CANNIBALIZATION'
        assert len(issue['metadata']['split_queries']) == 1
        assert issue['metadata']['split_queries'][0]['query'] == 'roofing repair'

    def test_no_issue_when_homepage_absent(self):
        """No issue when homepage does not appear in the query group."""
        svc1 = _make_page('service', 'https://example.com/services/a/', 'example.com/services/a')
        svc2 = _make_page('service', 'https://example.com/services/b/', 'example.com/services/b')

        query_groups = {
            'roofing': [
                _make_row(svc1, 'https://example.com/services/a/', 500, 10, 2.0, 'roofing'),
                _make_row(svc2, 'https://example.com/services/b/', 300, 5, 4.0, 'roofing'),
            ]
        }

        issues = self._run(query_groups)
        assert len(issues) == 0

    def test_no_issue_when_no_service_page(self):
        """No issue when homepage competes only with blog — not service/product."""
        hp = _make_page('homepage', 'https://example.com/', 'example.com')
        blog = _make_page('blog', 'https://example.com/blog/post/', 'example.com/blog/post')

        query_groups = {
            'some topic': [
                _make_row(hp, 'https://example.com/', 500, 10, 2.0, 'some topic'),
                _make_row(blog, 'https://example.com/blog/post/', 300, 5, 4.0, 'some topic'),
            ]
        }

        issues = self._run(query_groups)
        assert len(issues) == 0

    def test_multiple_queries_consolidated_per_pair(self):
        """Multiple queries for same hp/service pair → single consolidated issue."""
        hp = _make_page('homepage', 'https://example.com/', 'example.com')
        svc = _make_page('service', 'https://example.com/services/roofing/', 'example.com/services/roofing')

        query_groups = {
            'roofing company': [
                _make_row(hp, 'https://example.com/', 600, 1, 2.0, 'roofing company'),
                _make_row(svc, 'https://example.com/services/roofing/', 400, 1, 3.0, 'roofing company'),
            ],
            'roof repair': [
                _make_row(hp, 'https://example.com/', 550, 1, 2.0, 'roof repair'),
                _make_row(svc, 'https://example.com/services/roofing/', 450, 1, 3.0, 'roof repair'),
            ],
            'roofing contractor': [
                _make_row(hp, 'https://example.com/', 700, 1, 2.0, 'roofing contractor'),
                _make_row(svc, 'https://example.com/services/roofing/', 300, 1, 3.0, 'roofing contractor'),
            ],
        }

        issues = self._run(query_groups)
        # All 3 queries belong to the same pair — should produce 1 issue
        assert len(issues) == 1
        meta = issues[0]['metadata']
        total_queries = len(meta['hoarded_queries']) + len(meta['split_queries'])
        assert total_queries == 3

    def test_recommendation_mentions_keyword_and_service_url(self):
        """Recommendation string must name the keyword and the correct service page URL."""
        hp = _make_page('homepage', 'https://example.com/', 'example.com')
        svc = _make_page('service', 'https://example.com/services/plumbing/', 'example.com/services/plumbing')

        query_groups = {
            'plumber near me': [
                _make_row(hp, 'https://example.com/', 600, 10, 1.5, 'plumber near me'),
                _make_row(svc, 'https://example.com/services/plumbing/', 400, 5, 3.0, 'plumber near me'),
            ]
        }

        issues = self._run(query_groups)
        assert issues
        rec = issues[0]['metadata']['recommendation']
        assert 'plumber near me' in rec
        assert 'https://example.com/services/plumbing/' in rec

    def test_severity_severe_when_both_patterns(self):
        """SEVERE when same pair has both hoarding AND split queries."""
        hp = _make_page('homepage', 'https://example.com/', 'example.com')
        svc = _make_page('service', 'https://example.com/services/siding/', 'example.com/services/siding')

        query_groups = {
            'siding company': [   # hoarding: homepage > service
                _make_row(hp, 'https://example.com/', 700, 1, 2.0, 'siding company'),
                _make_row(svc, 'https://example.com/services/siding/', 300, 1, 3.0, 'siding company'),
            ],
            'vinyl siding': [     # split: service > homepage
                _make_row(svc, 'https://example.com/services/siding/', 600, 1, 2.0, 'vinyl siding'),
                _make_row(hp, 'https://example.com/', 400, 1, 3.0, 'vinyl siding'),
            ],
        }

        issues = self._run(query_groups)
        assert issues
        assert issues[0]['severity'] == 'SEVERE'

    def test_noise_filtered_out(self):
        """Homepage rows with <5% share and 0 clicks are ignored."""
        hp = _make_page('homepage', 'https://example.com/', 'example.com')
        svc = _make_page('service', 'https://example.com/services/gutters/', 'example.com/services/gutters')

        # Homepage has only 2% share and 0 clicks — should be noise-filtered
        query_groups = {
            'gutter cleaning': [
                _make_row(svc, 'https://example.com/services/gutters/', 980, 20, 2.0, 'gutter cleaning'),
                _make_row(hp, 'https://example.com/', 20, 0, 15.0, 'gutter cleaning'),
            ]
        }

        issues = self._run(query_groups)
        assert len(issues) == 0

    def test_product_page_type_detected(self):
        """product page type is recognised as a non-homepage service page."""
        hp = _make_page('homepage', 'https://example.com/', 'example.com')
        prod = _make_page('product', 'https://example.com/products/widget/', 'example.com/products/widget')

        query_groups = {
            'buy widget': [
                _make_row(hp, 'https://example.com/', 600, 5, 1.8, 'buy widget'),
                _make_row(prod, 'https://example.com/products/widget/', 400, 10, 3.5, 'buy widget'),
            ]
        }

        issues = self._run(query_groups)
        assert len(issues) == 1
        assert issues[0]['conflict_type'] == 'HOMEPAGE_CANNIBALIZATION'

    def test_location_page_type_detected(self):
        """location page type is also covered by the absolute rule."""
        hp = _make_page('homepage', 'https://example.com/', 'example.com')
        loc = _make_page('location', 'https://example.com/locations/chicago/', 'example.com/locations/chicago')

        query_groups = {
            'plumber chicago': [
                _make_row(hp, 'https://example.com/', 600, 8, 2.0, 'plumber chicago'),
                _make_row(loc, 'https://example.com/locations/chicago/', 400, 6, 3.8, 'plumber chicago'),
            ]
        }

        issues = self._run(query_groups)
        assert len(issues) == 1
        assert issues[0]['conflict_type'] == 'HOMEPAGE_CANNIBALIZATION'

    def test_category_page_type_detected(self):
        """category page type is covered by the absolute rule."""
        hp = _make_page('homepage', 'https://example.com/', 'example.com')
        cat = _make_page('category', 'https://example.com/shop/roofing/', 'example.com/shop/roofing')

        query_groups = {
            'roofing supplies': [
                _make_row(hp, 'https://example.com/', 600, 8, 2.0, 'roofing supplies'),
                _make_row(cat, 'https://example.com/shop/roofing/', 400, 6, 3.8, 'roofing supplies'),
            ]
        }

        issues = self._run(query_groups)
        assert len(issues) == 1
        assert issues[0]['conflict_type'] == 'HOMEPAGE_CANNIBALIZATION'


# ──────────────────────────────────────────────────────────────────────────────
# winner_selection: Homepage absolute rule
# ──────────────────────────────────────────────────────────────────────────────

class TestHomepageAbsoluteRule:
    """
    Verify that the homepage never wins against service/product/location pages
    even when it has far more clicks/impressions.
    """

    def _select(self, pages_data):
        from seo.cannibalization.winner_selection import select_recommended_winner
        return select_recommended_winner(pages_data)

    def test_homepage_never_wins_vs_service(self):
        """Homepage with massive clicks loses to a service page."""
        pages = [
            {
                'page_type': 'homepage',
                'gsc_clicks': 99999,
                'gsc_impressions': 999999,
                'gsc_avg_position': 1.0,
                'page_url': 'https://example.com/',
            },
            {
                'page_type': 'service',
                'gsc_clicks': 1,
                'gsc_impressions': 10,
                'gsc_avg_position': 8.0,
                'page_url': 'https://example.com/services/roofing/',
            },
        ]
        result = self._select(pages)
        assert result['homepage_override'] is True
        winner_page = pages[result['winner_index']]
        assert winner_page['page_type'] == 'service'

    def test_homepage_never_wins_vs_product(self):
        """Homepage with massive clicks loses to a product page."""
        pages = [
            {'page_type': 'homepage', 'gsc_clicks': 5000, 'gsc_impressions': 50000,
             'gsc_avg_position': 1.0, 'page_url': 'https://example.com/'},
            {'page_type': 'product', 'gsc_clicks': 0, 'gsc_impressions': 0,
             'gsc_avg_position': 999, 'page_url': 'https://example.com/products/widget/'},
        ]
        result = self._select(pages)
        assert result['homepage_override'] is True
        assert pages[result['winner_index']]['page_type'] == 'product'

    def test_homepage_never_wins_vs_location(self):
        """Homepage loses to a location page."""
        pages = [
            {'page_type': 'homepage', 'gsc_clicks': 500, 'gsc_impressions': 5000,
             'gsc_avg_position': 2.0, 'page_url': 'https://example.com/'},
            {'page_type': 'location', 'gsc_clicks': 1, 'gsc_impressions': 5,
             'gsc_avg_position': 9.0, 'page_url': 'https://example.com/locations/chicago/'},
        ]
        result = self._select(pages)
        assert result['homepage_override'] is True
        assert pages[result['winner_index']]['page_type'] == 'location'

    def test_homepage_override_false_when_no_service_page(self):
        """homepage_override flag is False when only competing with blog."""
        pages = [
            {'page_type': 'homepage', 'gsc_clicks': 500, 'gsc_impressions': 5000,
             'gsc_avg_position': 2.0, 'page_url': 'https://example.com/'},
            {'page_type': 'blog', 'gsc_clicks': 5, 'gsc_impressions': 50,
             'gsc_avg_position': 8.0, 'page_url': 'https://example.com/blog/post/'},
        ]
        result = self._select(pages)
        # No override needed when competing with blog only
        assert result['homepage_override'] is False

    def test_highest_scoring_service_wins_not_just_any_service(self):
        """When multiple service pages exist, the *highest-scoring* one wins."""
        pages = [
            {'page_type': 'homepage', 'gsc_clicks': 1000, 'gsc_impressions': 10000,
             'gsc_avg_position': 1.0, 'page_url': 'https://example.com/'},
            {'page_type': 'service', 'gsc_clicks': 50, 'gsc_impressions': 500,
             'gsc_avg_position': 4.0, 'page_url': 'https://example.com/services/a/'},
            {'page_type': 'service', 'gsc_clicks': 200, 'gsc_impressions': 2000,
             'gsc_avg_position': 2.5, 'page_url': 'https://example.com/services/b/'},
        ]
        result = self._select(pages)
        assert result['homepage_override'] is True
        winner = pages[result['winner_index']]
        # services/b/ has more clicks and impressions — should win
        assert winner['page_url'] == 'https://example.com/services/b/'
