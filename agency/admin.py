from django.contrib import admin
from .models import AgencyProfile, AgencyClientLink


@admin.register(AgencyProfile)
class AgencyProfileAdmin(admin.ModelAdmin):
    list_display = ('agency_name', 'agency_slug', 'white_label_tier', 'user', 'created_at')
    list_filter = ('white_label_tier', 'domain_verified')
    search_fields = ('agency_name', 'agency_slug', 'custom_domain', 'user__email')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(AgencyClientLink)
class AgencyClientLinkAdmin(admin.ModelAdmin):
    list_display = ('agency', 'client', 'status', 'invite_email', 'invited_at', 'accepted_at')
    list_filter = ('status',)
    search_fields = ('agency__email', 'client__email', 'invite_email')
    readonly_fields = ('invited_at',)
