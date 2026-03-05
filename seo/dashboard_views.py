"""
Dashboard Home implementation for Section 11.2.
3 columns: Fix Now | In Progress | Done This Month
GSC metrics move to Performance tab
Fix Now: top 3-5 actionable items from conflicts + page issues + content gaps
In Progress: approved items pending WP push (with live status)
Done This Month: resolved items with month-over-month count
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.db.models import Q, Count, Avg, Sum, Max, Min
from django.utils import timezone
from datetime import datetime, timedelta
import uuid
import logging

from sites.models import Site
from .models import Page, SEOData, Conflict, ContentJob

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_home(request, site_id):
    """
    11.2 — Dashboard Home
    
    3-column layout with actionable items:
    • Fix Now: top 3-5 actionable items from conflicts + page issues + content gaps
    • In Progress: approved items pending WP push (with live status)
    • Done This Month: resolved items with month-over-month count
    
    GSC metrics moved to Performance tab (not included here).
    """
    site = get_object_or_404(Site, id=site_id, user=request.user)
    
    # Get current date and month boundaries
    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month_start = (month_start - timedelta(days=1)).replace(day=1)
    
    # Get limit parameter (default 5 items per column)
    limit = int(request.query_params.get('limit', 5))
    
    # Build dashboard data
    dashboard_data = {
        'fix_now': get_fix_now_items(site, limit),
        'in_progress': get_in_progress_items(site, limit),
        'done_this_month': get_done_this_month_items(site, month_start, limit),
        'summary': get_dashboard_summary(site, month_start, last_month_start),
        'site_info': {
            'id': site.id,
            'name': site.name,
            'url': site.url
        },
        'generated_at': now
    }
    
    return Response(dashboard_data)


def get_fix_now_items(site, limit):
    """
    Get top 3-5 actionable items from conflicts + page issues + content gaps.
    Prioritized by severity and impact.
    """
    fix_now_items = []
    
    # 1. High severity conflicts (priority: critical)
    high_severity_conflicts = Conflict.objects.filter(
        Q(page1__site=site) | Q(page2__site=site),
        status='active',
        is_dismissed=False,
        severity_score__gte=80
    ).select_related('page1', 'page2').order_by('-severity_score')[:2]
    
    for conflict in high_severity_conflicts:
        fix_now_items.append({
            'id': str(conflict.id),
            'type': 'conflict',
            'priority': 'critical',
            'title': f"Resolve: {conflict.query_string}",
            'description': f"Keyword cannibalization between '{conflict.page1.title}' and '{conflict.page2.title}'",
            'action_text': 'Accept Recommendation',
            'action_url': f'/api/v1/sites/{site.id}/conflicts/{conflict.id}/accept/',
            'severity_score': conflict.severity_score,
            'estimated_impact': 'high',
            'time_to_resolve': '2-3 hours',
            'page1': {
                'id': conflict.page1.id,
                'title': conflict.page1.title,
                'url': conflict.page1.url
            },
            'page2': {
                'id': conflict.page2.id,
                'title': conflict.page2.title,
                'url': conflict.page2.url
            }
        })
    
    # 2. Critical page issues (priority: high)
    critical_pages = Page.objects.filter(
        site=site,
        is_noindex=False,
        seo_data__seo_score__lt=50
    ).select_related('seo_data').order_by('seo_data__seo_score')[:2]
    
    for page in critical_pages:
        issues = page.seo_data.issues if page.seo_data else []
        critical_issue = next((issue for issue in issues if issue.get('severity') == 'high'), None)
        
        fix_now_items.append({
            'id': str(page.id),
            'type': 'page_issue',
            'priority': 'high',
            'title': f"Fix SEO Issues: {page.title}",
            'description': critical_issue.get('message', 'Multiple SEO issues need attention') if critical_issue else 'Improve overall SEO score',
            'action_text': 'View Issues',
            'action_url': f'/api/v1/pages/{page.id}/seo/',
            'seo_score': page.seo_data.seo_score if page.seo_data else 0,
            'estimated_impact': 'medium',
            'time_to_resolve': '1-2 hours',
            'page': {
                'id': page.id,
                'title': page.title,
                'url': page.url
            }
        })
    
    # 3. Content gaps for money pages (priority: medium)
    money_pages_with_gaps = Page.objects.filter(
        site=site,
        is_money_page=True,
        is_noindex=False
    ).annotate(
        supporting_count=Count('related_pages')
    ).filter(supporting_count__lt=2).order_by('supporting_count')[:1]
    
    for page in money_pages_with_gaps:
        fix_now_items.append({
            'id': str(page.id),
            'type': 'content_gap',
            'priority': 'medium',
            'title': f"Add Supporting Content: {page.title}",
            'description': f"Money page has only {page.supporting_count} supporting articles (need 2+)",
            'action_text': 'View Content Plan',
            'action_url': f'/api/v1/sites/{site.id}/content-plan/',
            'supporting_count': page.supporting_count,
            'estimated_impact': 'medium',
            'time_to_resolve': '4-6 hours',
            'page': {
                'id': page.id,
                'title': page.title,
                'url': page.url
            }
        })
    
    # Sort by priority and limit results
    priority_order = {'critical': 0, 'high': 1, 'medium': 2}
    fix_now_items.sort(key=lambda x: priority_order.get(x['priority'], 3))
    
    return fix_now_items[:limit]


def get_in_progress_items(site, limit):
    """
    Get approved items pending WP push with live status.
    """
    in_progress_items = []
    
    # Approved content jobs pending WordPress push
    approved_jobs = ContentJob.objects.filter(
        site=site,
        status='approved',
        job_type__in=['conflict_resolution', 'supporting_content', 'money_page_optimization']
    ).select_related('page', 'target_page', 'created_by', 'approved_by').order_by('-approved_at')[:limit]
    
    for job in approved_jobs:
        # Determine WordPress push status
        wp_status = get_wordpress_push_status(job)
        
        in_progress_items.append({
            'id': str(job.id),
            'type': 'content_job',
            'title': job.topic or job.recommendation[:50],
            'description': job.recommendation,
            'job_type': job.job_type,
            'wp_status': wp_status,
            'live_status': get_live_status(wp_status),
            'approved_at': job.approved_at,
            'approved_by': job.approved_by.username if job.approved_by else None,
            'estimated_completion': get_estimated_completion(job),
            'target_page': {
                'id': job.target_page.id if job.target_page else None,
                'title': job.target_page.title if job.target_page else None,
                'url': job.target_page.url if job.target_page else None
            } if job.target_page else None,
            'progress_percentage': get_progress_percentage(job, wp_status)
        })
    
    # In-progress conflicts (in approval queue)
    conflicts_in_queue = Conflict.objects.filter(
        Q(page1__site=site) | Q(page2__site=site),
        status='in_approval_queue'
    ).select_related('page1', 'page2').order_by('-updated_at')[:max(1, limit - len(approved_jobs))]
    
    for conflict in conflicts_in_queue:
        # Find associated content job
        associated_job = ContentJob.objects.filter(
            site=site,
            conflict=conflict,
            status='pending_approval'
        ).first()
        
        in_progress_items.append({
            'id': str(conflict.id),
            'type': 'conflict_resolution',
            'title': f"Resolve: {conflict.query_string}",
            'description': f"Content job created for conflict resolution",
            'wp_status': 'pending_approval',
            'live_status': 'waiting_approval',
            'created_at': conflict.updated_at,
            'content_job_id': str(associated_job.id) if associated_job else None,
            'severity_score': conflict.severity_score,
            'progress_percentage': 25  # Early stage
        })
    
    return in_progress_items[:limit]


def get_done_this_month_items(site, month_start, limit):
    """
    Get resolved items with month-over-month count.
    """
    done_items = []
    
    # Resolved conflicts this month
    resolved_conflicts = Conflict.objects.filter(
        Q(page1__site=site) | Q(page2__site=site),
        status='resolved',
        resolved_at__gte=month_start
    ).select_related('page1', 'page2').order_by('-resolved_at')[:limit]
    
    for conflict in resolved_conflicts:
        done_items.append({
            'id': str(conflict.id),
            'type': 'conflict_resolved',
            'title': f"Resolved: {conflict.query_string}",
            'description': f"Conflict between '{conflict.page1.title}' and '{conflict.page2.title}' resolved",
            'resolved_at': conflict.resolved_at,
            'resolution_type': 'conflict_resolution',
            'impact': 'eliminated_keyword cannibalization',
            'severity_score': conflict.severity_score,
            'winner_page': {
                'id': conflict.winner_page.id if conflict.winner_page else None,
                'title': conflict.winner_page.title if conflict.winner_page else None
            } if conflict.winner_page else None
        })
    
    # Completed content jobs this month
    completed_jobs = ContentJob.objects.filter(
        site=site,
        status='completed',
        completed_at__gte=month_start,
        job_type__in=['conflict_resolution', 'supporting_content', 'money_page_optimization']
    ).select_related('page', 'target_page').order_by('-completed_at')[:max(1, limit - len(resolved_conflicts))]
    
    for job in completed_jobs:
        done_items.append({
            'id': str(job.id),
            'type': 'content_completed',
            'title': job.topic or job.recommendation[:50],
            'description': job.recommendation,
            'completed_at': job.completed_at,
            'resolution_type': job.job_type,
            'impact': get_job_impact_description(job),
            'word_count': job.actual_word_count,
            'target_page': {
                'id': job.target_page.id if job.target_page else None,
                'title': job.target_page.title if job.target_page else None,
                'url': job.target_page.url if job.target_page else None
            } if job.target_page else None
        })
    
    # Sort by completion date (most recent first)
    done_items.sort(key=lambda x: x['completed_at'], reverse=True)
    
    return done_items[:limit]


def get_dashboard_summary(site, month_start, last_month_start):
    """
    Get summary statistics for the dashboard.
    """
    # Current month counts
    current_month_conflicts = Conflict.objects.filter(
        Q(page1__site=site) | Q(page2__site=site),
        status='resolved',
        resolved_at__gte=month_start
    ).count()
    
    current_month_jobs = ContentJob.objects.filter(
        site=site,
        status='completed',
        completed_at__gte=month_start
    ).count()
    
    # Last month counts
    last_month_conflicts = Conflict.objects.filter(
        Q(page1__site=site) | Q(page2__site=site),
        status='resolved',
        resolved_at__gte=last_month_start,
        resolved_at__lt=month_start
    ).count()
    
    last_month_jobs = ContentJob.objects.filter(
        site=site,
        status='completed',
        completed_at__gte=last_month_start,
        completed_at__lt=month_start
    ).count()
    
    # Active counts
    active_conflicts = Conflict.objects.filter(
        Q(page1__site=site) | Q(page2__site=site),
        status='active',
        is_dismissed=False
    ).count()
    
    in_progress_jobs = ContentJob.objects.filter(
        site=site,
        status__in=['approved', 'in_progress']
    ).count()
    
    # Money pages with gaps
    money_pages_with_gaps = Page.objects.filter(
        site=site,
        is_money_page=True,
        is_noindex=False
    ).annotate(
        supporting_count=Count('related_pages')
    ).filter(supporting_count__lt=2).count()
    
    return {
        'current_month': {
            'conflicts_resolved': current_month_conflicts,
            'content_completed': current_month_jobs,
            'total_completed': current_month_conflicts + current_month_jobs
        },
        'last_month': {
            'conflicts_resolved': last_month_conflicts,
            'content_completed': last_month_jobs,
            'total_completed': last_month_conflicts + last_month_jobs
        },
        'month_over_month_change': {
            'conflicts_resolved': calculate_change(last_month_conflicts, current_month_conflicts),
            'content_completed': calculate_change(last_month_jobs, current_month_jobs),
            'total_completed': calculate_change(last_month_conflicts + last_month_jobs, current_month_conflicts + current_month_jobs)
        },
        'active_items': {
            'conflicts_active': active_conflicts,
            'jobs_in_progress': in_progress_jobs,
            'money_pages_with_gaps': money_pages_with_gaps
        }
    }


# Helper functions

def get_wordpress_push_status(job):
    """
    Determine WordPress push status for a content job.
    """
    if job.wp_post_id and job.wp_status == 'publish':
        return 'published'
    elif job.wp_post_id and job.wp_status == 'draft':
        return 'draft'
    elif job.wp_post_id:
        return 'pushed'
    else:
        return 'pending_push'


def get_live_status(wp_status):
    """
    Get user-friendly live status.
    """
    status_map = {
        'published': 'live',
        'draft': 'draft',
        'pushed': 'pushed_to_wp',
        'pending_push': 'pending_push',
        'pending_approval': 'waiting_approval'
    }
    return status_map.get(wp_status, 'unknown')


def get_estimated_completion(job):
    """
    Get estimated completion time for a job.
    """
    if job.wp_post_id:
        return 'Completed'
    elif job.status == 'approved':
        return '2-4 hours'
    else:
        return '1-2 days'


def get_progress_percentage(job, wp_status):
    """
    Calculate progress percentage for a job.
    """
    if wp_status == 'published':
        return 100
    elif wp_status == 'draft':
        return 90
    elif wp_status == 'pushed':
        return 80
    elif job.status == 'approved':
        return 50
    elif job.status == 'in_progress':
        return 30
    else:
        return 10


def get_job_impact_description(job):
    """
    Get impact description for a completed job.
    """
    if job.job_type == 'conflict_resolution':
        return 'resolved keyword cannibalization'
    elif job.job_type == 'supporting_content':
        return 'added supporting content for money page'
    elif job.job_type == 'money_page_optimization':
        return 'optimized money page performance'
    else:
        return 'completed content task'


def calculate_change(previous, current):
    """
    Calculate percentage change between two values.
    """
    if previous == 0:
        return 100 if current > 0 else 0
    return round(((current - previous) / previous) * 100, 1)
