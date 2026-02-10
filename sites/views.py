"""
Views for Site and APIKey management.
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.utils import timezone
from .models import Site, APIKey
from .serializers import SiteSerializer, APIKeySerializer, APIKeyCreateSerializer
from .permissions import IsSiteOwner, IsAPIKeyOwner
from .analysis import analyze_site, detect_cannibalization, calculate_health_score


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

    @action(detail=True, methods=['get'])
    def overview(self, request, pk=None):
        """
        Get site overview with health score and aggregated stats.
        
        GET /api/v1/sites/{id}/overview/
        """
        site = self.get_object()
        
        # Calculate health score (simplified - can be enhanced)
        pages = site.pages.all()
        total_pages = pages.count()
        
        # Calculate SEO health score based on issues
        total_issues = 0
        for page in pages:
            try:
                seo_data = page.seo_data
                if seo_data and seo_data.issues:
                    total_issues += len(seo_data.issues)
            except Exception:
                pass  # Page has no SEO data
        
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

    @action(detail=True, methods=['get'], url_path='health-summary')
    def health_summary(self, request, pk=None):
        """
        Get detailed health summary for dashboard display.
        
        GET /api/v1/sites/{id}/health-summary/
        
        Returns:
        {
            "health_score": 72,
            "health_score_delta": 8,
            "cannibalization_count": 3,
            "silo_count": 2,
            "page_count": 47,
            "missing_links_count": 12,
            "last_scan_at": "2026-02-03T10:30:00Z"
        }
        """
        site = self.get_object()
        pages = site.pages.all().prefetch_related('seo_data')
        
        # Calculate health using analysis module
        health = calculate_health_score(site)
        
        # Detect cannibalization issues
        issues = detect_cannibalization(pages)
        
        return Response({
            'health_score': health['health_score'],
            'health_score_delta': health['health_score_delta'],
            'cannibalization_count': len(issues),
            'silo_count': 0,  # TODO: Add when silos are implemented
            'page_count': pages.count(),
            'money_page_count': pages.filter(is_money_page=True).count(),
            'missing_links_count': 0,  # TODO: Add link analysis
            'last_scan_at': site.last_synced_at,
        })

    @action(detail=True, methods=['get'], url_path='cannibalization-issues')
    def cannibalization_issues(self, request, pk=None):
        """
        Get all cannibalization issues for a site.
        
        GET /api/v1/sites/{id}/cannibalization-issues/
        
        Returns:
        {
            "issues": [
                {
                    "id": "uuid",
                    "keyword": "kitchen remodeling",
                    "severity": "high",
                    "competing_pages": [...],
                    "suggested_king": {...},
                    "recommendation_type": "consolidate"
                }
            ],
            "total": 3
        }
        """
        site = self.get_object()
        pages = site.pages.all().prefetch_related('seo_data')
        
        # Detect cannibalization
        issues = detect_cannibalization(pages)
        
        # Format for API response
        formatted_issues = []
        for i, issue in enumerate(issues):
            formatted_issues.append({
                'id': i + 1,  # Simple ID for now
                'keyword': issue['keyword'],
                'severity': issue['severity'],
                'recommendation_type': issue['recommendation_type'],
                'total_impressions': issue['total_impressions'],
                'competing_pages': [
                    {
                        'id': p['id'],
                        'url': p['url'],
                        'title': p['title'],
                        'impression_share': None,
                    }
                    for p in issue['competing_pages']
                ],
                'suggested_king': {
                    'id': issue['suggested_king']['id'],
                    'url': issue['suggested_king']['url'],
                    'title': issue['suggested_king']['title'],
                } if issue['suggested_king'] else None,
            })
        
        return Response({
            'issues': formatted_issues,
            'total': len(formatted_issues),
        })

    @action(detail=True, methods=['post'])
    def analyze(self, request, pk=None):
        """
        Run full site analysis.
        
        POST /api/v1/sites/{id}/analyze/
        
        Triggers analysis of:
        - Cannibalization detection
        - Content recommendations
        - Health score calculation
        
        Returns comprehensive analysis results.
        """
        site = self.get_object()
        
        # Run full analysis
        results = analyze_site(site)
        
        return Response(results)

    @action(detail=True, methods=['get'])
    def recommendations(self, request, pk=None):
        """
        Get content and SEO recommendations for a site.
        
        GET /api/v1/sites/{id}/recommendations/
        """
        site = self.get_object()
        results = analyze_site(site)
        
        return Response({
            'recommendations': results['recommendations'],
            'total': results['recommendation_count'],
        })

    @action(detail=True, methods=['post'], url_path='trigger-sync')
    def trigger_sync(self, request, pk=None):
        """
        Trigger a sync request for a site.
        
        POST /api/v1/sites/{id}/trigger-sync/
        
        This endpoint marks the site as needing a sync.
        The WordPress plugin will pick this up on its next check.
        
        For now, returns instructions for manual sync.
        """
        site = self.get_object()
        
        # Update last sync request timestamp
        site.sync_requested_at = timezone.now()
        site.save(update_fields=['sync_requested_at'])
        
        return Response({
            'message': 'Sync requested',
            'site_id': site.id,
            'site_name': site.name,
            'instructions': 'Go to your WordPress admin → Siloq Settings → Click "Sync Now" to push pages to Siloq.',
            'sync_requested_at': site.sync_requested_at,
        })

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

    @action(detail=True, methods=['get'])
    def silos(self, request, pk=None):
        """
        Get all silos (content clusters) for a site.
        
        GET /api/v1/sites/{id}/silos/
        
        Returns:
        {
            "silos": [
                {
                    "id": 1,
                    "name": "Kitchen Remodeling",
                    "target_page": { "id": 1, "url": "...", "title": "...", "slug": "...", "status": "publish" },
                    "topic_cluster": { "id": 1, "name": "Home Renovation" } | null,
                    "supporting_pages": [...],
                    "supporting_count": 5,
                    "linked_count": 3,
                    "created_at": "2026-02-01T..."
                }
            ],
            "total": 2
        }
        
        Note: This currently auto-generates silos from money pages.
        Full silo management coming in V2.
        """
        site = self.get_object()
        pages = site.pages.all()
        money_pages = pages.filter(is_money_page=True)
        
        silos = []
        for i, money_page in enumerate(money_pages):
            # For now, create a virtual silo from each money page
            # In V2, this will come from actual Silo model
            silos.append({
                'id': money_page.id,
                'name': money_page.title or f'Silo {i + 1}',
                'target_page': {
                    'id': money_page.id,
                    'url': money_page.url,
                    'title': money_page.title,
                    'slug': money_page.slug,
                    'status': money_page.status,
                },
                'topic_cluster': None,  # V2 feature
                'supporting_pages': [],  # V2: pages linked to this money page
                'supporting_count': 0,
                'linked_count': 0,
                'created_at': money_page.created_at.isoformat() if money_page.created_at else None,
            })
        
        return Response({
            'silos': silos,
            'total': len(silos),
        })

    @action(detail=True, methods=['get'], url_path='pending-approvals')
    def pending_approvals(self, request, pk=None):
        """
        Get pending approval actions for a site.
        
        GET /api/v1/sites/{id}/pending-approvals/
        
        Returns:
        {
            "actions": [
                {
                    "id": 1,
                    "action_type": "consolidate",
                    "description": "Merge 3 pages about 'kitchen remodeling'",
                    "risk": "moderate",
                    "status": "pending",
                    "impact": "High - affects 3 pages",
                    "doctrine": "Siloq Doctrine: Consolidate competing pages...",
                    "is_destructive": false,
                    "related_issue": {...} | null,
                    "related_silo": 1 | null,
                    "created_at": "2026-02-01T...",
                    "rollback_expires_at": null
                }
            ],
            "total": 5
        }
        
        Note: This currently generates pending actions from cannibalization issues.
        Full approval workflow coming in V2.
        """
        site = self.get_object()
        pages = site.pages.all()
        
        # Generate pending actions from cannibalization issues
        issues = detect_cannibalization(pages)
        
        actions = []
        for i, issue in enumerate(issues):
            # Create a pending action for each cannibalization issue
            action_type = issue['recommendation_type'] or 'review'
            is_destructive = action_type in ['consolidate', 'redirect']
            risk = 'high' if is_destructive else 'moderate' if len(issue['competing_pages']) > 3 else 'safe'
            
            actions.append({
                'id': i + 1,
                'action_type': action_type,
                'description': f"{action_type.capitalize()} {len(issue['competing_pages'])} pages competing for '{issue['keyword']}'",
                'risk': risk,
                'status': 'pending',
                'impact': f"Affects {len(issue['competing_pages'])} pages with {issue['total_impressions']} monthly impressions",
                'doctrine': f"Siloq Doctrine: {action_type.capitalize()} pages that compete for the same keyword to consolidate ranking signals.",
                'is_destructive': is_destructive,
                'related_issue': {
                    'id': i + 1,
                    'keyword': issue['keyword'],
                    'severity': issue['severity'],
                },
                'related_silo': None,
                'created_at': timezone.now().isoformat(),
                'rollback_expires_at': None,
            })
        
        return Response({
            'actions': actions,
            'total': len(actions),
        })


class APIKeyViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing API keys.
    
    list: GET /api/v1/api-keys/ - List all API keys for user's sites (optional ?site_id= for one site)
    create: POST /api/v1/api-keys/ - Create a new API key
    retrieve: GET /api/v1/api-keys/{id}/ - Get API key details
    destroy: DELETE /api/v1/api-keys/{id}/ - Revoke API key
    """
    permission_classes = [IsAuthenticated, IsAPIKeyOwner]

    def get_queryset(self):
        """Return API keys for sites owned by the current user; optional filter by site_id."""
        qs = APIKey.objects.filter(site__user=self.request.user)
        site_id = self.request.query_params.get('site_id')
        if site_id:
            qs = qs.filter(site_id=site_id)
        return qs

    def get_serializer_class(self):
        """Use different serializer for create vs list/retrieve."""
        if self.action == 'create':
            return APIKeyCreateSerializer
        return APIKeySerializer

    def create(self, request, *args, **kwargs):
        """
        Create a new API key for a specific site (site-wise tokens).
        Each site can have multiple keys; keys are scoped to one site.
        
        POST /api/v1/api-keys/
        Body: { "name": "Production Site Key", "site_id": 1 }
        """
        site_id = request.data.get('site_id')
        if not site_id:
            return Response(
                {'error': 'site_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Verify user owns the site
        site = get_object_or_404(Site, id=site_id, user=request.user)
        
        # Generate API key
        full_key, key_prefix, key_hash = APIKey.generate_key()
        
        # Create API key record
        api_key = APIKey.objects.create(
            site=site,
            name=request.data.get('name', 'Unnamed Key'),
            key_hash=key_hash,
            key_prefix=key_prefix,
        )
        
        serializer = APIKeyCreateSerializer(api_key)
        # Add the full key to response (only shown once)
        response_data = serializer.data
        response_data['key'] = full_key
        
        return Response({
            'message': 'API key created successfully',
            'key': response_data
        }, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        """
        Revoke an API key.
        
        DELETE /api/v1/api-keys/{id}/
        """
        api_key = self.get_object()
        api_key.revoke()
        return Response(
            {'message': 'API key revoked successfully'},
            status=status.HTTP_200_OK
        )
