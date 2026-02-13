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
        Auto-generates silos from money pages (target pages) and groups
        non-money pages as supporting pages by matching URL path hierarchy.
        
        GET /api/v1/sites/{id}/silos/
        """
        site = self.get_object()
        from seo.models import Page
        pages = Page.objects.filter(site=site, is_noindex=False)
        
        money_pages = pages.filter(is_money_page=True).order_by('url')
        all_pages = list(pages.values('id', 'title', 'url', 'status', 'post_type', 'is_money_page'))
        
        silos = []
        assigned_ids = set()
        
        for mp in money_pages:
            mp_url = mp.url.rstrip('/')
            # Find supporting pages: same URL prefix or pages that link to this money page
            supporting = []
            for p in all_pages:
                if p['id'] == mp.id or p['id'] in assigned_ids or p.get('is_money_page'):
                    continue
                p_url = (p['url'] or '').rstrip('/')
                # Match by URL hierarchy (e.g. /services/roofing/ supports /services/)
                if mp_url and p_url and p_url.startswith(mp_url + '/'):
                    supporting.append(p)
                    assigned_ids.add(p['id'])
            
            silos.append({
                'id': mp.id,
                'name': mp.title or mp.url,
                'target_page': {
                    'id': mp.id,
                    'title': mp.title,
                    'url': mp.url,
                    'status': mp.status or 'publish',
                },
                'topic_cluster': None,
                'supporting_pages': [
                    {
                        'id': sp['id'],
                        'title': sp['title'],
                        'url': sp['url'],
                        'status': sp.get('status', 'publish'),
                    }
                    for sp in supporting
                ],
                'page_count': 1 + len(supporting),
            })
        
        # If no money pages set yet, create silos from pages that look like target pages
        # (homepage, service pages, category pages) so the dropdown isn't empty
        if not silos:
            # Group by top-level URL path
            from collections import defaultdict
            from urllib.parse import urlparse
            path_groups = defaultdict(list)
            for p in all_pages:
                parsed = urlparse(p['url'] or '')
                parts = [x for x in parsed.path.strip('/').split('/') if x]
                group = parts[0] if parts else 'home'
                path_groups[group].append(p)
            
            for group_name, group_pages in path_groups.items():
                if not group_pages:
                    continue
                # Pick the shortest URL as the target page
                group_pages.sort(key=lambda x: len(x['url'] or ''))
                target = group_pages[0]
                supporting = group_pages[1:10]  # Cap at 10 for display
                
                silos.append({
                    'id': target['id'],
                    'name': group_name.replace('-', ' ').title(),
                    'target_page': {
                        'id': target['id'],
                        'title': target['title'],
                        'url': target['url'],
                        'status': target.get('status', 'publish'),
                    },
                    'topic_cluster': None,
                    'supporting_pages': [
                        {
                            'id': sp['id'],
                            'title': sp['title'],
                            'url': sp['url'],
                            'status': sp.get('status', 'publish'),
                        }
                        for sp in supporting
                    ],
                    'page_count': 1 + len(supporting),
                })
        
        return Response({
            'silos': silos,
            'total': len(silos),
        })

    @action(detail=True, methods=['post'], url_path='generate-silos')
    def generate_silos(self, request, pk=None):
        """
        Generate silo suggestions based on business profile.
        
        POST /api/v1/sites/{id}/generate-silos/
        """
        site = self.get_object()
        
        # Build suggestions from existing pages
        pages = site.pages.filter(status='publish', is_noindex=False)
        from .analysis import classify_page_type
        
        service_silos = []
        location_silos = []
        
        for page in pages:
            page_type = classify_page_type(page.url, getattr(page, 'post_type', None))
            if page_type == 'service':
                service_silos.append({
                    'service': page.title,
                    'suggested_target_page': {
                        'title': page.title,
                        'slug': page.slug,
                        'description': (page.excerpt or '')[:200],
                    },
                    'suggested_supporting_topics': [
                        f'How to Choose {page.title}',
                        f'{page.title} FAQ',
                        f'{page.title} vs Alternatives',
                    ],
                })
            elif page_type == 'location':
                location_silos.append({
                    'area': page.title,
                    'suggested_page': {
                        'title': page.title,
                        'slug': page.slug,
                    },
                    'can_create_per_service': True,
                })
        
        return Response({
            'service_silos': service_silos[:20],
            'location_silos': location_silos[:20],
            'total_suggested_pages': len(service_silos) * 4 + len(location_silos),
        })

    @action(detail=True, methods=['get'], url_path='anchor-conflicts')
    def anchor_conflicts(self, request, pk=None):
        """
        Get anchor text conflicts for a site.
        
        GET /api/v1/sites/{id}/anchor-conflicts/
        """
        from seo.models import AnchorTextConflict
        
        site = self.get_object()
        conflicts = AnchorTextConflict.objects.filter(site=site, is_resolved=False)
        
        return Response({
            'conflicts': [
                {
                    'anchor_text': c.anchor_text,
                    'target_pages': [
                        {
                            'id': p.id,
                            'url': p.url,
                            'title': p.title,
                            'is_money_page': p.is_money_page,
                        }
                        for p in c.conflicting_pages.all()
                    ],
                    'occurrence_count': c.occurrence_count,
                    'severity': c.severity,
                }
                for c in conflicts[:50]
            ],
            'total': conflicts.count(),
        })

    @action(detail=True, methods=['get'], url_path='anchor-text-overview')
    def anchor_text_overview(self, request, pk=None):
        """
        Get anchor text overview for a site.
        
        GET /api/v1/sites/{id}/anchor-text-overview/
        """
        from seo.models import InternalLink
        from collections import Counter
        
        site = self.get_object()
        links = InternalLink.objects.filter(site=site, anchor_text_normalized__gt='')
        
        anchor_counts = Counter()
        anchor_targets = {}
        
        for link in links.values('anchor_text_normalized', 'target_page_id'):
            text = link['anchor_text_normalized']
            anchor_counts[text] += 1
            if text not in anchor_targets:
                anchor_targets[text] = set()
            if link['target_page_id']:
                anchor_targets[text].add(link['target_page_id'])
        
        anchors = [
            {
                'text': text,
                'count': count,
                'target_pages': list(anchor_targets.get(text, set())),
            }
            for text, count in anchor_counts.most_common(100)
        ]
        
        return Response({
            'total_anchors': links.count(),
            'unique_anchors': len(anchor_counts),
            'anchors': anchors,
        })

    @action(detail=True, methods=['get'], url_path='link-structure')
    def link_structure(self, request, pk=None):
        """
        Get link structure for a site (simplified version of internal-links).
        
        GET /api/v1/sites/{id}/link-structure/
        """
        site = self.get_object()
        pages = site.pages.filter(status='publish', is_noindex=False)
        
        homepage = pages.filter(is_homepage=True).first()
        money_pages = pages.filter(is_money_page=True)
        
        silos = []
        for mp in money_pages:
            supporting = pages.filter(parent_silo=mp)
            silos.append({
                'target': {'id': mp.id, 'url': mp.url, 'title': mp.title, 'slug': mp.slug},
                'supporting_pages': [
                    {'id': p.id, 'url': p.url, 'title': p.title, 'slug': p.slug}
                    for p in supporting
                ],
                'supporting_count': supporting.count(),
                'links': [],
            })
        
        return Response({
            'homepage': {'id': homepage.id, 'url': homepage.url, 'title': homepage.title} if homepage else None,
            'silos': silos,
            'total_target_pages': money_pages.count(),
            'total_supporting_pages': pages.filter(parent_silo__isnull=False).count(),
        })

    @action(detail=True, methods=['get'])
    def recommendations(self, request, pk=None):
        """
        Get content recommendations for a site.
        
        GET /api/v1/sites/{id}/recommendations/
        """
        site = self.get_object()
        
        # Generate recommendations from analysis
        results = analyze_site(site)
        recs = results.get('recommendations', [])
        
        return Response({
            'recommendations': recs,
            'total': len(recs),
        })

    # =========================================================================
    # Content Generation
    # =========================================================================

    @action(detail=True, methods=['post'], url_path='generate-content')
    def generate_content(self, request, pk=None):
        """
        Generate supporting page content using AI.
        
        POST /api/v1/sites/{id}/generate-content/
        Body: {
            "target_page_id": 123,
            "content_type": "supporting_article",  // faq, how_to, comparison
            "topic": "How to Choose the Right Dance Jacket"
        }
        """
        from seo.content_generation import generate_supporting_content
        from seo.models import Page
        
        site = self.get_object()
        target_page_id = request.data.get('target_page_id')
        content_type = request.data.get('content_type', 'supporting_article')
        topic = request.data.get('topic', '')
        
        if not target_page_id:
            return Response({'error': 'target_page_id required'}, status=status.HTTP_400_BAD_REQUEST)
        
        if not topic:
            return Response({'error': 'topic required'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            target_page = Page.objects.get(id=target_page_id, site=site)
        except Page.DoesNotExist:
            return Response({'error': 'Target page not found'}, status=status.HTTP_404_NOT_FOUND)
        
        result = generate_supporting_content(
            target_page_title=target_page.title,
            target_page_url=target_page.url,
            content_type=content_type,
            topic=topic,
            business_name=site.name,
            business_type=site.business_type or '',
            service_areas=site.service_areas or [],
        )
        
        if not result.get('success'):
            return Response({
                'error': result.get('error', 'Content generation failed'),
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return Response({
            'success': True,
            'target_page': {
                'id': target_page.id,
                'title': target_page.title,
                'url': target_page.url,
            },
            'generated': {
                'title': result.get('title', ''),
                'content': result.get('content', ''),
                'meta_description': result.get('meta_description', ''),
                'suggested_slug': result.get('suggested_slug', ''),
                'internal_links': result.get('internal_links', []),
                'word_count': result.get('word_count', 0),
            },
            'model_used': result.get('model_used', ''),
            'tokens_used': result.get('tokens_used', 0),
        })

    # =========================================================================
    # Approval Actions
    # =========================================================================

    @action(detail=True, methods=['post'], url_path=r'approvals/(?P<action_id>\d+)/approve')
    def approve_action(self, request, pk=None, action_id=None):
        """
        Approve a pending action.
        
        POST /api/v1/sites/{id}/approvals/{action_id}/approve/
        """
        return Response({
            'message': 'Action approved',
            'action_id': int(action_id),
            'status': 'approved',
        })

    @action(detail=True, methods=['post'], url_path=r'approvals/(?P<action_id>\d+)/deny')
    def deny_action(self, request, pk=None, action_id=None):
        """
        Deny a pending action.
        
        POST /api/v1/sites/{id}/approvals/{action_id}/deny/
        """
        return Response({
            'message': 'Action denied',
            'action_id': int(action_id),
            'status': 'denied',
        })

    @action(detail=True, methods=['post'], url_path=r'approvals/(?P<action_id>\d+)/rollback')
    def rollback_action(self, request, pk=None, action_id=None):
        """
        Rollback an approved action.
        
        POST /api/v1/sites/{id}/approvals/{action_id}/rollback/
        """
        return Response({
            'message': 'Action rolled back',
            'action_id': int(action_id),
            'status': 'rolled_back',
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
    
    @action(detail=True, methods=['post'], url_path='gsc/disconnect')
    def gsc_disconnect(self, request, pk=None):
        """
        Disconnect GSC from this site (allows reconnection).
        
        POST /api/v1/sites/{id}/gsc/disconnect/
        """
        site = self.get_object()
        site.gsc_site_url = ''
        site.gsc_access_token = ''
        site.gsc_refresh_token = ''
        site.gsc_token_expires_at = None
        site.gsc_connected_at = None
        site.save()
        
        return Response({
            'message': 'GSC disconnected successfully',
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

    # =========================================================================
    # Smart Money Page Detection
    # =========================================================================

    @action(detail=True, methods=['get'], url_path='suggested-money-pages')
    def suggested_money_pages(self, request, pk=None):
        """
        Auto-detect likely money pages based on URL patterns, post type, and content.
        Returns categorized suggestions for the user to confirm.
        
        GET /api/v1/sites/{id}/suggested-money-pages/
        """
        from .analysis import classify_page_type
        
        site = self.get_object()
        pages = site.pages.filter(status='publish', is_noindex=False)
        
        suggestions = {
            'homepage': [],
            'service_pages': [],
            'product_categories': [],
            'key_products': [],
            'location_pages': [],
        }
        
        already_money = set(pages.filter(is_money_page=True).values_list('id', flat=True))
        
        for page in pages:
            page_type = classify_page_type(page.url, getattr(page, 'post_type', None))
            entry = {
                'id': page.id,
                'url': page.url,
                'title': page.title,
                'page_type': page_type,
                'post_type': page.post_type,
                'is_money_page': page.id in already_money,
                'reason': '',
            }
            
            if page.is_homepage or page_type == 'homepage':
                entry['reason'] = 'Homepage — the foundation of your site authority'
                suggestions['homepage'].append(entry)
            elif page_type == 'service':
                entry['reason'] = 'Service page — directly drives business revenue'
                suggestions['service_pages'].append(entry)
            elif page_type == 'category':
                entry['reason'] = 'Category page — key shopping/browsing entry point'
                suggestions['product_categories'].append(entry)
            elif page_type == 'location':
                entry['reason'] = 'Location page — captures local search traffic'
                suggestions['location_pages'].append(entry)
            elif page_type == 'product' and page.post_type == 'product':
                # Only suggest top products (ones with short URLs or featured)
                url_depth = page.url.count('/') if page.url else 0
                if url_depth <= 4:  # Not too deeply nested
                    entry['reason'] = 'Product page — direct revenue generator'
                    suggestions['key_products'].append(entry)
        
        # Limit products to top 20 (most likely important ones)
        suggestions['key_products'] = suggestions['key_products'][:20]
        
        # Count totals
        total_suggested = sum(len(v) for v in suggestions.values())
        already_marked = sum(1 for v in suggestions.values() for p in v if p['is_money_page'])
        
        return Response({
            'site_id': site.id,
            'total_pages': pages.count(),
            'total_suggested': total_suggested,
            'already_marked': already_marked,
            'suggestions': suggestions,
            'message': f"Siloq found {total_suggested} pages that look like money pages. "
                       f"{already_marked} are already marked. Review and confirm below.",
        })

    @action(detail=True, methods=['post'], url_path='bulk-set-money-pages')
    def bulk_set_money_pages(self, request, pk=None):
        """
        Accept or modify money page suggestions in bulk.
        
        POST /api/v1/sites/{id}/bulk-set-money-pages/
        Body: { "page_ids": [1, 2, 3], "clear_others": false }
        """
        from seo.models import Page
        
        site = self.get_object()
        page_ids = request.data.get('page_ids', [])
        clear_others = request.data.get('clear_others', False)
        
        if not page_ids:
            return Response({'error': 'page_ids required'}, status=status.HTTP_400_BAD_REQUEST)
        
        if clear_others:
            # Clear all money page flags first
            Page.objects.filter(site=site, is_money_page=True).update(is_money_page=False)
        
        # Set selected pages as money pages
        updated = Page.objects.filter(site=site, id__in=page_ids).update(is_money_page=True)
        
        return Response({
            'message': f'{updated} money pages set successfully',
            'money_page_count': updated,
        })

    # =========================================================================
    # Sync & Internal Links Actions
    # =========================================================================

    @action(detail=True, methods=['get'], url_path='sync-status')
    def sync_status(self, request, pk=None):
        """
        Get sync status for a site.
        
        GET /api/v1/sites/{id}/sync-status/
        """
        site = self.get_object()
        page_count = site.pages.count()
        
        return Response({
            'site_id': site.id,
            'site_name': site.name,
            'page_count': page_count,
            'last_synced_at': site.last_synced_at,
            'sync_requested_at': getattr(site, 'sync_requested_at', None),
            'is_synced': page_count > 0,
        })

    @action(detail=True, methods=['post'], url_path='trigger-sync')
    def trigger_sync(self, request, pk=None):
        """
        Request a sync from WordPress plugin.
        Sets a flag that the WP plugin can check to initiate sync.
        
        POST /api/v1/sites/{id}/trigger-sync/
        """
        site = self.get_object()
        
        # Update sync_requested_at timestamp
        from django.utils import timezone
        now = timezone.now()
        if hasattr(site, 'sync_requested_at'):
            site.sync_requested_at = now
            site.save(update_fields=['sync_requested_at'])
        
        return Response({
            'message': 'Sync requested successfully',
            'site_id': site.id,
            'site_name': site.name,
            'instructions': 'Go to WordPress Admin → Siloq → click "Sync Now" to push pages to Siloq.',
            'sync_requested_at': now.isoformat(),
        })

    @action(detail=True, methods=['get'], url_path='internal-links')
    def internal_links(self, request, pk=None):
        """
        Get internal links analysis for a site.
        
        GET /api/v1/sites/{id}/internal-links/
        """
        from seo.models import Page, InternalLink
        
        site = self.get_object()
        pages = site.pages.filter(status='publish', is_noindex=False)
        
        # Build silo structure
        homepage = pages.filter(is_homepage=True).first()
        money_pages = pages.filter(is_money_page=True)
        
        silos = []
        for mp in money_pages:
            supporting = pages.filter(parent_silo=mp)
            
            # Get links within this silo
            silo_page_ids = [mp.id] + list(supporting.values_list('id', flat=True))
            links = InternalLink.objects.filter(
                site=site,
                source_page_id__in=silo_page_ids,
                target_page_id__in=silo_page_ids,
            )
            
            silos.append({
                'target': {
                    'id': mp.id,
                    'url': mp.url,
                    'title': mp.title,
                    'slug': mp.slug,
                },
                'supporting_pages': [
                    {'id': p.id, 'url': p.url, 'title': p.title, 'slug': p.slug}
                    for p in supporting
                ],
                'supporting_count': supporting.count(),
                'links': [
                    {
                        'source_id': l.source_page_id,
                        'target_id': l.target_page_id,
                        'anchor_text': l.anchor_text,
                    }
                    for l in links
                ],
            })
        
        # Detect issues
        anchor_conflicts = []
        homepage_theft = []
        missing_target_links = []
        missing_sibling_links = []
        orphan_pages = []
        silo_size_issues = []
        
        # Check for orphan pages (no incoming links)
        for page in pages:
            if not page.is_homepage and not page.is_money_page:
                incoming = InternalLink.objects.filter(site=site, target_page=page).count()
                if incoming == 0:
                    orphan_pages.append({
                        'page': {'id': page.id, 'url': page.url, 'title': page.title},
                        'severity': 'medium',
                        'recommendation': 'Add internal links pointing to this page',
                    })
        
        total_issues = (
            len(anchor_conflicts) + len(homepage_theft) + 
            len(missing_target_links) + len(orphan_pages) +
            len(silo_size_issues)
        )
        
        # Simple health score
        health_score = max(0, 100 - total_issues * 5)
        
        return Response({
            'health_score': health_score,
            'health_breakdown': {
                'anchor_conflicts': {'score': 100, 'issues': len(anchor_conflicts), 'weight': 25},
                'homepage_protection': {'score': 100, 'issues': len(homepage_theft), 'weight': 25},
                'target_links': {'score': 100, 'issues': len(missing_target_links), 'weight': 25},
                'orphan_pages': {'score': max(0, 100 - len(orphan_pages) * 10), 'issues': len(orphan_pages), 'weight': 25},
            },
            'total_issues': total_issues,
            'issues': {
                'anchor_conflicts': anchor_conflicts,
                'homepage_theft': homepage_theft,
                'missing_target_links': missing_target_links,
                'missing_sibling_links': missing_sibling_links,
                'orphan_pages': orphan_pages[:20],  # Limit response size
                'silo_size_issues': silo_size_issues,
            },
            'structure': {
                'homepage': {
                    'id': homepage.id,
                    'url': homepage.url,
                    'title': homepage.title,
                } if homepage else None,
                'silos': silos,
                'total_target_pages': money_pages.count(),
                'total_supporting_pages': pages.filter(parent_silo__isnull=False).count(),
            },
            'recommendations': [],
        })

    @action(detail=True, methods=['post'], url_path='sync-links')
    def sync_links(self, request, pk=None):
        """
        Extract and store internal links from page content.
        
        POST /api/v1/sites/{id}/sync-links/
        """
        import re
        from urllib.parse import urlparse
        from seo.models import Page, InternalLink
        
        site = self.get_object()
        pages = site.pages.filter(status='publish')
        
        # Build URL to page mapping
        url_to_page = {}
        for page in pages:
            if page.url:
                parsed = urlparse(page.url)
                path = parsed.path.rstrip('/')
                url_to_page[path] = page
                url_to_page[page.url] = page
        
        # Clear existing links for this site
        InternalLink.objects.filter(site=site).delete()
        
        total_links = 0
        pages_processed = 0
        
        for page in pages:
            content = page.content or ''
            # Find all href links in content
            links = re.findall(r'href=["\']([^"\']+)["\']', content)
            
            for link_url in links:
                # Check if internal
                try:
                    parsed = urlparse(link_url)
                    site_parsed = urlparse(site.url)
                    
                    # Skip external links
                    if parsed.netloc and parsed.netloc != site_parsed.netloc:
                        continue
                    
                    # Normalize path
                    path = parsed.path.rstrip('/')
                    target_page = url_to_page.get(path) or url_to_page.get(link_url)
                    
                    # Extract anchor text (simplified - from surrounding HTML)
                    anchor_match = re.search(
                        rf'<a[^>]*href=["\']' + re.escape(link_url) + r'["\'][^>]*>(.*?)</a>',
                        content, re.DOTALL
                    )
                    anchor_text = ''
                    if anchor_match:
                        anchor_text = re.sub(r'<[^>]+>', '', anchor_match.group(1)).strip()
                    
                    InternalLink.objects.create(
                        site=site,
                        source_page=page,
                        target_page=target_page,
                        target_url=link_url if link_url.startswith('http') else f"{site.url.rstrip('/')}{link_url}",
                        anchor_text=anchor_text[:500],
                        is_in_content=True,
                    )
                    total_links += 1
                except Exception:
                    continue
            
            pages_processed += 1
        
        return Response({
            'message': 'Links synced successfully',
            'pages_processed': pages_processed,
            'total_links_found': total_links,
        })

    @action(detail=True, methods=['post'], url_path='set-homepage')
    def set_homepage(self, request, pk=None):
        """
        Set a page as the homepage for this site.
        
        POST /api/v1/sites/{id}/set-homepage/
        Body: { "page_id": 123 }
        """
        from seo.models import Page
        
        site = self.get_object()
        page_id = request.data.get('page_id')
        
        if not page_id:
            return Response({'error': 'page_id required'}, status=status.HTTP_400_BAD_REQUEST)
        
        page = get_object_or_404(Page, id=page_id, site=site)
        
        # Clear existing homepage
        Page.objects.filter(site=site, is_homepage=True).update(is_homepage=False)
        
        page.is_homepage = True
        page.save(update_fields=['is_homepage'])
        
        return Response({
            'message': 'Homepage set successfully',
            'page_id': page.id,
        })

    @action(detail=True, methods=['post'], url_path='assign-silo')
    def assign_silo(self, request, pk=None):
        """
        Assign a page to a silo (set parent_silo).
        
        POST /api/v1/sites/{id}/assign-silo/
        Body: { "page_id": 123, "target_page_id": 456 }
        """
        from seo.models import Page
        
        site = self.get_object()
        page_id = request.data.get('page_id')
        target_page_id = request.data.get('target_page_id')
        
        if not page_id:
            return Response({'error': 'page_id required'}, status=status.HTTP_400_BAD_REQUEST)
        
        page = get_object_or_404(Page, id=page_id, site=site)
        
        if target_page_id:
            target = get_object_or_404(Page, id=target_page_id, site=site)
            page.parent_silo = target
        else:
            page.parent_silo = None
        
        page.save(update_fields=['parent_silo'])
        
        return Response({
            'message': 'Silo assignment updated',
            'page_id': page.id,
            'parent_silo_id': target_page_id,
        })

    @action(detail=True, methods=['get'], url_path='content-suggestions')
    def content_suggestions(self, request, pk=None):
        """
        Generate content suggestions based on money pages.
        
        GET /api/v1/sites/{id}/content-suggestions/
        """
        site = self.get_object()
        pages = site.pages.filter(status='publish', is_noindex=False)
        money_pages = pages.filter(is_money_page=True)
        
        suggestions = []
        for mp in money_pages:
            supporting = pages.filter(parent_silo=mp)
            
            # Check what content types exist
            has_how_to = any('how' in (p.title or '').lower() for p in supporting)
            has_comparison = any(w in (p.title or '').lower() for p in supporting for w in ['vs', 'compare', 'comparison'])
            has_guide = any('guide' in (p.title or '').lower() for p in supporting)
            has_faq = any('faq' in (p.title or '').lower() or '?' in (p.title or '') for p in supporting)
            
            # Generate topic suggestions based on gaps
            topics = []
            title_base = mp.title or 'this service'
            if not has_how_to:
                topics.append({'title': f'How to Choose the Right {title_base}', 'type': 'how-to', 'priority': 'high'})
            if not has_comparison:
                topics.append({'title': f'{title_base} vs Alternatives: Complete Comparison', 'type': 'comparison', 'priority': 'medium'})
            if not has_guide:
                topics.append({'title': f'The Ultimate Guide to {title_base}', 'type': 'educational', 'priority': 'medium'})
            if not has_faq:
                topics.append({'title': f'Frequently Asked Questions About {title_base}', 'type': 'tips', 'priority': 'low'})
            
            suggestions.append({
                'target_page': {
                    'id': mp.id,
                    'title': mp.title,
                    'url': mp.url,
                },
                'existing_supporting_count': supporting.count(),
                'suggested_topics': topics,
                'gap_analysis': {
                    'has_how_to': has_how_to,
                    'has_comparison': has_comparison,
                    'has_guide': has_guide,
                    'has_faq': has_faq,
                },
            })
        
        total_topics = sum(len(s['suggested_topics']) for s in suggestions)
        
        return Response({
            'total_targets': money_pages.count(),
            'total_suggested_topics': total_topics,
            'suggestions': suggestions,
        })
