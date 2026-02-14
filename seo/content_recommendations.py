"""
Content Recommendations API for Content Hub.

Analyzes site structure and suggests content to create based on:
- Silo gaps (money pages with few supporting articles)
- Service coverage (primary services without dedicated pages)
- Industry best practices (common content types for business type)
"""
import uuid
import hashlib
import logging
from typing import List, Dict, Any

from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from sites.models import Site
from seo.models import Page
from seo.content_generation import generate_supporting_content

logger = logging.getLogger(__name__)


# Industry-standard content types by business type
INDUSTRY_CONTENT_TEMPLATES = {
    'local_service': [
        'FAQ: Common Questions About {service}',
        'How Much Does {service} Cost?',
        '{service} vs {alternative}: What\'s the Difference?',
        'DIY vs Professional {service}: Which is Right for You?',
        'How to Choose the Best {service} Provider',
        'Emergency {service}: What to Do',
        '{service} Checklist: What to Expect',
    ],
    'ecommerce': [
        'How to Choose the Right {product}',
        '{product} Buying Guide',
        'Top {number} {product} for {use_case}',
        '{product} Care and Maintenance Tips',
        '{product} Comparison Guide',
        'FAQ: Everything About {product}',
    ],
    'saas': [
        'Getting Started with {product}',
        '{product} vs {competitor}',
        'How to {solve_problem} with {product}',
        '{product} Pricing Guide',
        'Best Practices for {use_case}',
        '{product} FAQ',
    ],
    'content_blog': [
        'Ultimate Guide to {topic}',
        '{topic}: Everything You Need to Know',
        'Common Mistakes in {topic}',
        'How to Get Started with {topic}',
        '{topic} FAQ',
    ],
}


def _generate_rec_id(site_id: int, title: str) -> str:
    """Generate a stable recommendation ID based on site + title."""
    hash_input = f"{site_id}:{title}".encode('utf-8')
    hash_hex = hashlib.md5(hash_input).hexdigest()[:12]
    return f"rec_{hash_hex}"


def _analyze_silo_gaps(site: Site) -> List[Dict[str, Any]]:
    """
    Find money pages with few supporting pages and suggest topics.
    Returns list of recommendation dicts.
    """
    recommendations = []
    
    # Get all money pages
    money_pages = Page.objects.filter(
        site=site,
        is_money_page=True,
        status='publish'
    ).prefetch_related('supporting_pages')
    
    for money_page in money_pages:
        supporting_count = money_page.supporting_pages.filter(status='publish').count()
        
        # Determine priority
        if supporting_count == 0:
            priority = 'high'
            reason = f'No supporting content for "{money_page.title}" yet'
        elif supporting_count == 1:
            priority = 'high'
            reason = f'Only 1 supporting page for "{money_page.title}" — add more depth'
        elif supporting_count <= 3:
            priority = 'medium'
            reason = f'Only {supporting_count} supporting pages for "{money_page.title}"'
        else:
            # Skip if already has plenty of support
            continue
        
        # Extract keywords from money page title for topic suggestions
        # Simple approach: remove common words and suggest related topics
        title_words = money_page.title.lower().replace('-', ' ').split()
        service_keywords = [w for w in title_words if len(w) > 3 and w not in ['page', 'home', 'about', 'contact']]
        
        if not service_keywords:
            service_keywords = ['this topic']
        
        # Generate 2-3 suggested topics based on money page
        base_topic = ' '.join(service_keywords[:3])
        
        # Suggest complementary topics
        topic_suggestions = [
            f"Common Questions About {base_topic.title()}",
            f"How to Choose the Right {base_topic.title()}",
            f"{base_topic.title()} Cost Guide",
        ]
        
        # Add recommendations for this silo
        for idx, suggested_title in enumerate(topic_suggestions[:2]):  # Limit to 2 per silo to avoid spam
            rec_id = _generate_rec_id(site.id, suggested_title)
            recommendations.append({
                'id': rec_id,
                'title': suggested_title,
                'silo': money_page.title,
                'silo_id': money_page.id,
                'reason': reason,
                'priority': priority,
                'content_type': 'supporting_article',
                'estimated_searches': None,
            })
    
    return recommendations


def _analyze_service_coverage(site: Site) -> List[Dict[str, Any]]:
    """
    Check which primary services don't have dedicated pages.
    Returns list of recommendation dicts.
    """
    recommendations = []
    
    if not site.primary_services:
        return recommendations
    
    # Get existing page titles
    existing_pages = Page.objects.filter(site=site, status='publish')
    existing_titles = [p.title.lower() for p in existing_pages]
    existing_content = ' '.join(existing_titles)
    
    for service in site.primary_services:
        service_lower = service.lower()
        
        # Simple check: is this service mentioned in any page title?
        # This is a basic heuristic - could be improved with embeddings/semantic search
        if service_lower not in existing_content:
            rec_id = _generate_rec_id(site.id, f"Service: {service}")
            recommendations.append({
                'id': rec_id,
                'title': f"{service} - Complete Guide",
                'silo': None,
                'silo_id': None,
                'reason': f'No page found covering "{service}" (one of your primary services)',
                'priority': 'high',
                'content_type': 'money_page',
                'estimated_searches': None,
            })
    
    return recommendations


def _suggest_industry_content(site: Site) -> List[Dict[str, Any]]:
    """
    Suggest industry-standard content types based on business type.
    Returns list of recommendation dicts.
    """
    recommendations = []
    
    if not site.business_type or site.business_type == 'other':
        return recommendations
    
    templates = INDUSTRY_CONTENT_TEMPLATES.get(site.business_type, [])
    
    # Get existing page titles to avoid duplicates
    existing_pages = Page.objects.filter(site=site, status='publish')
    existing_titles = [p.title.lower() for p in existing_pages]
    
    # Fill in templates with service/product info
    services = site.primary_services[:3] if site.primary_services else ['your services']
    
    for template in templates[:4]:  # Limit to 4 suggestions
        # Fill in template with first service
        if services and services[0] != 'your services':
            suggested_title = template.format(
                service=services[0],
                product=services[0],
                alternative='alternatives',
                number='5',
                use_case='your needs',
                solve_problem='solve common problems',
                competitor='competitors',
                topic=services[0],
            )
        else:
            # Skip if no specific service to fill in
            continue
        
        # Check if similar content already exists (basic keyword match)
        if any(keyword in ' '.join(existing_titles) for keyword in suggested_title.lower().split()[:3]):
            continue
        
        rec_id = _generate_rec_id(site.id, f"Industry: {suggested_title}")
        recommendations.append({
            'id': rec_id,
            'title': suggested_title,
            'silo': None,
            'silo_id': None,
            'reason': f'Industry best practice content for {site.business_type} businesses',
            'priority': 'medium',
            'content_type': 'supporting_article',
            'estimated_searches': None,
        })
    
    return recommendations


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_content_recommendations(request, site_id):
    """
    GET /api/v1/sites/{site_id}/content-recommendations/
    
    Returns prioritized list of recommended content to create.
    
    Query params:
    - limit: Max number of recommendations (default: 10)
    - priority: Filter by priority (high/medium/low)
    """
    # Get site and verify ownership
    site = get_object_or_404(Site, id=site_id)
    
    if site.user != request.user:
        return Response(
            {'error': 'Permission denied'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    # Collect recommendations from different sources
    recommendations = []
    
    # 1. Silo gap analysis (high priority)
    recommendations.extend(_analyze_silo_gaps(site))
    
    # 2. Service coverage analysis (high priority)
    recommendations.extend(_analyze_service_coverage(site))
    
    # 3. Industry-standard content (medium priority)
    recommendations.extend(_suggest_industry_content(site))
    
    # Sort by priority
    priority_order = {'high': 0, 'medium': 1, 'low': 2}
    recommendations.sort(key=lambda x: priority_order.get(x['priority'], 3))
    
    # Apply filters
    priority_filter = request.query_params.get('priority')
    if priority_filter:
        recommendations = [r for r in recommendations if r['priority'] == priority_filter]
    
    limit = int(request.query_params.get('limit', 10))
    recommendations = recommendations[:limit]
    
    return Response({
        'recommendations': recommendations,
        'total': len(recommendations),
        'site_id': site.id,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_from_recommendation(request, site_id, rec_id):
    """
    POST /api/v1/sites/{site_id}/content-recommendations/{rec_id}/generate/
    
    Generate content for a specific recommendation using OpenAI.
    
    Body (optional):
    - custom_title: Override the suggested title
    - custom_topic: Additional context for generation
    """
    # Get site and verify ownership
    site = get_object_or_404(Site, id=site_id)
    
    if site.user != request.user:
        return Response(
            {'error': 'Permission denied'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    # Get all recommendations to find this one
    # (In production, you might want to cache or rebuild from rec_id)
    all_recommendations = []
    all_recommendations.extend(_analyze_silo_gaps(site))
    all_recommendations.extend(_analyze_service_coverage(site))
    all_recommendations.extend(_suggest_industry_content(site))
    
    recommendation = next((r for r in all_recommendations if r['id'] == rec_id), None)
    
    if not recommendation:
        return Response(
            {'error': 'Recommendation not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    
    # Get custom overrides
    custom_title = request.data.get('custom_title')
    custom_topic = request.data.get('custom_topic')
    
    title = custom_title or recommendation['title']
    topic = custom_topic or recommendation['title']
    
    # Get target page if this is for a silo
    target_page_title = ''
    target_page_url = ''
    if recommendation.get('silo_id'):
        try:
            target_page = Page.objects.get(id=recommendation['silo_id'])
            target_page_title = target_page.title
            target_page_url = target_page.url
        except Page.DoesNotExist:
            pass
    
    # Generate content
    logger.info(f"Generating content for recommendation {rec_id}: {title}")
    
    result = generate_supporting_content(
        target_page_title=target_page_title or 'General',
        target_page_url=target_page_url or site.url,
        content_type=recommendation.get('content_type', 'supporting_article'),
        topic=topic,
        business_name=site.name,
        business_type=site.business_type or '',
        service_areas=site.service_areas or [],
    )
    
    if not result.get('success'):
        return Response(
            {'error': result.get('error', 'Content generation failed')},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    
    # Return generated content with recommendation context
    return Response({
        'recommendation_id': rec_id,
        'title': result['title'],
        'content': result['content'],
        'meta_description': result['meta_description'],
        'suggested_slug': result.get('suggested_slug', ''),
        'word_count': result.get('word_count', 0),
        'silo_id': recommendation.get('silo_id'),
        'status': 'draft',
        'model_used': result.get('model_used'),
        'tokens_used': result.get('tokens_used'),
    }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def approve_content(request, site_id):
    """
    POST /api/v1/sites/{site_id}/content/approve/
    
    Approve and create a new page from generated content.
    Creates a draft page in the database and triggers WordPress webhook.
    
    Body:
    - title: Page title (required)
    - content: Page content (required)
    - silo_id: Parent silo/money page ID (optional)
    - meta_description: SEO meta description (optional)
    - slug: URL slug (optional, will be auto-generated if not provided)
    """
    # Get site and verify ownership
    site = get_object_or_404(Site, id=site_id)
    
    if site.user != request.user:
        return Response(
            {'error': 'Permission denied'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    # Validate required fields
    title = request.data.get('title')
    content = request.data.get('content')
    
    if not title or not content:
        return Response(
            {'error': 'title and content are required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    silo_id = request.data.get('silo_id')
    meta_description = request.data.get('meta_description', '')
    slug = request.data.get('slug', '')
    
    # Generate slug if not provided
    if not slug:
        slug = title.lower().replace(' ', '-').replace('?', '').replace(':', '')
        # Remove special characters
        slug = ''.join(c for c in slug if c.isalnum() or c == '-')
    
    # Get parent silo if specified
    parent_silo = None
    if silo_id:
        try:
            parent_silo = Page.objects.get(id=silo_id, site=site)
        except Page.DoesNotExist:
            return Response(
                {'error': f'Silo page with ID {silo_id} not found'},
                status=status.HTTP_404_NOT_FOUND
            )
    
    # Create the page in draft status
    # Note: wp_post_id will be set when WordPress creates the actual post
    page = Page.objects.create(
        site=site,
        title=title,
        content=content,
        slug=slug,
        url=f"{site.url}/{slug}/",  # This will be updated by WordPress
        status='draft',
        post_type='page',
        wp_post_id=0,  # Placeholder - will be updated by webhook
        parent_silo=parent_silo,
        is_money_page=False,
        yoast_description=meta_description,
    )
    
    logger.info(f"Created draft page {page.id} for site {site.id}: {title}")
    
    # TODO: Trigger WordPress webhook to create the actual draft post
    # This would typically:
    # 1. Call WordPress REST API to create a draft post
    # 2. Update the page.wp_post_id with the returned WP post ID
    # 3. Return the edit URL for the user to review in WordPress
    #
    # For now, we'll return the page data and let the WordPress plugin
    # poll for new draft pages or implement a webhook receiver
    
    return Response({
        'page_id': page.id,
        'title': page.title,
        'slug': page.slug,
        'url': page.url,
        'status': page.status,
        'silo_id': parent_silo.id if parent_silo else None,
        'message': 'Page created as draft. Sync with WordPress to publish.',
        # In production, would include:
        # 'wordpress_edit_url': f"{site.url}/wp-admin/post.php?post={page.wp_post_id}&action=edit"
    }, status=status.HTTP_201_CREATED)
