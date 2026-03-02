"""
Page management views.
Handles listing and retrieving pages with SEO data.
"""
import logging
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import Page
from .serializers import PageSerializer, PageListSerializer
from sites.models import Site

logger = logging.getLogger(__name__)


class LargeResultsSetPagination(PageNumberPagination):
    """Allow up to 1000 pages per request for dashboard views."""
    page_size = 1000
    page_size_query_param = 'page_size'
    max_page_size = 5000


class PageViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing pages (read-only for dashboard).
    
    list: GET /api/v1/pages/ - List pages (filtered by site_id)
    retrieve: GET /api/v1/pages/{id}/ - Get page details with SEO data
    """
    permission_classes = [IsAuthenticated]
    pagination_class = LargeResultsSetPagination

    def get_queryset(self):
        """Return pages for sites owned by the current user."""
        user_sites = Site.objects.filter(user=self.request.user)
        queryset = Page.objects.filter(site__in=user_sites)
        
        # Filter out noindex pages by default
        include_noindex = self.request.query_params.get('include_noindex', 'false').lower()
        if include_noindex != 'true':
            queryset = queryset.filter(is_noindex=False)

        # Filter by site_id if provided
        site_id = self.request.query_params.get('site_id')
        if site_id:
            queryset = queryset.filter(site_id=site_id)

        # Prefetch related seo_data for list efficiency (OneToOne relation)
        return queryset.select_related('site', 'seo_data')

    def get_serializer_class(self):
        """Use lightweight serializer for list, full serializer for detail."""
        if self.action == 'list':
            return PageListSerializer
        return PageSerializer

    def list(self, request, *args, **kwargs):
        """Override list to enrich pages with GSC metrics (clicks, impressions, position)."""
        response = super().list(request, *args, **kwargs)

        # Determine site from query param
        site_id = request.query_params.get('site_id')
        if not site_id:
            return response

        try:
            site = Site.objects.get(id=site_id, user=request.user)
        except Site.DoesNotExist:
            return response

        # Check if GSC is connected
        if not getattr(site, 'gsc_refresh_token', None):
            return response

        # Fetch GSC page-level data
        try:
            from integrations.gsc import refresh_access_token, fetch_search_analytics
            tokens = refresh_access_token(site.gsc_refresh_token)
            access_token = tokens.get('access_token', '')
            if not access_token or not site.gsc_site_url:
                return response

            rows = fetch_search_analytics(
                access_token, site.gsc_site_url,
                dimensions=['page'], row_limit=5000,
            )

            # Build lookup maps with URL normalization
            gsc_data = {}  # normalized_url -> {clicks, impressions, position}
            for row in rows:
                page_url = row.get('keys', [''])[0] if row.get('keys') else row.get('page', '')
                normalized = page_url.rstrip('/')
                if normalized not in gsc_data:
                    gsc_data[normalized] = {'clicks': 0, 'impressions': 0, 'position': None}
                gsc_data[normalized]['clicks'] += row.get('clicks', 0)
                gsc_data[normalized]['impressions'] += row.get('impressions', 0)
                pos = row.get('position', 0)
                if gsc_data[normalized]['position'] is None or pos < gsc_data[normalized]['position']:
                    gsc_data[normalized]['position'] = round(pos, 1)

            # Enrich each page in the response
            pages_list = response.data.get('results', response.data) if isinstance(response.data, dict) else response.data
            if isinstance(pages_list, list):
                for page_data in pages_list:
                    url = (page_data.get('url') or '').rstrip('/')
                    metrics = gsc_data.get(url, {})
                    page_data['gsc_clicks'] = metrics.get('clicks', 0)
                    page_data['gsc_impressions'] = metrics.get('impressions', 0)
                    page_data['gsc_position'] = metrics.get('position', None)

        except Exception as e:
            logger.warning(f"Failed to enrich pages with GSC data for site {site_id}: {e}")

        return response

    @action(detail=True, methods=['post'])
    def toggle_money_page(self, request, pk=None):
        """
        Toggle the is_money_page status for a page.
        POST /api/v1/pages/{id}/toggle_money_page/
        """
        try:
            # Get the page, ensuring it belongs to the user's sites
            user_sites = Site.objects.filter(user=request.user)
            page = Page.objects.get(pk=pk, site__in=user_sites)
            
            # Toggle the field
            page.is_money_page = not page.is_money_page
            page.save(update_fields=['is_money_page'])
            
            return Response({
                'success': True,
                'id': page.id,
                'is_money_page': page.is_money_page,
                'message': f'Page "{page.title}" is now {"a money page" if page.is_money_page else "a regular page"}.'
            }, status=status.HTTP_200_OK)
            
        except Page.DoesNotExist:
            return Response({
                'success': False,
                'error': 'Page not found or you do not have permission to modify it.'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
