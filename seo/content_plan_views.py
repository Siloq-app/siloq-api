"""
Content Plan tab implementation for Section 11.5.
Position: between Pages and Performance in nav
Tab badge: count of money pages with <2 supporting articles
Default Gaps view: money page cards, supporting article count, 3 topic suggestions with "Add to Pipeline"
Backend: GET /api/v1/sites/{id}/pages/{id}/supporting-content/ (already live from PR #74)
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.db.models import Q, Count, Avg, Sum
from django.utils import timezone
from datetime import datetime, timedelta
import uuid
import logging

from sites.models import Site
from .models import Page, SEOData, ContentJob

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def content_plan(request, site_id):
    """
    11.5 — Content Plan tab (new tab)
    
    Returns money pages with supporting content gaps and topic suggestions.
    
    Features:
    • Tab badge: count of money pages with <2 supporting articles
    • Default Gaps view: money page cards, supporting article count, 3 topic suggestions
    • "Add to Pipeline" functionality for topic suggestions
    • Backend integration with supporting-content endpoint from PR #74
    """
    site = get_object_or_404(Site, id=site_id, user=request.user)
    
    # Get filter parameters
    view_type = request.query_params.get('view', 'gaps')  # gaps, pipeline, all
    min_supporting = int(request.query_params.get('min_supporting', 2))
    limit = int(request.query_params.get('limit', 50))
    
    # Get all money pages for the site
    money_pages = Page.objects.filter(
        site=site,
        is_money_page=True,
        is_noindex=False
    ).select_related('seo_data').order_by('-created_at')
    
    # Count money pages with <2 supporting articles (for tab badge)
    pages_with_gaps = money_pages.filter(
        Q(related_pages__count__lt=min_supporting) | Q(related_pages__isnull=True)
    ).distinct()
    
    # Calculate supporting content counts for each money page
    content_plan_data = []
    for page in money_pages:
        # Get supporting pages count (using related_pages relationship)
        supporting_count = page.related_pages.count()
        
        # Determine if page has content gaps
        has_gaps = supporting_count < min_supporting
        
        # Skip pages without gaps if in gaps view
        if view_type == 'gaps' and not has_gaps:
            continue
        
        # Generate topic suggestions based on page analysis
        topic_suggestions = generate_topic_suggestions(page, supporting_count)
        
        # Get SEO metrics
        seo_score = page.seo_data.seo_score if page.seo_data else 0
        word_count = page.seo_data.word_count if page.seo_data else 0
        
        content_plan_data.append({
            'id': str(page.id),
            'title': page.title,
            'url': page.url,
            'wp_post_id': page.wp_post_id,
            'supporting_articles_count': supporting_count,
            'has_gaps': has_gaps,
            'seo_score': seo_score,
            'word_count': word_count,
            'last_updated': page.updated_at,
            'topic_suggestions': topic_suggestions,
            'content_gap_score': calculate_content_gap_score(page, supporting_count),
            'priority': determine_priority(page, supporting_count, seo_score)
        })
    
    # Sort by priority and content gap score
    content_plan_data.sort(key=lambda x: (x['priority'], x['content_gap_score']), reverse=True)
    
    # Apply limit
    if limit:
        content_plan_data = content_plan_data[:limit]
    
    return Response({
        'content_plan': content_plan_data,
        'view_type': view_type,
        'tab_badge_count': pages_with_gaps.count(),
        'total_money_pages': money_pages.count(),
        'pages_with_gaps': pages_with_gaps.count(),
        'min_supporting_threshold': min_supporting,
        'site_info': {
            'id': site.id,
            'name': site.name,
            'url': site.url
        }
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def supporting_content(request, site_id, page_id):
    """
    GET /api/v1/sites/{id}/pages/{id}/supporting-content/
    
    Already live from PR #74 - returns detailed supporting content analysis for a specific money page.
    """
    site = get_object_or_404(Site, id=site_id, user=request.user)
    page = get_object_or_404(Page, id=page_id, site=site, is_money_page=True)
    
    # Get supporting pages
    supporting_pages = page.related_pages.all().select_related('seo_data')
    
    # Analyze supporting content
    supporting_analysis = []
    for supporting_page in supporting_pages:
        seo_score = supporting_page.seo_data.seo_score if supporting_page.seo_data else 0
        word_count = supporting_page.seo_data.word_count if supporting_page.seo_data else 0
        
        supporting_analysis.append({
            'id': str(supporting_page.id),
            'title': supporting_page.title,
            'url': supporting_page.url,
            'wp_post_id': supporting_page.wp_post_id,
            'seo_score': seo_score,
            'word_count': word_count,
            'last_updated': supporting_page.updated_at,
            'content_quality': assess_content_quality(supporting_page),
            'relevance_score': calculate_relevance_score(page, supporting_page)
        })
    
    # Generate additional topic suggestions based on gaps
    gap_analysis = analyze_content_gaps(page, supporting_pages)
    
    return Response({
        'money_page': {
            'id': str(page.id),
            'title': page.title,
            'url': page.url,
            'wp_post_id': page.wp_post_id,
            'seo_score': page.seo_data.seo_score if page.seo_data else 0,
            'word_count': page.seo_data.word_count if page.seo_data else 0
        },
        'supporting_pages': supporting_analysis,
        'supporting_count': len(supporting_pages),
        'gap_analysis': gap_analysis,
        'recommended_topics': generate_topic_suggestions(page, len(supporting_pages)),
        'content_health_score': calculate_content_health_score(page, supporting_pages)
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_to_pipeline(request, site_id, page_id):
    """
    Add a topic suggestion to the content pipeline.
    
    POST /api/v1/sites/{id}/pages/{id}/add-to-pipeline/
    Body: { "topic": "...", "recommendation": "...", "priority": "medium" }
    """
    site = get_object_or_404(Site, id=site_id, user=request.user)
    page = get_object_or_404(Page, id=page_id, site=site, is_money_page=True)
    
    topic = request.data.get('topic')
    recommendation = request.data.get('recommendation', '')
    priority = request.data.get('priority', 'medium')
    
    if not topic:
        return Response({
            'error': 'Topic is required'
        }, status=400)
    
    # Create content job for the pipeline
    content_job = ContentJob.objects.create(
        site=site,
        page=page,
        target_page=page,
        job_type='supporting_content',
        topic=topic,
        recommendation=recommendation,
        status='pending',
        priority=priority,
        created_by=request.user
    )
    
    logger.info(f"Topic '{topic}' added to pipeline for page {page.id} by user {request.user.id}")
    
    return Response({
        'message': 'Topic added to pipeline',
        'content_job_id': str(content_job.id),
        'topic': topic,
        'priority': priority,
        'status': 'pending',
        'estimated_completion': '3-5 business days'
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def content_pipeline(request, site_id):
    """
    Get all content jobs in the pipeline for this site.
    
    GET /api/v1/sites/{id}/content-pipeline/
    """
    site = get_object_or_404(Site, id=site_id, user=request.user)
    
    # Get content jobs for this site
    content_jobs = ContentJob.objects.filter(
        site=site,
        job_type='supporting_content'
    ).select_related('page', 'target_page', 'created_by').order_by('-created_at')
    
    pipeline_data = []
    for job in content_jobs:
        pipeline_data.append({
            'id': str(job.id),
            'topic': job.topic,
            'recommendation': job.recommendation,
            'status': job.status,
            'priority': job.priority,
            'target_page': {
                'id': str(job.target_page.id) if job.target_page else None,
                'title': job.target_page.title if job.target_page else None,
                'url': job.target_page.url if job.target_page else None
            },
            'created_at': job.created_at,
            'created_by': job.created_by.username if job.created_by else None,
            'estimated_word_count': job.estimated_word_count,
            'actual_word_count': job.actual_word_count
        })
    
    return Response({
        'pipeline': pipeline_data,
        'total_jobs': len(pipeline_data),
        'status_breakdown': get_status_breakdown(content_jobs),
        'site_info': {
            'id': site.id,
            'name': site.name,
            'url': site.url
        }
    })


# Helper functions for content plan analysis

def generate_topic_suggestions(page, supporting_count):
    """
    Generate 3 topic suggestions for a money page based on content gaps and analysis.
    """
    base_topic = extract_base_topic(page.title, page.content)
    
    suggestions = []
    
    # Suggestion 1: FAQ-style content
    if supporting_count < 1:
        suggestions.append({
            'id': str(uuid.uuid4()),
            'topic': f"{base_topic} FAQ: Common Questions Answered",
            'recommendation': "Create comprehensive FAQ content that addresses common user questions and concerns about this topic.",
            'type': 'faq',
            'estimated_word_count': 1200,
            'priority': 'high'
        })
    
    # Suggestion 2: How-to guide
    if supporting_count < 2:
        suggestions.append({
            'id': str(uuid.uuid4()),
            'topic': f"How to {base_topic.lower()}: Complete Guide",
            'recommendation': "Develop a step-by-step guide that walks users through the process or implementation.",
            'type': 'how_to',
            'estimated_word_count': 2000,
            'priority': 'high'
        })
    
    # Suggestion 3: Case study or examples
    suggestions.append({
        'id': str(uuid.uuid4()),
        'topic': f"{base_topic} Case Studies and Real Examples",
        'recommendation': "Showcase real-world examples, case studies, and success stories to build trust and authority.",
        'type': 'case_study',
        'estimated_word_count': 1500,
        'priority': 'medium'
    })
    
    return suggestions[:3]  # Return exactly 3 suggestions


def calculate_content_gap_score(page, supporting_count):
    """
    Calculate a content gap score (0-100) based on supporting content analysis.
    """
    # Base score starts at 100 and decreases with more supporting content
    base_score = 100
    
    # Deduction for each supporting article
    deduction = supporting_count * 20
    
    # SEO score factor
    seo_factor = (100 - (page.seo_data.seo_score if page.seo_data else 0)) * 0.3
    
    # Word count factor (under 1000 words needs more support)
    word_count = page.seo_data.word_count if page.seo_data else 0
    word_factor = max(0, (1000 - word_count) * 0.05) if word_count < 1000 else 0
    
    gap_score = max(0, base_score - deduction + seo_factor + word_factor)
    return min(100, gap_score)


def determine_priority(page, supporting_count, seo_score):
    """
    Determine priority level for content creation.
    """
    if supporting_count == 0 and seo_score < 70:
        return 'high'
    elif supporting_count < 2 and seo_score < 80:
        return 'medium'
    else:
        return 'low'


def extract_base_topic(title, content):
    """
    Extract the base topic from page title and content.
    """
    # Simple extraction - in real implementation, this would use NLP
    words = title.split()
    if len(words) > 3:
        return ' '.join(words[:3])
    return title


def assess_content_quality(page):
    """
    Assess the quality of supporting content.
    """
    seo_score = page.seo_data.seo_score if page.seo_data else 0
    word_count = page.seo_data.word_count if page.seo_data else 0
    
    if seo_score >= 80 and word_count >= 1000:
        return 'excellent'
    elif seo_score >= 70 and word_count >= 800:
        return 'good'
    elif seo_score >= 60 and word_count >= 600:
        return 'fair'
    else:
        return 'poor'


def calculate_relevance_score(money_page, supporting_page):
    """
    Calculate how relevant supporting content is to the money page.
    """
    # Simple relevance calculation based on title similarity
    money_words = set(money_page.title.lower().split())
    supporting_words = set(supporting_page.title.lower().split())
    
    if not money_words or not supporting_words:
        return 50  # Default relevance
    
    common_words = money_words.intersection(supporting_words)
    relevance = (len(common_words) / max(len(money_words), len(supporting_words))) * 100
    
    return min(100, max(0, relevance))


def analyze_content_gaps(page, supporting_pages):
    """
    Analyze content gaps for a money page.
    """
    gaps = []
    
    # Check for FAQ content
    has_faq = any('faq' in sp.title.lower() or 'question' in sp.title.lower() for sp in supporting_pages)
    if not has_faq:
        gaps.append({
            'type': 'faq',
            'description': 'Missing FAQ content to address common user questions',
            'priority': 'high'
        })
    
    # Check for how-to content
    has_how_to = any('how to' in sp.title.lower() or 'guide' in sp.title.lower() for sp in supporting_pages)
    if not has_how_to:
        gaps.append({
            'type': 'how_to',
            'description': 'Missing how-to guides for step-by-step instructions',
            'priority': 'high'
        })
    
    # Check for case studies
    has_case_study = any('case study' in sp.title.lower() or 'example' in sp.title.lower() for sp in supporting_pages)
    if not has_case_study:
        gaps.append({
            'type': 'case_study',
            'description': 'Missing case studies and real-world examples',
            'priority': 'medium'
        })
    
    return gaps


def calculate_content_health_score(page, supporting_pages):
    """
    Calculate overall content health score for a money page.
    """
    if not supporting_pages:
        return 25  # Very low health with no supporting content
    
    # Factors: number of supporting pages, average quality, diversity
    count_score = min(50, len(supporting_pages) * 10)
    
    avg_seo_score = sum(
        sp.seo_data.seo_score if sp.seo_data else 0 
        for sp in supporting_pages
    ) / len(supporting_pages)
    quality_score = avg_seo_score * 0.3
    
    # Diversity bonus for different content types
    content_types = set()
    for sp in supporting_pages:
        title_lower = sp.title.lower()
        if 'faq' in title_lower or 'question' in title_lower:
            content_types.add('faq')
        elif 'how to' in title_lower or 'guide' in title_lower:
            content_types.add('how_to')
        elif 'case study' in title_lower or 'example' in title_lower:
            content_types.add('case_study')
    
    diversity_score = len(content_types) * 10
    
    total_score = count_score + quality_score + diversity_score
    return min(100, max(0, total_score))


def get_status_breakdown(content_jobs):
    """
    Get breakdown of content jobs by status.
    """
    breakdown = {
        'pending': 0,
        'pending_approval': 0,
        'approved': 0,
        'in_progress': 0,
        'completed': 0,
        'failed': 0
    }
    
    for job in content_jobs:
        breakdown[job.status] = breakdown.get(job.status, 0) + 1
    
    return breakdown
