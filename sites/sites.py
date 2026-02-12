"""
Site management views.
Handles CRUD operations for sites and site overview.
"""
import logging

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.db.models import Prefetch
from django.db import IntegrityError

from seo.models import SEOData
from .models import Site
from .serializers import SiteSerializer
from .permissions import IsSiteOwner
from .analysis import detect_cannibalization, analyze_site, calculate_health_score

logger = logging.getLogger(__name__)


class SiteViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing sites.
    
    list: GET /api/v1/sites/ - List all sites for current user
    create: POST /api/v1/sites/ - Create a new site
    retrieve: GET /api/v1/sites/{id}/ - Get site details
    update: PUT /api/v1/sites/{id}/ - Update site
    destroy: DELETE /api/v1/sites/{id}/ - Delete site
    overview: GET /api/v1/sites/{id}/overview/ - Get site overview (health score, stats)
    """
    serializer_class = SiteSerializer
    permission_classes = [IsAuthenticated, IsSiteOwner]

    def get_queryset(self):
        """Return only sites owned by the current user."""
        return Site.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        """Set the user when creating a site."""
        serializer.save(user=self.request.user)

    def create(self, request, *args, **kwargs):
        """Create a site with duplicate URL handling."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            self.perform_create(serializer)
        except IntegrityError:
            return Response(
                {'error': 'A site with this URL already exists for your account'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    @action(detail=True, methods=['get'])
    def overview(self, request, pk=None):
        """
        Get site overview with health score and aggregated stats.

        GET /api/v1/sites/{id}/overview/
        """
        site = self.get_object()

        # Calculate health score (simplified - can be enhanced)
        # Prefetch seo_data to avoid N+1 queries
        pages = site.pages.prefetch_related(
            Prefetch('seo_data', queryset=SEOData.objects.all(), to_attr='prefetched_seo_data')
        )
        total_pages = pages.count()

        # Calculate SEO health score based on issues
        total_issues = 0
        for page in pages:
            seo_data_list = getattr(page, 'prefetched_seo_data', [])
            if seo_data_list and len(seo_data_list) > 0:
                seo_data = seo_data_list[0]
                if seo_data and seo_data.issues:
                    total_issues += len(seo_data.issues)

        # Simple health score calculation (0-100)
        # Lower issues = higher score
        if total_pages > 0:
            avg_issues_per_page = total_issues / total_pages
            health_score = max(0, min(100, 100 - (avg_issues_per_page * 10)))
        else:
            health_score = 0

        return Response({
            'site_id': site.id,
            'site_name': site.name,
            'health_score': round(health_score, 1),
            'total_pages': total_pages,
            'total_issues': total_issues,
            'last_synced_at': site.last_synced_at,
        })

    @action(detail=True, methods=['get', 'patch'])
    def profile(self, request, pk=None):
        """
        Get or update business profile for onboarding wizard.

        GET /api/v1/sites/{id}/profile/ - Get current profile
        PATCH /api/v1/sites/{id}/profile/ - Update profile fields
        """
        site = self.get_object()

        if request.method == 'GET':
            return Response({
                'business_type': site.business_type,
                'primary_services': site.primary_services or [],
                'service_areas': site.service_areas or [],
                'target_audience': site.target_audience or '',
                'business_description': site.business_description or '',
                'onboarding_complete': site.onboarding_complete,
            })

        # PATCH - update profile fields
        allowed_fields = [
            'business_type',
            'primary_services',
            'service_areas',
            'target_audience',
            'business_description',
        ]
        
        for field in allowed_fields:
            if field in request.data:
                setattr(site, field, request.data[field])
        
        # Check if onboarding is complete (has business_type and at least one service)
        if site.business_type and site.primary_services:
            site.onboarding_complete = True
        
        site.save()
        
        return Response({
            'business_type': site.business_type,
            'primary_services': site.primary_services or [],
            'service_areas': site.service_areas or [],
            'target_audience': site.target_audience or '',
            'business_description': site.business_description or '',
            'onboarding_complete': site.onboarding_complete,
        })

    @action(detail=True, methods=['get'], url_path='cannibalization-issues')
    def cannibalization_issues(self, request, pk=None):
        """
        Get all cannibalization issues for a site.
        
        GET /api/v1/sites/{id}/cannibalization-issues/
        """
        site = self.get_object()
        pages = site.pages.all().prefetch_related('seo_data')
        
        # Detect cannibalization
        issues = detect_cannibalization(pages)
        
        # Format for API response
        formatted_issues = []
        for i, issue in enumerate(issues):
            formatted_issues.append({
                'id': i + 1,
                'keyword': issue['keyword'],
                'severity': issue['severity'],
                'recommendation_type': issue['recommendation_type'],
                'total_impressions': issue.get('total_impressions', 0),
                'competing_pages': [
                    {
                        'id': p['id'],
                        'url': p['url'],
                        'title': p['title'],
                    }
                    for p in issue['competing_pages']
                ],
                'suggested_king': {
                    'id': issue['suggested_king']['id'],
                    'url': issue['suggested_king']['url'],
                    'title': issue['suggested_king']['title'],
                } if issue.get('suggested_king') else None,
            })
        
        return Response({
            'issues': formatted_issues,
            'total': len(formatted_issues),
        })

    @action(detail=True, methods=['get'], url_path='health-summary')
    def health_summary(self, request, pk=None):
        """
        Get detailed health summary for a site.
        
        GET /api/v1/sites/{id}/health-summary/
        """
        site = self.get_object()
        health = calculate_health_score(site)
        
        return Response({
            'site_id': site.id,
            'health_score': health['health_score'],
            'health_score_delta': health['health_score_delta'],
            'breakdown': health['breakdown'],
        })

    @action(detail=True, methods=['post'])
    def analyze(self, request, pk=None):
        """
        Run full analysis on a site.
        
        POST /api/v1/sites/{id}/analyze/
        """
        site = self.get_object()
        results = analyze_site(site)
        return Response(results)

    @action(detail=True, methods=['get'], url_path='pending-approvals')
    def pending_approvals(self, request, pk=None):
        """
        Get pending approval actions for a site.
        
        GET /api/v1/sites/{id}/pending-approvals/
        """
        # For now, return empty - will be populated by analysis
        return Response({
            'pending_approvals': [],
            'total': 0,
        })

    @action(detail=True, methods=['get'])
    def silos(self, request, pk=None):
        """
        Get content silos for a site.
        
        GET /api/v1/sites/{id}/silos/
        """
        # For now, return empty - silos need to be created first
        return Response({
            'silos': [],
            'total': 0,
        })
