"""
API endpoints for page classification.
"""
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404

from sites.models import Site
from seo.models import Page
from seo.page_classifier import classify_and_save, classify_all_pages, _get_business_profile


def _get_site_for_user(request, site_id):
    return get_object_or_404(Site, id=site_id, user=request.user)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def classify_single_page(request, site_id, page_id):
    """
    POST /api/v1/sites/{site_id}/pages/{page_id}/classify/
    Re-classify a single page. Returns new classification.
    """
    site = _get_site_for_user(request, site_id)
    page = get_object_or_404(Page, id=page_id, site=site)
    profile = _get_business_profile(site)
    result = classify_and_save(page, business_profile=profile)
    return Response({
        'page_id': page.id,
        'page_type': result['page_type'],
        'confidence': result['confidence'],
        'reason': result['reason'],
        'page_type_override': page.page_type_override,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def classify_all(request, site_id):
    """
    POST /api/v1/sites/{site_id}/classify-all/
    Re-classify all pages for a site.
    """
    site = _get_site_for_user(request, site_id)
    results = classify_all_pages(site.id)
    return Response({
        'site_id': site.id,
        'classified': len(results),
        'results': results,
    })


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def manual_page_type_override(request, site_id, page_id):
    """
    PATCH /api/v1/sites/{site_id}/pages/{page_id}/page-type/
    Manual override: {"page_type": "utility"}
    Sets page_type_override=True.
    """
    site = _get_site_for_user(request, site_id)
    page = get_object_or_404(Page, id=page_id, site=site)

    page_type = request.data.get('page_type')
    valid_types = {c[0] for c in Page.PAGE_TYPE_CHOICES}
    if page_type not in valid_types:
        return Response(
            {'error': f'Invalid page_type. Must be one of: {", ".join(sorted(valid_types))}'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    page.page_type_classification = page_type
    page.page_type_override = True
    page.is_money_page = (page_type == 'money')
    page.save(update_fields=['page_type_classification', 'page_type_override', 'is_money_page'])

    return Response({
        'page_id': page.id,
        'page_type': page.page_type_classification,
        'page_type_override': True,
    })
