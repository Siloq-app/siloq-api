"""
Serializers for WordPress integration endpoints.
"""
from rest_framework import serializers
from sites.models import Site
from seo.models import Page, SEOData
from .models import Scan


class APIKeyVerifySerializer(serializers.Serializer):
    """Serializer for API key verification."""
    site_id = serializers.IntegerField(read_only=True)
    site_name = serializers.CharField(read_only=True)
    site_url = serializers.URLField(read_only=True)
    valid = serializers.BooleanField(read_only=True)


class PageSyncSerializer(serializers.ModelSerializer):
    """Serializer for syncing pages from WordPress."""
    
    class Meta:
        model = Page
        fields = (
            'wp_post_id', 'url', 'title', 'content', 'excerpt',
            'status', 'published_at', 'modified_at', 'slug',
            'parent_id', 'menu_order', 'yoast_title', 'yoast_description',
            'featured_image'
        )


class SEODataSyncSerializer(serializers.ModelSerializer):
    """Serializer for syncing SEO data from WordPress scanner."""
    
    class Meta:
        model = SEOData
        fields = (
            'meta_title', 'meta_description', 'meta_keywords',
            'h1_count', 'h1_text', 'h2_count', 'h2_texts', 'h3_count', 'h3_texts',
            'internal_links_count', 'external_links_count', 'internal_links', 'external_links',
            'images_count', 'images_without_alt', 'images',
            'word_count', 'reading_time_minutes',
            'seo_score', 'issues', 'recommendations',
            'has_canonical', 'canonical_url', 'has_schema', 'schema_type'
        )


class ScanCreateSerializer(serializers.Serializer):
    """Serializer for creating a scan."""
    url = serializers.URLField()
    scan_type = serializers.ChoiceField(choices=['full', 'quick'], default='full')


class ScanSerializer(serializers.ModelSerializer):
    """Serializer for Scan model."""

    class Meta:
        model = Scan
        fields = (
            'id', 'url', 'scan_type', 'status', 'score',
            'pages_analyzed', 'scan_duration_seconds', 'results',
            'error_message', 'started_at', 'completed_at'
        )
        read_only_fields = (
            'id', 'status', 'score', 'pages_analyzed',
            'scan_duration_seconds', 'results', 'error_message',
            'started_at', 'completed_at'
        )
