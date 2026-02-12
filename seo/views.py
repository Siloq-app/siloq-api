"""
Views for Page and SEOData management.
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.utils import timezone
from .models import Page, SEOData
from .serializers import PageSerializer, PageListSerializer, PageSyncSerializer, SEODataSerializer
from sites.models import Site


class PageViewSet(viewsets.ModelViewSet):
    """
    ViewSet for viewing and managing pages.
    
    list: GET /api/v1/pages/ - List pages (filtered by site_id)
    retrieve: GET /api/v1/pages/{id}/ - Get page details with SEO data
    """
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'patch', 'head', 'options']  # GET, POST (for actions), PATCH

    def get_queryset(self):
        """Return pages for sites owned by the current user."""
        user_sites = Site.objects.filter(user=self.request.user)
        queryset = Page.objects.filter(site__in=user_sites)
        
        # Filter by site_id if provided
        site_id = self.request.query_params.get('site_id')
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        
        # Filter out noindex pages by default (unless include_noindex=true)
        include_noindex = self.request.query_params.get('include_noindex', 'false').lower()
        if include_noindex != 'true':
            queryset = queryset.filter(is_noindex=False)
        
        return queryset.select_related('site', 'seo_data')

    def get_serializer_class(self):
        """Use lightweight serializer for list, full serializer for detail."""
        if self.action == 'list':
            return PageListSerializer
        return PageSerializer

    @action(detail=True, methods=['get'])
    def seo(self, request, pk=None):
        """
        Get detailed SEO data for a page.
        
        GET /api/v1/pages/{id}/seo/
        """
        page = self.get_object()
        try:
            seo_data = page.seo_data
        except Exception:
            seo_data = None
        
        if not seo_data:
            return Response(
                {'message': 'No SEO data available for this page'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = SEODataSerializer(seo_data)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def toggle_money_page(self, request, pk=None):
        """
        Toggle whether a page is a money page.
        
        POST /api/v1/pages/{id}/toggle_money_page/
        Body: { "is_money_page": true/false }
        """
        page = self.get_object()
        is_money = request.data.get('is_money_page')
        
        if is_money is None:
            # Toggle if not specified
            page.is_money_page = not page.is_money_page
        else:
            page.is_money_page = bool(is_money)
        
        page.save(update_fields=['is_money_page'])
        
        return Response({
            'id': page.id,
            'is_money_page': page.is_money_page,
            'message': 'Money page status updated'
        })
