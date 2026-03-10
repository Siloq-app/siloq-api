"""
Views for Page and SEOData management.
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.utils import timezone
from .models import Page, SEOData
from .serializers import PageSerializer, PageListSerializer, PageSyncSerializer, SEODataSerializer
from sites.models import Site


class LargeResultsSetPagination(PageNumberPagination):
    """Allow up to 1000 pages per request for dashboard views."""
    page_size = 1000
    page_size_query_param = 'page_size'
    max_page_size = 5000


class PageViewSet(viewsets.ModelViewSet):
    """
    ViewSet for viewing and managing pages.
    
    list: GET /api/v1/pages/ - List pages (filtered by site_id)
    retrieve: GET /api/v1/pages/{id}/ - Get page details with SEO data
    """
    permission_classes = [IsAuthenticated]
    pagination_class = LargeResultsSetPagination
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

    @action(detail=True, methods=['patch'], url_path='page-type')
    def set_page_type(self, request, pk=None):
        """
        PATCH /api/v1/pages/{id}/page-type/
        Set a manual page type override. Send null to clear the override.
        Body: { "page_type": "money" | "supporting" | "utility" | "conversion" | "archive" | "product" | null }
        """
        VALID_TYPES = {'money', 'supporting', 'utility', 'conversion', 'archive', 'product'}
        page = self.get_object()
        page_type = request.data.get('page_type')

        if page_type is None:
            # Clear override — revert to auto-classification
            page.page_type_override = None
        elif page_type not in VALID_TYPES:
            return Response(
                {'error': f'Invalid page_type. Must be one of: {", ".join(sorted(VALID_TYPES))}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        else:
            page.page_type_override = page_type

        page.save(update_fields=['page_type_override'])
        return Response({
            'id': page.id,
            'page_type_override': page.page_type_override,
            'page_type_classification': page.page_type_classification,
            'effective_type': page.page_type_override or page.page_type_classification,
        })
