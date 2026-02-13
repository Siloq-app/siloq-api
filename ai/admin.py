from django.contrib import admin
from .models import SystemPrompt, GeneratedPlan


@admin.register(SystemPrompt)
class SystemPromptAdmin(admin.ModelAdmin):
    list_display = ('prompt_key', 'version', 'is_active', 'updated_at')
    list_filter = ('is_active',)


@admin.register(GeneratedPlan)
class GeneratedPlanAdmin(admin.ModelAdmin):
    list_display = ('action', 'conflict_query', 'provider', 'model', 'created_at')
    list_filter = ('action', 'provider')
    readonly_fields = ('context_payload', 'ai_response')
