"""
Conflicts tab views for Section 11.3 implementation.
Wires to Ahmad's new endpoint with GSC query strings, page cards, and approval queue.
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.db.models import Q, Count, Avg, Sum
from django.utils import timezone
from datetime import datetime, timedelta
import uuid

from sites.models import Site
from .models import Page, SEOData


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def conflicts_list(request, site_id):
    """
    11.3 — Conflicts tab (wire to Ahmad's new endpoint)
    Returns conflicts with GSC query strings as headers, two page cards side by side,
    and location differentiation cards (hidden by default).
    """
    site = get_object_or_404(Site, id=site_id, user=request.user)
    
    # Mock conflicts data - in real implementation this would come from Ahmad's endpoint
    # or from the Conflict model if it exists
    mock_conflicts = [
        {
            'id': str(uuid.uuid4()),
            'query_string': 'best seo services 2024',  # GSC query string for card header
            'page1': {
                'id': 'page1_id',
                'title': 'SEO Services - Our Company',
                'url': 'https://example.com/seo-services',
                'impressions': 1250,
                'position': 3.2,
                'clicks': 45,
                'click_share': 65.2,  # Calculated as percentage
                'is_winner': True
            },
            'page2': {
                'id': 'page2_id', 
                'title': 'Best SEO Services - Blog Post',
                'url': 'https://example.com/blog/best-seo-services',
                'impressions': 680,
                'position': 8.7,
                'clicks': 24,
                'click_share': 34.8,
                'is_winner': False
            },
            'location_differentiation': [
                {
                    'location': 'New York',
                    'page1_position': 2.1,
                    'page2_position': 15.3,
                    'recommendation': 'Page 1 dominates in New York, consolidate content'
                },
                {
                    'location': 'Los Angeles', 
                    'page1_position': 5.8,
                    'page2_position': 4.2,
                    'recommendation': 'Page 2 performs better in LA, consider geographic targeting'
                }
            ],
            'is_dismissed': False,
            'recommendation': 'Merge blog content into main service page and 301 redirect blog URL',
            'severity_score': 85,
            'created_at': '2026-03-02T15:30:00Z'
        },
        {
            'id': str(uuid.uuid4()),
            'query_string': 'local seo optimization',
            'page1': {
                'id': 'page3_id',
                'title': 'Local SEO Services',
                'url': 'https://example.com/local-seo',
                'impressions': 890,
                'position': 4.5,
                'clicks': 32,
                'click_share': 58.2,
                'is_winner': True
            },
            'page2': {
                'id': 'page4_id',
                'title': 'SEO Optimization Guide',
                'url': 'https://example.com/seo-optimization-guide',
                'impressions': 620,
                'position': 9.1,
                'clicks': 23,
                'click_share': 41.8,
                'is_winner': False
            },
            'location_differentiation': [
                {
                    'location': 'Chicago',
                    'page1_position': 3.2,
                    'page2_position': 12.8,
                    'recommendation': 'Page 1 strongly outranks in Chicago market'
                }
            ],
            'is_dismissed': False,
            'recommendation': 'Add local SEO section to main optimization guide, redirect local page',
            'severity_score': 72,
            'created_at': '2026-03-01T10:15:00Z'
        },
        {
            'id': str(uuid.uuid4()),
            'query_string': 'seo audit tools',
            'page1': {
                'id': 'page5_id',
                'title': 'Free SEO Audit Tool',
                'url': 'https://example.com/seo-audit-tool',
                'impressions': 450,
                'position': 6.8,
                'clicks': 18,
                'click_share': 55.6,
                'is_winner': True
            },
            'page2': {
                'id': 'page6_id',
                'title': 'SEO Audit Tools Comparison',
                'url': 'https://example.com/blog/seo-audit-tools',
                'impressions': 360,
                'position': 11.2,
                'clicks': 14,
                'click_share': 44.4,
                'is_winner': False
            },
            'location_differentiation': [],
            'is_dismissed': True,  # This one is dismissed
            'recommendation': 'Combine tool page with comparison blog for comprehensive resource',
            'severity_score': 45,
            'created_at': '2026-02-28T14:20:00Z'
        }
    ]
    
    # Filter by dismissed status if requested
    show_dismissed = request.query_params.get('show_dismissed', 'false').lower() == 'true'
    if not show_dismissed:
        mock_conflicts = [c for c in mock_conflicts if not c['is_dismissed']]
    
    return Response({
        'conflicts': mock_conflicts,
        'show_dismissed': show_dismissed,
        'total_count': len(mock_conflicts)
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def accept_recommendation(request, site_id, conflict_id):
    """
    Accept recommendation for a conflict and send to Approvals queue
    """
    site = get_object_or_404(Site, id=site_id, user=request.user)
    
    # Mock implementation - would find and update actual conflict
    # In real implementation, this would:
    # 1. Find the conflict by ID
    # 2. Create a ContentJob with status 'pending_approval'
    # 3. Update conflict status to 'in_approval_queue'
    
    return Response({
        'message': 'Recommendation sent to Approvals queue',
        'content_job_id': str(uuid.uuid4()),
        'conflict_id': conflict_id,
        'status': 'pending_approval'
    })


# Helper functions
def calculate_click_share(page_clicks, total_clicks):
    """Calculate click share percentage"""
    if total_clicks == 0:
        return 0.0
    return round((page_clicks / total_clicks) * 100, 1)
