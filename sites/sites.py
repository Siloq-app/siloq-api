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

    # ─────────────────────────────────────────────────────────────────────────
    # Related Pages endpoint
    # GET /api/v1/sites/{site_id}/pages/{page_id}/related-pages/
    # ─────────────────────────────────────────────────────────────────────────
    @action(
        detail=True,
        methods=['get'],
        url_path=r'pages/(?P<page_id>[0-9]+)/related-pages',
    )
    def page_related_pages(self, request, pk=None, page_id=None):
        """
        Returns internal linking recommendations for a page.

        Response:
        {
          "should_link_to":   [ {id, wp_post_id, title, url, page_type, anchor_text, already_linked}, ... ],
          "should_link_from": [ ... ],
          "page": { id, wp_post_id, title, page_type },
          "source": "api"
        }

        page_id resolves by Django Page.id first, then wp_post_id (WP post ID).
        """
        from seo.models import Page, InternalLink
        from django.db.models import Q

        try:
            site = self.get_queryset().get(pk=pk)
        except Exception:
            return Response({'detail': 'Site not found.'}, status=status.HTTP_404_NOT_FOUND)

        page = (
            Page.objects.filter(Q(id=page_id) | Q(wp_post_id=page_id), site=site)
            .select_related('parent_silo')
            .first()
        )
        if not page:
            return Response(
                {'detail': f'Page {page_id} not found for this site.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        is_hub      = page.is_money_page
        is_homepage = page.is_homepage
        parent_silo = page.parent_silo

        all_pages = (
            Page.objects.filter(site=site, status='publish')
            .exclude(pk=page.pk)
            .select_related('parent_silo')
        )

        outbound_ids = set(
            InternalLink.objects.filter(source_page=page, target_page__site=site)
            .values_list('target_page_id', flat=True)
        )

        def _entry(p, already_linked):
            anchor = p.title
            return {
                'id':             p.id,
                'wp_post_id':     p.wp_post_id,
                'title':          p.title,
                'url':            p.url,
                'page_type':      p.page_type,
                'anchor_text':    anchor,
                'already_linked': already_linked,
            }

        should_link_to   = []
        should_link_from = []

        if is_homepage:
            for p in all_pages.filter(is_money_page=True):
                should_link_to.append(_entry(p, p.pk in outbound_ids))

        elif is_hub:
            for p in all_pages.filter(parent_silo=page):
                should_link_to.append(_entry(p, p.pk in outbound_ids))
            hp = all_pages.filter(is_homepage=True).first()
            if hp:
                hp_links = set(InternalLink.objects.filter(source_page=hp, target_page=page).values_list('target_page_id', flat=True))
                should_link_from.append(_entry(hp, bool(hp_links)))
            for p in all_pages.filter(is_money_page=True):
                p_links = set(InternalLink.objects.filter(source_page=p, target_page=page).values_list('target_page_id', flat=True))
                should_link_from.append(_entry(p, bool(p_links)))

        elif parent_silo:
            should_link_to.append(_entry(parent_silo, parent_silo.pk in outbound_ids))
            siblings = all_pages.filter(parent_silo=parent_silo)
            for p in siblings:
                should_link_to.append(_entry(p, p.pk in outbound_ids))
            hub_links = set(InternalLink.objects.filter(source_page=parent_silo, target_page=page).values_list('target_page_id', flat=True))
            should_link_from.append(_entry(parent_silo, bool(hub_links)))
            for p in siblings:
                p_links = set(InternalLink.objects.filter(source_page=p, target_page=page).values_list('target_page_id', flat=True))
                should_link_from.append(_entry(p, bool(p_links)))

        else:
            for p in all_pages.filter(is_money_page=True):
                should_link_to.append(_entry(p, p.pk in outbound_ids))

        should_link_to.sort(   key=lambda x: (x['already_linked'], x['title']))
        should_link_from.sort( key=lambda x: (x['already_linked'], x['title']))

        return Response({
            'should_link_to':   should_link_to[:20],
            'should_link_from': should_link_from[:20],
            'page': {
                'id':         page.id,
                'wp_post_id': page.wp_post_id,
                'title':      page.title,
                'page_type':  page.page_type,
            },
            'source': 'api',
        })
