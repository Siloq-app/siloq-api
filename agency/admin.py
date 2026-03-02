from django.contrib import admin
from .models import AgencyProfile, AgencyClientSite


@admin.register(AgencyProfile)
class AgencyProfileAdmin(admin.ModelAdmin):
    list_display = ('agency_name', 'agency_slug', 'white_label_tier', 'user', 'created_at')
    list_filter = ('white_label_tier', 'domain_verified')
    search_fields = ('agency_name', 'agency_slug', 'custom_domain', 'user__email')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(AgencyClientSite)
class AgencyClientSiteAdmin(admin.ModelAdmin):
    list_display = ('agency', 'site', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('agency__agency_name', 'site__url')
    readonly_fields = ('created_at',)
