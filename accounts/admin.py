from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, TeamInvite, SiteAccess, UserNotificationPreferences


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('email', 'username', 'is_staff', 'is_active', 'created_at')
    list_filter = ('is_staff', 'is_active', 'created_at')
    search_fields = ('email', 'username')
    ordering = ('-created_at',)


@admin.register(TeamInvite)
class TeamInviteAdmin(admin.ModelAdmin):
    list_display = ('email', 'role', 'invited_by', 'site', 'status', 'created_at', 'expires_at')
    list_filter = ('status', 'created_at', 'expires_at')
    search_fields = ('email', 'invited_by__email', 'site__name')
    ordering = ('-created_at',)


@admin.register(SiteAccess)
class SiteAccessAdmin(admin.ModelAdmin):
    list_display = ('user', 'site', 'role', 'granted_by', 'created_at')
    list_filter = ('role', 'created_at')
    search_fields = ('user__email', 'site__name', 'granted_by__email')


@admin.register(UserNotificationPreferences)
class UserNotificationPreferencesAdmin(admin.ModelAdmin):
    list_display = ('user', 'updated_at')
    search_fields = ('user__email',)
    raw_id_fields = ('user',)  