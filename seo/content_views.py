"""
Content generation job endpoints for WordPress plugin compatibility.

POST /api/v1/content-jobs/ - Create a content generation job (synchronous)
GET /api/v1/content-jobs/{job_id}/ - Check job status
"""
import json
import logging
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response
from rest_framework import status

from integrations.authentication import APIKeyAuthentication
from integrations.permissions import IsAPIKeyAuthenticated
from .models import ContentJob
from .content_generation import generate_supporting_content

logger = logging.getLogger(__name__)


@csrf_exempt
@api_view(['POST'])
@authentication_classes([APIKeyAuthentication])
@permission_classes([IsAPIKeyAuthenticated])
def create_content_job(request):
    """
    Create and immediately execute a content generation job synchronously.

    POST /api/v1/content-jobs/
    Headers: Authorization: Bearer <api_key>
    Body: {
        "page_id": <int|null>,
        "wp_post_id": <int|null>,
        "job_type": "supporting_content",
        "title": "Target page title",
        "url": "https://example.com/target-page"
    }

    Returns 201 with status "completed" or "failed" — never "pending".
    The result is available immediately in the response and via the GET endpoint.
    """
    site = request.auth['site']
    page_id = request.data.get('page_id')
    wp_post_id = request.data.get('wp_post_id')
    # Default to 'supporting_content' — the valid ContentJob job_type for this flow
    job_type = request.data.get('job_type', 'supporting_content')
    title = request.data.get('title', '')
    url = request.data.get('url', '')

    # Create the job in 'in_progress' state immediately
    job = ContentJob.objects.create(
        site=site,
        page_id=page_id,
        wp_post_id=wp_post_id,
        job_type=job_type,
        topic=title,
        status='in_progress',
    )

    logger.info(f"Content job {job.id} started (in_progress) for site {site.id}, page_id={page_id}")

    # Pull business context directly from the Site model
    business_name = site.name
    business_type = site.business_type or 'local'
    service_areas = site.service_areas or []

    # Generate content synchronously — this call blocks until the LLM responds
    result = generate_supporting_content(
        target_page_title=title,
        target_page_url=url,
        content_type='supporting_article',
        business_name=business_name,
        business_type=business_type,
        service_areas=service_areas,
    )

    if result.get('success'):
        job.status = 'completed'
        job.generated_content = json.dumps(result)
        job.save()

        logger.info(f"Content job {job.id} completed successfully")

        return Response({
            'job_id': str(job.id),
            'status': 'completed',
            'result': result,
        }, status=status.HTTP_201_CREATED)
    else:
        error_msg = result.get('error', 'Content generation failed')
        job.status = 'failed'
        # Store the error message in recommendation (closest available text field)
        job.recommendation = error_msg
        job.generated_content = json.dumps(result)
        job.save()

        logger.error(f"Content job {job.id} failed: {error_msg}")

        return Response({
            'job_id': str(job.id),
            'status': 'failed',
            'error': error_msg,
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

    job_id is the integer primary key returned by the POST endpoint.
    """
    site = request.auth['site']

    try:
        job = ContentJob.objects.get(id=job_id, site=site)
    except ContentJob.DoesNotExist:
        return Response({'error': 'Job not found'}, status=status.HTTP_404_NOT_FOUND)

    # Deserialize stored content back to dict; fall back to None if absent/invalid
    result = None
    if job.generated_content:
        try:
            result = json.loads(job.generated_content)
        except (json.JSONDecodeError, ValueError):
            result = {'raw': job.generated_content}

    # Error message was stored in recommendation when status is 'failed'
    error = job.recommendation if job.status == 'failed' else None

    return Response({
        'job_id': str(job.id),
        'status': job.status,
        'result': result,
        'error': error,
        'created_at': job.created_at,
        'updated_at': job.updated_at,
    })
