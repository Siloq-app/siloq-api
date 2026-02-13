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
                'keyword': issue.get('keyword', ''),
                'severity': issue.get('severity', 'LOW').lower(),
                'recommendation_type': issue.get('recommendation_type') or issue.get('type', 'review'),
                'recommendation': issue.get('recommendation', ''),
                'total_impressions': issue.get('total_impressions', 0),
                'competing_pages': [
                    {
                        'id': p.get('id'),
                        'url': p.get('url', ''),
                        'title': p.get('title', ''),
                        'impression_share': p.get('impression_share'),
                    }
                    for p in issue.get('competing_pages', [])
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

    # =========================================================================
    # GSC Integration Actions
    # =========================================================================
    
    @action(detail=True, methods=['get'], url_path='gsc/status')
    def gsc_status(self, request, pk=None):
        """
        Check GSC connection status for a site.
        
        GET /api/v1/sites/{id}/gsc/status/
        """
        site = self.get_object()
        return Response({
            'connected': bool(site.gsc_refresh_token),
            'gsc_site_url': site.gsc_site_url,
            'connected_at': site.gsc_connected_at,
        })
    
    @action(detail=True, methods=['post'], url_path='gsc/connect')
    def gsc_connect(self, request, pk=None):
        """
        Connect GSC to this site.
        
        POST /api/v1/sites/{id}/gsc/connect/
        Body: { "gsc_site_url": "...", "access_token": "...", "refresh_token": "..." }
        """
        from django.utils import timezone
        
        site = self.get_object()
        
        gsc_site_url = request.data.get('gsc_site_url')
        access_token = request.data.get('access_token')
        refresh_token = request.data.get('refresh_token')
        
        if not gsc_site_url:
            return Response({'error': 'gsc_site_url required'}, status=status.HTTP_400_BAD_REQUEST)
        
        site.gsc_site_url = gsc_site_url
        if access_token:
            site.gsc_access_token = access_token
        if refresh_token:
            site.gsc_refresh_token = refresh_token
            from datetime import timedelta
            site.gsc_token_expires_at = timezone.now() + timedelta(hours=1)
        site.gsc_connected_at = timezone.now()
        site.save()
        
        return Response({
            'message': 'GSC connected successfully',
            'gsc_site_url': gsc_site_url,
        })
    
    @action(detail=True, methods=['get'], url_path='gsc/data')
    def gsc_data(self, request, pk=None):
        """
        Fetch GSC search analytics data.
        
        GET /api/v1/sites/{id}/gsc/data/?days=90
        """
        from integrations.gsc_views import _get_valid_access_token, _fetch_search_analytics
        from datetime import datetime, timedelta
        
        site = self.get_object()
        
        if not site.gsc_site_url or not site.gsc_refresh_token:
            return Response({'error': 'GSC not connected'}, status=status.HTTP_400_BAD_REQUEST)
        
        access_token = _get_valid_access_token(site)
        if not access_token:
            return Response({'error': 'Failed to get GSC access token'}, status=status.HTTP_401_UNAUTHORIZED)
        
        days = int(request.query_params.get('days', 90))
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        end_date = datetime.now().strftime('%Y-%m-%d')
        
        data = _fetch_search_analytics(
            access_token=access_token,
            site_url=site.gsc_site_url,
            start_date=start_date,
            end_date=end_date,
            dimensions=['query', 'page'],
            row_limit=5000,
        )
        
        return Response({
            'site_id': site.id,
            'gsc_site_url': site.gsc_site_url,
            'date_range': {'start': start_date, 'end': end_date},
            'row_count': len(data),
            'data': data,
        })
    
    @action(detail=True, methods=['post'], url_path='gsc/analyze')
    def gsc_analyze(self, request, pk=None):
        """
        Run cannibalization analysis on GSC data.
        
        POST /api/v1/sites/{id}/gsc/analyze/
        """
        from integrations.gsc_views import _get_valid_access_token, _fetch_search_analytics
        from .analysis import analyze_gsc_data
        
        site = self.get_object()
        
        if not site.gsc_site_url or not site.gsc_refresh_token:
            return Response({'error': 'GSC not connected'}, status=status.HTTP_400_BAD_REQUEST)
        
        access_token = _get_valid_access_token(site)
        if not access_token:
            return Response({'error': 'Failed to get GSC access token'}, status=status.HTTP_401_UNAUTHORIZED)
        
        gsc_data = _fetch_search_analytics(
            access_token=access_token,
            site_url=site.gsc_site_url,
            dimensions=['query', 'page'],
            row_limit=5000,
        )
        
        if not gsc_data:
            return Response({'error': 'No GSC data available'}, status=status.HTTP_404_NOT_FOUND)
        
        # Transform and analyze
        formatted_data = [
            {
                'query': row.get('query', ''),
                'page_url': row.get('page', ''),
                'clicks': row.get('clicks', 0),
                'impressions': row.get('impressions', 0),
                'position': row.get('position', 0),
            }
            for row in gsc_data
        ]
        
        issues = analyze_gsc_data(formatted_data)
        
        return Response({
            'site_id': site.id,
            'gsc_site_url': site.gsc_site_url,
            'queries_analyzed': len(gsc_data),
            'issues_found': len(issues),
            'issues': issues,
        })

    # =========================================================================
    # GEO Tools
    # =========================================================================
    
    @action(detail=True, methods=['get'], url_path='geo/llms-txt')
    def generate_llms_txt(self, request, pk=None):
        """
        Generate llms.txt content for AI crawler optimization.
        
        GET /api/v1/sites/{id}/geo/llms-txt/
        
        Returns markdown formatted llms.txt content that can be placed
        at the site root to help AI engines understand site structure.
        """
        site = self.get_object()
        pages = site.pages.filter(status='publish', is_noindex=False).order_by('url')
        
        # Group pages by type
        from .analysis import classify_page_type
        
        services = []
        products = []
        categories = []
        blog_posts = []
        other_pages = []
        
        for page in pages:
            page_type = classify_page_type(page.url, getattr(page, 'post_type', None))
            excerpt = (page.excerpt or page.content or '')[:150].strip()
            excerpt = excerpt.replace('\n', ' ').replace('\r', '')
            
            entry = {
                'title': page.title,
                'url': page.url,
                'excerpt': excerpt + '...' if len(excerpt) == 150 else excerpt,
            }
            
            if page_type == 'service':
                services.append(entry)
            elif page_type == 'product':
                products.append(entry)
            elif page_type == 'category':
                categories.append(entry)
            elif page_type in ['blog', 'listicle_blog']:
                blog_posts.append(entry)
            elif page_type != 'homepage':
                other_pages.append(entry)
        
        # Build llms.txt content
        lines = []
        lines.append(f"# {site.name}")
        
        # Business description
        if site.business_description:
            lines.append(f"> {site.business_description}")
        else:
            lines.append(f"> {site.name} - {site.url}")
        
        lines.append("")
        
        # Services
        if services:
            lines.append("## Services")
            for s in services[:20]:
                lines.append(f"- [{s['title']}]({s['url']}): {s['excerpt']}")
            lines.append("")
        
        # Products (for e-commerce)
        if products:
            lines.append("## Products")
            for p in products[:30]:
                lines.append(f"- [{p['title']}]({p['url']}): {p['excerpt']}")
            lines.append("")
        
        # Categories
        if categories:
            lines.append("## Categories")
            for c in categories[:20]:
                lines.append(f"- [{c['title']}]({c['url']}): {c['excerpt']}")
            lines.append("")
        
        # Service Areas
        if site.service_areas:
            lines.append("## Service Areas")
            areas = site.service_areas if isinstance(site.service_areas, list) else []
            for area in areas[:10]:
                if isinstance(area, str):
                    lines.append(f"- {area}")
            lines.append("")
        
        # Blog/Resources
        if blog_posts:
            lines.append("## Resources")
            for b in blog_posts[:15]:
                lines.append(f"- [{b['title']}]({b['url']})")
            lines.append("")
        
        # Contact
        lines.append("## Contact")
        lines.append(f"- [Website]({site.url})")
        
        llms_txt = '\n'.join(lines)
        
        return Response({
            'site_id': site.id,
            'site_name': site.name,
            'llms_txt': llms_txt,
            'page_count': pages.count(),
            'sections': {
                'services': len(services),
                'products': len(products),
                'categories': len(categories),
                'blog_posts': len(blog_posts),
            },
            'instructions': "Add this content to a file named 'llms.txt' at your site root (e.g., https://yoursite.com/llms.txt)",
        })
    
    @action(detail=True, methods=['get'], url_path='geo/score')
    def geo_score(self, request, pk=None):
        """
        Get GEO readiness score for a site.
        
        GET /api/v1/sites/{id}/geo/score/
        """
        site = self.get_object()
        results = analyze_site(site)
        
        return Response({
            'site_id': site.id,
            'geo_score': results.get('geo_score', 0),
            'geo_pages_analyzed': results.get('geo_pages_analyzed', 0),
            'geo_issues_count': results.get('geo_issues_count', 0),
            'geo_results': results.get('geo_results', []),
            'geo_recommendations': results.get('geo_recommendations', []),
        })
