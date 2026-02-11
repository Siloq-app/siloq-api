"""
Serializers for Page and SEOData models.
"""
from rest_framework import serializers
from .models import Page, SEOData
from sites.serializers import SiteSerializer


class SEODataSerializer(serializers.ModelSerializer):
    """Serializer for SEOData model."""
    
    class Meta:
        model = SEOData
        fields = (
            'id', 'meta_title', 'meta_description', 'meta_keywords',
            'h1_count', 'h1_text', 'h2_count', 'h2_texts', 'h3_count', 'h3_texts',
            'internal_links_count', 'external_links_count', 'internal_links', 'external_links',
            'images_count', 'images_without_alt', 'images',
            'word_count', 'reading_time_minutes',
            'seo_score', 'issues', 'recommendations',
            'has_canonical', 'canonical_url', 'has_schema', 'schema_type',
            'scanned_at', 'scan_version'
        )
        read_only_fields = ('id', 'scanned_at')


class PageSerializer(serializers.ModelSerializer):
    """Serializer for Page model."""
    site = SiteSerializer(read_only=True)
    seo_data = SEODataSerializer(read_only=True)

    class Meta:
        model = Page
        fields = (
            'id', 'site', 'wp_post_id', 'url', 'title', 'slug',
            'content', 'excerpt', 'status', 'published_at', 'modified_at',
            'parent_id', 'menu_order', 'yoast_title', 'yoast_description',
            'featured_image', 'siloq_page_id', 'is_money_page', 'last_synced_at',
            'created_at', 'updated_at', 'seo_data'
        )
        read_only_fields = ('id', 'created_at', 'updated_at', 'last_synced_at')


class PageListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for page lists."""
    seo_score = serializers.SerializerMethodField()
    issue_count = serializers.SerializerMethodField()

    class Meta:
        model = Page
        fields = (
            'id', 'url', 'title', 'status', 'published_at',
            'last_synced_at', 'seo_score', 'issue_count', 'is_money_page', 'is_noindex'
        )

    def get_seo_score(self, obj):
        """Get SEO score from related SEOData (OneToOneField)."""
        try:
            return obj.seo_data.seo_score
        except SEOData.DoesNotExist:
            return None

    def get_issue_count(self, obj):
        """Get issue count from related SEOData (OneToOneField)."""
        try:
            seo_data = obj.seo_data
            return len(seo_data.issues) if seo_data.issues else 0
        except SEOData.DoesNotExist:
            return 0


class PageSyncSerializer(serializers.Serializer):
    """Serializer for WordPress page sync requests."""
    wp_post_id = serializers.IntegerField()
    url = serializers.URLField()
    title = serializers.CharField(max_length=500)
    content = serializers.CharField(required=False, allow_blank=True)
    excerpt = serializers.CharField(required=False, allow_blank=True)
    status = serializers.CharField(default='publish')
    published_at = serializers.DateTimeField(required=False, allow_null=True)
    modified_at = serializers.DateTimeField(required=False, allow_null=True)
    slug = serializers.CharField(max_length=500, required=False, allow_blank=True)
    parent_id = serializers.IntegerField(required=False, allow_null=True)
    menu_order = serializers.IntegerField(default=0)
    yoast_title = serializers.CharField(required=False, allow_blank=True)
    yoast_description = serializers.CharField(required=False, allow_blank=True)
    featured_image = serializers.URLField(required=False, allow_blank=True)
    is_noindex = serializers.BooleanField(required=False, default=False)
    is_homepage = serializers.BooleanField(required=False, default=False)

    def to_internal_value(self, data):
        """Flatten nested meta fields if present (yoast_title, yoast_description, featured_image, is_noindex)."""
        if isinstance(data, dict) and 'meta' in data and isinstance(data['meta'], dict):
            meta = data['meta']
            data = dict(data)
            if 'yoast_title' not in data and meta.get('yoast_title') is not None:
                data['yoast_title'] = meta['yoast_title']
            if 'yoast_description' not in data and meta.get('yoast_description') is not None:
                data['yoast_description'] = meta['yoast_description']
            if 'featured_image' not in data and meta.get('featured_image') is not None:
                data['featured_image'] = meta['featured_image']
            # Check for noindex in meta (Yoast sends this as _yoast_wpseo_meta-robots-noindex)
            if 'is_noindex' not in data:
                noindex_val = meta.get('_yoast_wpseo_meta-robots-noindex') or meta.get('is_noindex')
                if noindex_val:
                    data['is_noindex'] = noindex_val in [True, '1', 1, 'true', 'yes']
        return super().to_internal_value(data)
