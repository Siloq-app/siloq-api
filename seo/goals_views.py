"""
Goals endpoints.
GET  /api/v1/sites/{site_id}/goals/  — retrieve goals
POST /api/v1/sites/{site_id}/goals/  — create or update (upsert)
"""
import logging
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response
from rest_framework import status
from integrations.authentication import APIKeyAuthentication
from integrations.permissions import IsAPIKeyAuthenticated
from .models import SiteGoals

logger = logging.getLogger(__name__)

VALID_GOALS = {'local_leads', 'ecommerce_sales', 'topic_authority', 'multi_location', 'geo_citations', 'organic_growth'}


@api_view(['GET', 'POST'])
@authentication_classes([APIKeyAuthentication])
@permission_classes([IsAPIKeyAuthenticated])
def site_goals(request, site_id):
    site = request.auth['site']
    if str(site.id) != str(site_id):
        return Response({'error': 'Site not found'}, status=404)

    if request.method == 'GET':
        try:
            goals = SiteGoals.objects.get(site=site)
            return Response(_serialize(goals))
        except SiteGoals.DoesNotExist:
            return Response({
                'exists': False,
                'primary_goal': None,
                'priority_services': [],
                'priority_locations': [],
                'geo_priority_pages': [],
            })

    # POST — upsert
    data = request.data
    primary_goal = data.get('primary_goal', 'local_leads')
    if primary_goal not in VALID_GOALS:
        return Response(
            {'error': f'primary_goal must be one of: {", ".join(sorted(VALID_GOALS))}'},
            status=400,
        )

    goals, created = SiteGoals.objects.update_or_create(
        site=site,
        defaults={
            'primary_goal': primary_goal,
            'priority_services': data.get('priority_services', []),
            'priority_locations': data.get('priority_locations', []),
            'geo_priority_pages': data.get('geo_priority_pages', []),
        }
    )
    serialized = _serialize(goals)
    serialized['created'] = created
    return Response(serialized, status=201 if created else 200)


def _serialize(goals):
    return {
        'exists': True,
        'primary_goal': goals.primary_goal,
        'priority_services': goals.priority_services,
        'priority_locations': goals.priority_locations,
        'geo_priority_pages': goals.geo_priority_pages,
        'updated_at': goals.updated_at.isoformat(),
    }
