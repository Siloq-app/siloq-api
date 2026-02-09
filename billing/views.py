"""
Billing API views.
Handles AI settings, usage logs, and cost estimation.
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404

from sites.models import Site
from .models import ProjectAISettings, AIUsageLog, BillingEvent
from .serializers import (
    ProjectAISettingsSerializer, ProjectAISettingsUpdateSerializer,
    AIUsageLogSerializer, BillingEventSerializer, CostEstimateSerializer
)
from .preflight import check_ai_preflight, AIPreflightGuard


class BillingViewSet(viewsets.ViewSet):
    """
    Billing endpoints for a site.
    
    GET /sites/{site_id}/billing/settings/ - Get AI settings
    PUT /sites/{site_id}/billing/settings/ - Update AI settings
    GET /sites/{site_id}/billing/usage/ - Get usage logs
    POST /sites/{site_id}/billing/estimate/ - Estimate cost before execution
    """
    permission_classes = [IsAuthenticated]
    
    def _get_site(self, request, site_id):
        """Get site and verify ownership."""
        return get_object_or_404(Site, id=site_id, user=request.user)
    
    @action(detail=False, methods=['get', 'put'], url_path='settings')
    def settings(self, request, site_id=None):
        """Get or update AI settings for a site."""
        site = self._get_site(request, site_id)
        
        # Get or create settings
        ai_settings, created = ProjectAISettings.objects.get_or_create(
            site=site,
            defaults={'mode': 'trial'}
        )
        
        # Initialize trial if new
        if created and not ai_settings.trial_start_date:
            ai_settings.start_trial()
        
        if request.method == 'GET':
            serializer = ProjectAISettingsSerializer(ai_settings)
            return Response(serializer.data)
        
        # PUT - update settings
        serializer = ProjectAISettingsUpdateSerializer(ai_settings, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(ProjectAISettingsSerializer(ai_settings).data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'], url_path='usage')
    def usage(self, request, site_id=None):
        """Get AI usage logs for a site."""
        site = self._get_site(request, site_id)
        
        logs = AIUsageLog.objects.filter(site=site).order_by('-created_at')[:100]
        serializer = AIUsageLogSerializer(logs, many=True)
        
        # Calculate totals
        total_tokens = sum(log.input_tokens + log.output_tokens for log in logs)
        total_cost = sum(log.total_charge_usd for log in logs)
        trial_cost = sum(log.provider_cost_usd for log in logs if log.is_trial)
        
        return Response({
            'logs': serializer.data,
            'summary': {
                'total_tokens': total_tokens,
                'total_cost_usd': float(total_cost),
                'trial_cost_absorbed_usd': float(trial_cost),
                'log_count': len(logs)
            }
        })
    
    @action(detail=False, methods=['post'], url_path='estimate')
    def estimate(self, request, site_id=None):
        """
        Estimate cost before AI execution.
        
        POST /sites/{site_id}/billing/estimate/
        Body: { "estimated_tokens": 2000, "is_bulk": false }
        
        Returns cost estimate or error if not allowed.
        """
        site = self._get_site(request, site_id)
        
        estimated_tokens = request.data.get('estimated_tokens', 1000)
        is_bulk = request.data.get('is_bulk', False)
        
        result = check_ai_preflight(site, estimated_tokens, is_bulk)
        
        response_data = {
            'allowed': result.allowed,
            'error_code': result.error_code,
            'error_message': result.error_message,
            'warning': result.warning,
            'estimated_input_tokens': result.estimated_input_tokens,
            'estimated_output_tokens': result.estimated_output_tokens,
            'estimated_provider_cost_usd': str(result.estimated_provider_cost_usd),
            'estimated_siloq_fee_usd': str(result.estimated_siloq_fee_usd),
            'estimated_total_cost_usd': str(result.estimated_total_cost_usd),
        }
        
        if not result.allowed:
            return Response(response_data, status=status.HTTP_402_PAYMENT_REQUIRED)
        
        return Response(response_data)
    
    @action(detail=False, methods=['post'], url_path='increment-trial')
    def increment_trial(self, request, site_id=None):
        """
        Increment trial page counter after successful generation.
        Called internally after content generation.
        """
        site = self._get_site(request, site_id)
        
        ai_settings = get_object_or_404(ProjectAISettings, site=site)
        
        if ai_settings.mode != 'trial':
            return Response({'error': 'Not in trial mode'}, status=status.HTTP_400_BAD_REQUEST)
        
        ai_settings.trial_pages_used += 1
        ai_settings.save(update_fields=['trial_pages_used'])
        
        return Response({
            'trial_pages_used': ai_settings.trial_pages_used,
            'trial_pages_remaining': ai_settings.trial_pages_remaining
        })
