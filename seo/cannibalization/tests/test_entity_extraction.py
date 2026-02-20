"""
Tests for Phase 0.5 entity extraction and Rule 2D brand line variant exemption.

Test data is modelled on:
- Crystallized Couture (e-commerce, cheer/dance apparel, product siblings)
- CoCo Events NYC (service business — no product_name entities)

Run: pytest seo/cannibalization/tests/test_entity_extraction.py -v
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from seo.cannibalization.models import PageClassification
from seo.cannibalization.phase0_entity_extraction import (
    _parse_entity_response,
    extract_entities_for_pages,
    run_phase0_entity_extraction,
)
from seo.cannibalization.phase2_safe_filters import (
    _is_brand_line_variant,
    audit_brand_line_urls,
)


# =============================================================================
# Helpers
# =============================================================================

def _make_pc(**kwargs) -> PageClassification:
    """Create an unsaved PageClassification with sensible defaults."""
    defaults = dict(
        page_id=1,
        url='https://example.com/page/',
        title='Page',
        normalized_url='https://example.com/page/',
        normalized_path='/page/',
        classified_type='product',
        is_legacy_variant=False,
        folder_root='',
        parent_path='',
        slug_last='page',
        depth=1,
        geo_node='',
        service_keyword='',
        slug_tokens_json=[],
        word_count=0,
        is_thin_content=False,
        is_critically_thin=False,
        entities=[],
    )
    defaults.update(kwargs)
    pc = PageClassification(**defaults)
    pc.id = kwargs.get('id', defaults['page_id'])
    return pc


# =============================================================================
# Rule 2D — _is_brand_line_variant()
# =============================================================================

class TestIsBrandLineVariant:
    """Unit tests for Rule 2D brand line variant detection."""

    def test_chasse_performance_vip_vs_all_star_exempt(self):
        """Two Chasse Performance products with different names → exempt."""
        page_a = _make_pc(
            page_id=1,
            url='https://crystallizedcouture.com/chasse-performance-vip-jacket/',
            entities=[
                {'text': 'Chasse Performance', 'type': 'brand_line', 'confidence': 0.95},
                {'text': 'VIP Jacket', 'type': 'product_name', 'confidence': 0.90},
                {'text': 'Jacket', 'type': 'product_category', 'confidence': 0.85},
            ],
        )
        page_b = _make_pc(
            page_id=2,
            url='https://crystallizedcouture.com/chasse-performance-all-star-jacket/',
            entities=[
                {'text': 'Chasse Performance', 'type': 'brand_line', 'confidence': 0.95},
                {'text': 'All Star Jacket', 'type': 'product_name', 'confidence': 0.90},
                {'text': 'Jacket', 'type': 'product_category', 'confidence': 0.85},
            ],
        )
        assert _is_brand_line_variant(page_a, page_b) is True

    def test_shared_product_name_not_exempt(self):
        """Same brand_line AND same product_name → NOT exempt (could be duplicate)."""
        page_a = _make_pc(
            page_id=1,
            entities=[
                {'text': 'Chasse Performance', 'type': 'brand_line', 'confidence': 0.95},
                {'text': 'VIP Jacket', 'type': 'product_name', 'confidence': 0.90},
            ],
        )
        page_b = _make_pc(
            page_id=2,
            entities=[
                {'text': 'Chasse Performance', 'type': 'brand_line', 'confidence': 0.95},
                {'text': 'VIP Jacket', 'type': 'product_name', 'confidence': 0.90},
            ],
        )
        assert _is_brand_line_variant(page_a, page_b) is False

    def test_no_shared_brand_line_not_exempt(self):
        """Different brand lines → NOT exempt."""
        page_a = _make_pc(
            page_id=1,
            entities=[
                {'text': 'Chasse Performance', 'type': 'brand_line', 'confidence': 0.95},
                {'text': 'VIP Jacket', 'type': 'product_name', 'confidence': 0.90},
            ],
        )
        page_b = _make_pc(
            page_id=2,
            entities=[
                {'text': 'Nike Dri-FIT', 'type': 'brand_line', 'confidence': 0.95},
                {'text': 'All Star Jacket', 'type': 'product_name', 'confidence': 0.90},
            ],
        )
        assert _is_brand_line_variant(page_a, page_b) is False

    def test_service_pages_no_brand_line_not_exempt(self):
        """CoCo Events service pages — no brand_line → NOT exempt (true conflict check)."""
        page_c = _make_pc(
            page_id=3,
            entities=[{'text': 'kitchen remodeling', 'type': 'service_type', 'confidence': 0.9}],
        )
        page_d = _make_pc(
            page_id=4,
            entities=[{'text': 'kitchen remodeling', 'type': 'service_type', 'confidence': 0.9}],
        )
        assert _is_brand_line_variant(page_c, page_d) is False

    def test_empty_entities_not_exempt(self):
        """No entities → cannot determine brand line variant → NOT exempt."""
        page_a = _make_pc(page_id=1, entities=[])
        page_b = _make_pc(page_id=2, entities=[])
        assert _is_brand_line_variant(page_a, page_b) is False

    def test_brand_line_only_no_product_name_not_exempt(self):
        """Shared brand line but one page has no product_name → NOT exempt."""
        page_a = _make_pc(
            page_id=1,
            entities=[
                {'text': 'Chasse Performance', 'type': 'brand_line', 'confidence': 0.95},
            ],
        )
        page_b = _make_pc(
            page_id=2,
            entities=[
                {'text': 'Chasse Performance', 'type': 'brand_line', 'confidence': 0.95},
                {'text': 'All Star Jacket', 'type': 'product_name', 'confidence': 0.90},
            ],
        )
        assert _is_brand_line_variant(page_a, page_b) is False

    def test_case_insensitive_comparison(self):
        """brand_line comparison must be case-insensitive."""
        page_a = _make_pc(
            page_id=1,
            entities=[
                {'text': 'CHASSE PERFORMANCE', 'type': 'brand_line', 'confidence': 0.95},
                {'text': 'VIP Jacket', 'type': 'product_name', 'confidence': 0.90},
            ],
        )
        page_b = _make_pc(
            page_id=2,
            entities=[
                {'text': 'chasse performance', 'type': 'brand_line', 'confidence': 0.95},
                {'text': 'All Star Jacket', 'type': 'product_name', 'confidence': 0.90},
            ],
        )
        assert _is_brand_line_variant(page_a, page_b) is True


# =============================================================================
# audit_brand_line_urls()
# =============================================================================

class TestAuditBrandLineUrls:
    """Tests for the Crystallized Couture URL audit function."""

    def test_flat_url_group_generates_recommendation(self):
        """2+ flat pages with same brand_line → BRAND_LINE_URL_RESTRUCTURE recommendation."""
        page_a = _make_pc(
            id=1, page_id=1,
            url='https://crystallizedcouture.com/chasse-performance-vip-jacket/',
            normalized_path='/chasse-performance-vip-jacket/',
            slug_last='chasse-performance-vip-jacket',
            depth=1,
            entities=[
                {'text': 'Chasse Performance', 'type': 'brand_line', 'confidence': 0.95},
                {'text': 'VIP Jacket', 'type': 'product_name', 'confidence': 0.90},
            ],
        )
        page_b = _make_pc(
            id=2, page_id=2,
            url='https://crystallizedcouture.com/chasse-performance-all-star-jacket/',
            normalized_path='/chasse-performance-all-star-jacket/',
            slug_last='chasse-performance-all-star-jacket',
            depth=1,
            entities=[
                {'text': 'Chasse Performance', 'type': 'brand_line', 'confidence': 0.95},
                {'text': 'All Star Jacket', 'type': 'product_name', 'confidence': 0.90},
            ],
        )
        recs = audit_brand_line_urls([page_a, page_b])
        assert len(recs) == 1
        rec = recs[0]
        assert rec['conflict_type'] == 'BRAND_LINE_URL_RESTRUCTURE'
        assert rec['action_code'] == 'BRAND_LINE_URL_RESTRUCTURE'
        assert rec['hub_url'] == '/chasse-performance/'
        assert rec['conflict_subtype'] == 'structural_warning'
        assert len(rec['spoke_suggestions']) == 2

    def test_nested_url_group_no_recommendation(self):
        """Pages already at depth 2 → no restructure needed."""
        page_a = _make_pc(
            id=1, page_id=1,
            url='https://crystallizedcouture.com/chasse-performance/vip-jacket/',
            normalized_path='/chasse-performance/vip-jacket/',
            slug_last='vip-jacket',
            depth=2,
            entities=[
                {'text': 'Chasse Performance', 'type': 'brand_line', 'confidence': 0.95},
                {'text': 'VIP Jacket', 'type': 'product_name', 'confidence': 0.90},
            ],
        )
        page_b = _make_pc(
            id=2, page_id=2,
            url='https://crystallizedcouture.com/chasse-performance/all-star-jacket/',
            normalized_path='/chasse-performance/all-star-jacket/',
            slug_last='all-star-jacket',
            depth=2,
            entities=[
                {'text': 'Chasse Performance', 'type': 'brand_line', 'confidence': 0.95},
                {'text': 'All Star Jacket', 'type': 'product_name', 'confidence': 0.90},
            ],
        )
        recs = audit_brand_line_urls([page_a, page_b])
        assert recs == []

    def test_single_page_brand_line_no_recommendation(self):
        """Only one page in brand line → no recommendation."""
        page_a = _make_pc(
            id=1, page_id=1,
            url='https://example.com/chasse-performance-vip-jacket/',
            depth=1,
            entities=[
                {'text': 'Chasse Performance', 'type': 'brand_line', 'confidence': 0.95},
                {'text': 'VIP Jacket', 'type': 'product_name', 'confidence': 0.90},
            ],
        )
        recs = audit_brand_line_urls([page_a])
        assert recs == []

    def test_no_entities_no_recommendation(self):
        """Pages with no entities → no recommendation."""
        page_a = _make_pc(id=1, page_id=1, depth=1, entities=[])
        page_b = _make_pc(id=2, page_id=2, depth=1, entities=[])
        recs = audit_brand_line_urls([page_a, page_b])
        assert recs == []


# =============================================================================
# _parse_entity_response()
# =============================================================================

class TestParseEntityResponse:
    """Tests for Claude response parsing."""

    def test_clean_json_array(self):
        raw = json.dumps([
            {
                'url': '/vip-jacket/',
                'entities': [
                    {'text': 'Chasse Performance', 'type': 'brand_line', 'confidence': 0.95},
                ],
            }
        ])
        result = _parse_entity_response(raw)
        assert len(result) == 1
        assert result[0]['url'] == '/vip-jacket/'
        assert result[0]['entities'][0]['type'] == 'brand_line'

    def test_markdown_fenced_json(self):
        raw = (
            "```json\n"
            '[{"url": "/test/", "entities": [{"text": "Nike", "type": "brand", "confidence": 0.9}]}]\n'
            "```"
        )
        result = _parse_entity_response(raw)
        assert len(result) == 1
        assert result[0]['entities'][0]['text'] == 'Nike'

    def test_invalid_json_raises_value_error(self):
        with pytest.raises(ValueError, match='Could not parse'):
            _parse_entity_response('not json at all')

    def test_non_array_raises_value_error(self):
        with pytest.raises(ValueError, match='Expected JSON array'):
            _parse_entity_response('{"pages": []}')

    def test_missing_confidence_defaults_to_1(self):
        raw = json.dumps([
            {'url': '/page/', 'entities': [{'text': 'Nike', 'type': 'brand'}]}
        ])
        result = _parse_entity_response(raw)
        assert result[0]['entities'][0]['confidence'] == 1.0

    def test_empty_array_returns_empty_list(self):
        result = _parse_entity_response('[]')
        assert result == []


# =============================================================================
# run_phase0_entity_extraction() — pipeline integration
# =============================================================================

class TestRunPhase0EntityExtraction:
    """Integration-level tests for the pipeline entry point."""

    def test_no_api_key_skips_gracefully(self, caplog):
        """No ANTHROPIC_API_KEY → skip silently, log warning."""
        classifications = [_make_pc(page_id=1)]
        with patch(
            'seo.cannibalization.phase0_entity_extraction.ANTHROPIC_API_KEY', ''
        ):
            with caplog.at_level('WARNING'):
                run_phase0_entity_extraction(classifications)
        # Should log a warning, not raise
        assert any('ANTHROPIC_API_KEY' in r.message for r in caplog.records)
        # Entities should remain empty
        assert classifications[0].entities == []

    def test_empty_classifications_returns_immediately(self):
        """Empty list → no API call, no error."""
        run_phase0_entity_extraction([])  # Should not raise

    def test_entities_stored_on_classifications(self):
        """Claude response is mapped back to PageClassification.entities."""
        pc = _make_pc(
            page_id=1,
            id=1,
            url='https://example.com/chasse-performance-vip-jacket/',
        )
        mock_response = [
            {
                'url': '/chasse-performance-vip-jacket/',
                'entities': [
                    {'text': 'Chasse Performance', 'type': 'brand_line', 'confidence': 0.95},
                    {'text': 'VIP Jacket', 'type': 'product_name', 'confidence': 0.90},
                ],
            }
        ]
        with patch(
            'seo.cannibalization.phase0_entity_extraction.ANTHROPIC_API_KEY',
            'test-key',
        ):
            with patch(
                'seo.cannibalization.phase0_entity_extraction._call_claude_batch',
                return_value=mock_response,
            ):
                with patch(
                    'seo.cannibalization.models.PageClassification.objects'
                ) as mock_mgr:
                    mock_mgr.bulk_update = MagicMock()
                    run_phase0_entity_extraction([pc])

        assert len(pc.entities) == 2
        assert pc.entities[0]['type'] == 'brand_line'
        assert pc.entities[1]['type'] == 'product_name'

    def test_api_error_logged_not_raised(self, caplog):
        """Claude API error → log error, don't crash the pipeline."""
        pc = _make_pc(page_id=1, id=1, url='https://example.com/page/')
        with patch(
            'seo.cannibalization.phase0_entity_extraction.ANTHROPIC_API_KEY',
            'test-key',
        ):
            with patch(
                'seo.cannibalization.phase0_entity_extraction._call_claude_batch',
                side_effect=RuntimeError('API error'),
            ):
                with caplog.at_level('ERROR'):
                    run_phase0_entity_extraction([pc])

        assert any('entity extraction failed' in r.message.lower() for r in caplog.records)
        # Entities should remain empty — pipeline continues
        assert pc.entities == []


# =============================================================================
# extract_entities_for_pages() — API helper
# =============================================================================

class TestExtractEntitiesForPages:
    """Tests for the API helper function."""

    def test_no_api_key_raises_runtime_error(self):
        with patch(
            'seo.cannibalization.phase0_entity_extraction.ANTHROPIC_API_KEY', ''
        ):
            with pytest.raises(RuntimeError, match='ANTHROPIC_API_KEY'):
                extract_entities_for_pages([{'url': '/test/', 'title': 'Test', 'h1': '', 'meta': ''}])

    def test_empty_pages_returns_empty_list(self):
        result = extract_entities_for_pages([])
        assert result == []

    def test_batch_call_result_returned(self):
        pages = [{'url': '/test/', 'title': 'Test page', 'h1': 'Test', 'meta': ''}]
        expected = [{'url': '/test/', 'entities': [{'text': 'Test', 'type': 'product_name', 'confidence': 0.8}]}]
        with patch(
            'seo.cannibalization.phase0_entity_extraction.ANTHROPIC_API_KEY',
            'test-key',
        ):
            with patch(
                'seo.cannibalization.phase0_entity_extraction._call_claude_batch',
                return_value=expected,
            ):
                result = extract_entities_for_pages(pages)
        assert result == expected
