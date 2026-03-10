"""
Tests for the AI Content Engine app.
"""
from django.test import TestCase
from unittest.mock import patch, MagicMock

from ai.models import SystemPrompt, GeneratedPlan
from ai.validators import validate_response, ValidationError
from ai.context import build_context_payload


class SystemPromptModelTest(TestCase):
    def test_create_prompt(self):
        prompt = SystemPrompt.objects.create(
            prompt_key='merge_plan',
            prompt_text='Test prompt',
            version=1,
            is_active=True,
        )
        self.assertEqual(str(prompt), 'merge_plan v1')
        self.assertTrue(prompt.is_active)


class ValidationTest(TestCase):
    def test_merge_plan_valid(self):
        data = {
            'hub_url': '/test',
            'new_title': 'Test',
            'h2_structure': [{'h2': 'a'}, {'h2': 'b'}, {'h2': 'c'}],
            'content_actions': [{'type': 'keep'}],
            'redirects': [{'from': '/old', 'to': '/new'}],
            'projected_impact': {'current_best_position': 4},
        }
        validate_response('merge_plan', data)  # Should not raise

    def test_merge_plan_missing_field(self):
        with self.assertRaises(ValidationError):
            validate_response('merge_plan', {'hub_url': '/test'})

    def test_merge_plan_too_few_h2s(self):
        data = {
            'hub_url': '/test',
            'new_title': 'Test',
            'h2_structure': [{'h2': 'a'}, {'h2': 'b'}],
            'content_actions': [{}],
            'redirects': [{}],
            'projected_impact': {},
        }
        with self.assertRaises(ValidationError):
            validate_response('merge_plan', data)

    def test_spoke_rewrite_valid(self):
        data = {
            'hub': {'url': '/hub', 'keyword': 'test'},
            'spokes': [{'url': '/spoke1', 'action': 'rewrite_as_spoke'}],
        }
        validate_response('spoke_rewrite', data)

    def test_spoke_rewrite_missing_hub(self):
        with self.assertRaises(ValidationError):
            validate_response('spoke_rewrite', {'spokes': []})

    def test_spoke_rewrite_empty_spokes(self):
        with self.assertRaises(ValidationError):
            validate_response('spoke_rewrite', {'hub': {'url': '/hub'}, 'spokes': []})


class ContextPayloadTest(TestCase):
    def test_build_payload(self):
        # Mock cluster and site
        cluster = MagicMock()
        cluster.gsc_query = 'custom kitchen cabinets'
        cluster.cluster_key = 'test'

        site = MagicMock()
        site.url = 'https://example.com'
        site.business_type = 'local_service'
        site.pages.count.return_value = 50

        pages = [
            {
                'url': '/page1', 'title': 'Page 1', 'clicks': 100,
                'impressions': 1000, 'avg_position': 4.0, 'ctr': 10.0,
                'position_trend': [4, 5, 3, 4], 'related_queries': [],
                'h1': 'Page 1', 'meta_description': '', 'focus_keyword': '',
                'word_count': 1000, 'internal_links_in': 5,
                'internal_links_out': 2, 'schema_type': '',
            },
        ]

        payload = build_context_payload('merge_plan', cluster, site, pages)
        self.assertEqual(payload['action'], 'merge_plan')
        self.assertEqual(payload['conflict']['query'], 'custom kitchen cabinets')
        self.assertEqual(len(payload['conflict']['pages']), 1)
        self.assertEqual(payload['conflict']['pages'][0]['click_share_pct'], 100.0)
