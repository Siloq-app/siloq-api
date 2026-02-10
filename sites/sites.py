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
