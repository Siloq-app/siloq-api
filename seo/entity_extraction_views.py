"""
API endpoint for Phase 0.5 entity extraction.

POST /api/v1/sites/{site_id}/pages/extract-entities/

Accepts a list of page dicts (url, title, h1, meta) and returns the
named entities extracted by Claude in a single batched API call.

Usage:
    POST /api/v1/sites/123/pages/extract-entities/
    {
        "pages": [
            {"url": "/chasse-performance-vip-jacket/", "title": "Chasse Performance VIP Jacket",
             "h1": "Chasse Performance VIP Jacket", "meta": "Shop the Chasse Performance VIP Jacket..."},
            {"url": "/chasse-performance-all-star-jacket/", "title": "Chasse Performance All Star Jacket",
             "h1": "Chasse Performance All Star Jacket", "meta": "..."}
        ]
    }

Response:
    {
        "pages": [
            {
                "url": "/chasse-performance-vip-jacket/",
                "entities": [
                    {"text": "Chasse Performance", "type": "brand_line", "confidence": 0.95},
                    {"text": "VIP Jacket", "type": "product_name", "confidence": 0.90},
                    {"text": "Jacket", "type": "product_category", "confidence": 0.85}
                ]
            },
            ...
        ]
    }
"""

import logging

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from sites.models import Site
from seo.cannibalization.phase0_entity_extraction import extract_entities_for_pages

logger = logging.getLogger(__name__)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def extract_entities(request, site_id: int):
    """
    POST /api/v1/sites/{site_id}/pages/extract-entities/

    Extract named entities for a list of pages using Claude (batch call).

    Request body:
        {
            "pages": [
                {"url": "...", "title": "...", "h1": "...", "meta": "..."},
                ...
            ]
        }

    Returns:
        {
            "pages": [
                {"url": "...", "entities": [{"text": "...", "type": "...", "confidence": 0.9}, ...]},
                ...
            ]
        }
    """
    site = get_object_or_404(Site, id=site_id)

    # Ownership check
    if site.user != request.user:
        return Response(
            {'error': {'code': 'FORBIDDEN', 'message': 'Permission denied.', 'status': 403}},
            status=status.HTTP_403_FORBIDDEN,
        )

    pages = request.data.get('pages', [])
    if not isinstance(pages, list):
        return Response(
            {'error': {'code': 'INVALID_INPUT', 'message': '`pages` must be a list.', 'status': 400}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not pages:
        return Response({'pages': []}, status=status.HTTP_200_OK)

    # Validate each page entry
    valid_pages = []
    for idx, page in enumerate(pages):
        if not isinstance(page, dict):
            return Response(
                {
                    'error': {
                        'code': 'INVALID_INPUT',
                        'message': f'pages[{idx}] must be an object.',
                        'status': 400,
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not page.get('url'):
            return Response(
                {
                    'error': {
                        'code': 'INVALID_INPUT',
                        'message': f'pages[{idx}].url is required.',
                        'status': 400,
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        valid_pages.append({
            'url': str(page.get('url', '')),
            'title': str(page.get('title', '')),
            'h1': str(page.get('h1', '')),
            'meta': str(page.get('meta', '')),
        })

    try:
        extracted = extract_entities_for_pages(valid_pages)
    except RuntimeError as exc:
        # ANTHROPIC_API_KEY not configured
        logger.error("Entity extraction config error: %s", exc)
        return Response(
            {
                'error': {
                    'code': 'AI_NOT_CONFIGURED',
                    'message': str(exc),
                    'status': 503,
                }
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except Exception as exc:
        logger.error("Entity extraction failed for site %s: %s", site_id, exc, exc_info=True)
        return Response(
            {
                'error': {
                    'code': 'EXTRACTION_FAILED',
                    'message': 'Entity extraction failed. Check server logs.',
                    'status': 500,
                }
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return Response({'pages': extracted}, status=status.HTTP_200_OK)
