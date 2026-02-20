"""
Content generation job endpoints for WordPress plugin compatibility.

POST /api/v1/content-jobs/ - Create a content generation job
GET /api/v1/content-jobs/{job_id}/ - Check job status
"""
import uuid
import logging
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response
from rest_framework import status

from integrations.authentication import APIKeyAuthentication
from integrations.permissions import IsAPIKeyAuthenticated
from .models import ContentJob

logger = logging.getLogger(__name__)


@csrf_exempt
@api_view(['POST'])
@authentication_classes([APIKeyAuthentication])
@permission_classes([IsAPIKeyAuthenticated])
def create_content_job(request):
    """
    Create a content generation job.

    POST /api/v1/content-jobs/
    Headers: Authorization: Bearer <api_key>
    Body: { "page_id": "...", "wp_post_id": 123, "job_type": "content_generation" }
    """
    site = request.auth['site']
    page_id = request.data.get('page_id')
    wp_post_id = request.data.get('wp_post_id')
    job_type = request.data.get('job_type', 'content_generation')

    job_id = str(uuid.uuid4())

    ContentJob.objects.create(
        job_id=job_id,
        site=site,
        page_id=page_id,
        wp_post_id=wp_post_id,
        job_type=job_type,
        status='pending',
    )

    logger.info(f"Content job created: {job_id} for site {site.id}, page {page_id}")

    return Response({
        'job_id': job_id,
        'status': 'pending',
        'message': 'Content generation job created',
    }, status=status.HTTP_201_CREATED)


@csrf_exempt
@api_view(['GET'])
@authentication_classes([APIKeyAuthentication])
@permission_classes([IsAPIKeyAuthenticated])
def get_content_job_status(request, job_id):
    """
    Get status of a content generation job.

    GET /api/v1/content-jobs/{job_id}/
    Headers: Authorization: Bearer <api_key>
    """
    site = request.auth['site']

    try:
        job = ContentJob.objects.get(job_id=job_id, site=site)
    except ContentJob.DoesNotExist:
        return Response({'error': 'Job not found'}, status=status.HTTP_404_NOT_FOUND)

    return Response({
        'job_id': job.job_id,
        'status': job.status,
        'result': job.result,
        'error': job.error,
        'created_at': job.created_at,
        'updated_at': job.updated_at,
    })
