from django.contrib import admin
from .models import (
    Page, SEOData, InternalLink, AnchorTextConflict, LinkIssue, GSCData,
    Conflict, ContentJob, SiloDefinition, SiloKeyword, KeywordAssignment,
    KeywordAssignmentHistory, PageMetadata, CannibalizationConflict,
    ConflictPage, ConflictResolution, RedirectRegistry, PageAnalysis,
    SiteEntityProfile, SlugChangeLog, SiloHealthScore, FreshnessAlert,
    ContentHealthScore, ContentAuditLog, LifecycleQueue, SiteGSCPageData,
    ValidationLog, SiteIntelligence, SiteAudit
)


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ('title', 'site', 'url', 'status', 'last_synced_at', 'created_at')
    list_filter = ('status', 'site', 'created_at')
    search_fields = ('title', 'url', 'site__name')
    readonly_fields = ('created_at', 'updated_at', 'last_synced_at')


@admin.register(SEOData)
class SEODataAdmin(admin.ModelAdmin):
    list_display = ('page', 'seo_score', 'h1_count', 'word_count', 'scanned_at')
    list_filter = ('scanned_at', 'has_schema', 'has_canonical')
    search_fields = ('page__title', 'page__url')
    readonly_fields = ('scanned_at',)


@admin.register(InternalLink)
class InternalLinkAdmin(admin.ModelAdmin):
    list_display = ('source_page', 'anchor_text', 'target_url', 'is_valid', 'created_at')
    list_filter = ('is_valid', 'is_nofollow', 'created_at')
    search_fields = ('anchor_text', 'source_page__title', 'target_url')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(AnchorTextConflict)
class AnchorTextConflictAdmin(admin.ModelAdmin):
    list_display = ('anchor_text', 'occurrence_count', 'severity', 'is_resolved', 'created_at')
    list_filter = ('severity', 'is_resolved', 'created_at')
    search_fields = ('anchor_text',)
    readonly_fields = ('created_at', 'updated_at', 'resolved_at')


@admin.register(LinkIssue)
class LinkIssueAdmin(admin.ModelAdmin):
    list_display = ('issue_type', 'page', 'severity', 'is_resolved', 'created_at')
    list_filter = ('issue_type', 'severity', 'is_resolved', 'created_at')
    search_fields = ('description', 'anchor_text', 'page__title')
    readonly_fields = ('created_at', 'updated_at', 'resolved_at')


@admin.register(GSCData)
class GSCDataAdmin(admin.ModelAdmin):
    list_display = ('query', 'page', 'site', 'impressions', 'clicks', 'position', 'date_start', 'date_end')
    list_filter = ('site', 'device', 'date_start', 'date_end')
    search_fields = ('query', 'page__title', 'site__name')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Conflict)
class ConflictAdmin(admin.ModelAdmin):
    list_display = ('query_string', 'site', 'page1', 'page2', 'status', 'severity_score', 'created_at')
    list_filter = ('status', 'is_dismissed', 'site', 'created_at')
    search_fields = ('query_string', 'page1__title', 'page2__title', 'site__name')
    readonly_fields = ('created_at', 'updated_at', 'resolved_at')


@admin.register(ContentJob)
class ContentJobAdmin(admin.ModelAdmin):
    list_display = ('job_type', 'page', 'status', 'priority', 'topic', 'created_at')
    list_filter = ('job_type', 'status', 'priority', 'created_at')
    search_fields = ('topic', 'recommendation', 'page__title')
    readonly_fields = ('created_at', 'updated_at', 'approved_at', 'completed_at')


@admin.register(SiloDefinition)
class SiloDefinitionAdmin(admin.ModelAdmin):
    list_display = ('name', 'target_page', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('name', 'target_page__title')
    readonly_fields = ('created_at',)


@admin.register(SiloKeyword)
class SiloKeywordAdmin(admin.ModelAdmin):
    list_display = ('keyword', 'silo', 'search_volume')
    list_filter = ('silo',)
    search_fields = ('keyword',)


@admin.register(KeywordAssignment)
class KeywordAssignmentAdmin(admin.ModelAdmin):
    list_display = ('keyword', 'page', 'silo', 'status', 'assigned_at')
    list_filter = ('status', 'silo', 'assigned_at')
    search_fields = ('keyword', 'page__title')
    readonly_fields = ('assigned_at',)


@admin.register(KeywordAssignmentHistory)
class KeywordAssignmentHistoryAdmin(admin.ModelAdmin):
    list_display = ('keyword', 'action', 'old_page', 'new_page', 'created_at')
    list_filter = ('action', 'created_at')
    search_fields = ('keyword', 'old_page__title', 'new_page__title')
    readonly_fields = ('created_at',)


@admin.register(PageMetadata)
class PageMetadataAdmin(admin.ModelAdmin):
    list_display = ('page', 'word_count', 'readability_score', 'last_crawled')
    search_fields = ('page__title', 'page__url')
    readonly_fields = ('last_crawled',)


@admin.register(CannibalizationConflict)
class CannibalizationConflictAdmin(admin.ModelAdmin):
    list_display = ('keyword', 'severity', 'status', 'created_at')
    list_filter = ('severity', 'status', 'created_at')
    search_fields = ('keyword',)
    readonly_fields = ('created_at',)


@admin.register(ConflictPage)
class ConflictPageAdmin(admin.ModelAdmin):
    list_display = ('conflict', 'page', 'impressions', 'clicks', 'position')
    list_filter = ('conflict',)
    search_fields = ('page__title',)


@admin.register(ConflictResolution)
class ConflictResolutionAdmin(admin.ModelAdmin):
    list_display = ('conflict', 'resolution_type', 'resolved_at')
    list_filter = ('resolution_type', 'resolved_at')
    search_fields = ('resolution_type', 'notes')
    readonly_fields = ('resolved_at',)


@admin.register(RedirectRegistry)
class RedirectRegistryAdmin(admin.ModelAdmin):
    list_display = ('source_url', 'target_url', 'redirect_type', 'created_at')
    list_filter = ('redirect_type', 'created_at')
    search_fields = ('source_url', 'target_url')
    readonly_fields = ('created_at',)


@admin.register(PageAnalysis)
class PageAnalysisAdmin(admin.ModelAdmin):
    list_display = ('page', 'score', 'created_at')
    list_filter = ('created_at',)
    search_fields = ['page__title']
    readonly_fields = ('created_at',)


@admin.register(SiteEntityProfile)
class SiteEntityProfileAdmin(admin.ModelAdmin):
    list_display = ('business_name', 'business_type', 'is_service_area_business')
    list_filter = ('business_type', 'is_service_area_business')
    search_fields = ('business_name',)


@admin.register(SlugChangeLog)
class SlugChangeLogAdmin(admin.ModelAdmin):
    list_display = ('old_slug', 'new_slug', 'slug_change_status', 'changed_at')
    list_filter = ('slug_change_status', 'changed_at')
    search_fields = ('old_slug', 'new_slug')
    readonly_fields = ('changed_at', 'updated_at')


@admin.register(SiloHealthScore)
class SiloHealthScoreAdmin(admin.ModelAdmin):
    list_display = ('silo', 'score', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('silo__name',)
    readonly_fields = ('created_at',)


@admin.register(FreshnessAlert)
class FreshnessAlertAdmin(admin.ModelAdmin):
    list_display = ('alert_type', 'page', 'is_resolved', 'created_at')
    list_filter = ('alert_type', 'is_resolved', 'created_at')
    search_fields = ('alert_type', 'page__title')
    readonly_fields = ('created_at',)


@admin.register(ContentHealthScore)
class ContentHealthScoreAdmin(admin.ModelAdmin):
    list_display = ('score', 'created_at')
    list_filter = ('created_at',)
    search_fields = ()
    readonly_fields = ('created_at',)


@admin.register(ContentAuditLog)
class ContentAuditLogAdmin(admin.ModelAdmin):
    list_display = ('action', 'created_by', 'created_at')
    list_filter = ('action', 'created_at')
    search_fields = ('action',)
    readonly_fields = ('created_at',)


@admin.register(LifecycleQueue)
class LifecycleQueueAdmin(admin.ModelAdmin):
    list_display = ('page', 'action', 'status', 'priority', 'created_at')
    list_filter = ('action', 'status', 'created_at')
    search_fields = ('action', 'page__title')
    readonly_fields = ('created_at',)


@admin.register(SiteGSCPageData)
class SiteGSCPageDataAdmin(admin.ModelAdmin):
    list_display = ('url', 'impressions_28d', 'clicks_28d', 'avg_position', 'synced_at')
    list_filter = ('synced_at',)
    search_fields = ('url',)
    readonly_fields = ('synced_at',)


@admin.register(ValidationLog)
class ValidationLogAdmin(admin.ModelAdmin):
    list_display = ('page', 'validation_type', 'created_at')
    list_filter = ('validation_type', 'created_at')
    search_fields = ('validation_type', 'page__title')
    readonly_fields = ('created_at',)


@admin.register(SiteIntelligence)
class SiteIntelligenceAdmin(admin.ModelAdmin):
    list_display = ('business_type', 'primary_goal', 'generated_at')
    list_filter = ('business_type', 'generated_at')
    search_fields = ('primary_goal',)
    readonly_fields = ('generated_at',)


@admin.register(SiteAudit)
class SiteAuditAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'status', 'site_score', 'pages_audited', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('user__email',)
    readonly_fields = ('id', 'created_at')
