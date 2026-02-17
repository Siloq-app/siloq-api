"""
API endpoints for AI-powered conflict differentiation.
Generates unique title/meta/keyword recommendations for competing pages.
"""
import json
import logging
import os
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
import openai

from sites.models import Site
from seo.models import Page

logger = logging.getLogger(__name__)


def _get_site_or_error(request, site_id):
    """Validate site ownership."""
    site = get_object_or_404(Site, id=site_id)
    if site.user != request.user:
        return None, Response({
            'error': {'code': 'FORBIDDEN', 'message': 'Permission denied.', 'detail': None, 'status': 403}
        }, status=status.HTTP_403_FORBIDDEN)
    return site, None


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def differentiate_conflict(request, site_id):
    """
    Use AI to generate differentiation recommendations for competing pages.
    
    POST /api/v1/sites/{site_id}/conflicts/differentiate/
    
    Body:
    - pages: list of {url, title, page_type} for the competing pages
    - keyword: str (the shared keyword causing the conflict)
    - conflict_type: str (e.g., "title_keyword_overlap")
    """
    site, err = _get_site_or_error(request, site_id)
    if err:
        return err

    data = request.data
    pages_data = data.get('pages', [])
    keyword = data.get('keyword', '')
    conflict_type = data.get('conflict_type', '')

    if not pages_data:
        return Response({
            'error': {'code': 'MISSING_PAGES', 'message': 'pages array is required', 'detail': None, 'status': 400}
        }, status=status.HTTP_400_BAD_REQUEST)

    if not keyword:
        return Response({
            'error': {'code': 'MISSING_KEYWORD', 'message': 'keyword is required', 'detail': None, 'status': 400}
        }, status=status.HTTP_400_BAD_REQUEST)

    # Fetch page details from DB
    enriched_pages = []
    for pg in pages_data:
        url = pg.get('url')
        try:
            page = Page.objects.filter(site=site, url=url).first()
            if page:
                enriched_pages.append({
                    'url': url,
                    'title': page.title,
                    'page_type': pg.get('page_type') or page.page_type_classification,
                    'meta_description': page.yoast_description or '',
                    'h1': page.title,  # Approximate (we don't store H1 separately yet)
                    'excerpt': page.excerpt[:500] if page.excerpt else page.content[:500] if page.content else '',
                    'page_id': page.id,
                })
            else:
                # Page not in DB yet, use what we have
                enriched_pages.append({
                    'url': url,
                    'title': pg.get('title', url),
                    'page_type': pg.get('page_type', 'supporting'),
                    'meta_description': '',
                    'h1': '',
                    'excerpt': '',
                    'page_id': None,
                })
        except Exception as e:
            logger.warning(f"Could not fetch page details for {url}: {e}")
            enriched_pages.append({
                'url': url,
                'title': pg.get('title', url),
                'page_type': pg.get('page_type', 'supporting'),
                'meta_description': '',
                'h1': '',
                'excerpt': '',
                'page_id': None,
            })

    # Build AI prompt
    pages_summary = "\n\n".join([
        f"Page {i+1}:\n"
        f"  URL: {p['url']}\n"
        f"  Current Title: {p['title']}\n"
        f"  Current Meta: {p['meta_description']}\n"
        f"  Current H1: {p['h1']}\n"
        f"  Page Type: {p['page_type']}\n"
        f"  Excerpt: {p['excerpt']}"
        for i, p in enumerate(enriched_pages)
    ])

    prompt = f"""You are an SEO expert. These pages on {site.name} are competing for similar keywords.
Analyze each page and recommend specific changes to differentiate them.

For each page, provide:
- new_title: A better, more specific title that targets a unique angle (60 chars max)
- new_h1: A differentiated H1 heading
- new_meta_description: Updated meta description with unique selling point (155 chars max)
- primary_keyword: The specific keyword THIS page should own
- internal_link_suggestion: Which other page(s) this should link to and with what anchor text
- reasoning: Brief explanation (2-3 sentences) of why these changes help

Pages:
{pages_summary}

Shared keyword causing conflict: {keyword}
Conflict type: {conflict_type}

Return ONLY a valid JSON array with one object per page. Each object must have the fields above plus the original url.
Example structure:
[
  {{
    "url": "https://example.com/page1",
    "new_title": "...",
    "new_h1": "...",
    "new_meta_description": "...",
    "primary_keyword": "...",
    "internal_link_suggestion": "Link to [page2] with anchor text 'specific service'",
    "reasoning": "..."
  }}
]
"""

    # Call OpenAI
    try:
        openai.api_key = os.environ.get('OPENAI_API_KEY')
        if not openai.api_key:
            logger.error("OPENAI_API_KEY not set")
            return Response({
                'error': {'code': 'CONFIG_ERROR', 'message': 'OpenAI API key not configured', 'detail': None, 'status': 500}
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        response = openai.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {'role': 'system', 'content': 'You are an expert SEO consultant specializing in content differentiation.'},
                {'role': 'user', 'content': prompt}
            ],
            temperature=0.7,
            max_tokens=2000,
        )

        ai_response = response.choices[0].message.content.strip()
        
        # Parse JSON response
        # Sometimes the model wraps in ```json, so clean that up
        if ai_response.startswith('```'):
            ai_response = ai_response.split('```')[1]
            if ai_response.startswith('json'):
                ai_response = ai_response[4:]
            ai_response = ai_response.strip()

        recommendations = json.loads(ai_response)

        # Merge with page_id from enriched_pages
        for rec in recommendations:
            url = rec.get('url')
            matching = next((p for p in enriched_pages if p['url'] == url), None)
            if matching:
                rec['page_id'] = matching['page_id']
            else:
                rec['page_id'] = None

        return Response({
            'data': {
                'site_id': site.id,
                'keyword': keyword,
                'recommendations': recommendations,
            }
        }, status=status.HTTP_200_OK)

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse AI response: {e}\nResponse: {ai_response}")
        return Response({
            'error': {'code': 'AI_PARSE_ERROR', 'message': 'Failed to parse AI recommendations', 'detail': str(e), 'status': 500}
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as e:
        logger.exception("AI differentiation failed")
        return Response({
            'error': {'code': 'AI_ERROR', 'message': 'AI analysis failed', 'detail': str(e), 'status': 500}
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def apply_differentiation(request, site_id):
    """
    Apply approved differentiation changes to WordPress.
    
    POST /api/v1/sites/{site_id}/conflicts/apply-differentiation/
    
    Body:
    - changes: list of {page_id, url, new_title, new_meta_description, new_h1}
    """
    site, err = _get_site_or_error(request, site_id)
    if err:
        return err

    changes = request.data.get('changes', [])
    if not changes:
        return Response({
            'error': {'code': 'MISSING_CHANGES', 'message': 'changes array is required', 'detail': None, 'status': 400}
        }, status=status.HTTP_400_BAD_REQUEST)

    results = []
    for change in changes:
        url = change.get('url')
        page_id = change.get('page_id')
        new_title = change.get('new_title')
        new_meta = change.get('new_meta_description')
        new_h1 = change.get('new_h1')

        if not url:
            results.append({'url': 'unknown', 'success': False, 'error': 'Missing URL'})
            continue

        try:
            # Update DB
            if page_id:
                page = Page.objects.filter(site=site, id=page_id).first()
                if page:
                    if new_title:
                        page.title = new_title
                    if new_meta:
                        page.yoast_description = new_meta
                    # We don't have a separate H1 field yet, but we'll send it to WP
                    page.save()

            # Send webhook to WordPress
            # TODO: Implement webhook sending when the webhook system is ready
            # For now, we'll just log it
            webhook_payload = {
                'event': 'page.update_meta',
                'site_id': site.id,
                'url': url,
                'title': new_title,
                'meta_description': new_meta,
                'h1': new_h1,
            }
            logger.info(f"Would send webhook to WordPress: {webhook_payload}")
            # webhook.send(site, webhook_payload)

            results.append({
                'url': url,
                'success': True,
                'updated_fields': {
                    'title': new_title,
                    'meta_description': new_meta,
                    'h1': new_h1,
                },
            })

        except Exception as e:
            logger.exception(f"Failed to apply changes for {url}")
            results.append({
                'url': url,
                'success': False,
                'error': str(e),
            })

    success_count = sum(1 for r in results if r.get('success'))
    
    return Response({
        'data': {
            'site_id': site.id,
            'total_changes': len(changes),
            'successful': success_count,
            'failed': len(changes) - success_count,
            'results': results,
        }
    }, status=status.HTTP_200_OK)
