"""
AI Content Engine API views.
"""
import logging

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from sites.models import Site
from seo.cannibalization.models import ClusterResult
from .models import SystemPrompt, GeneratedPlan
from .context import build_context_payload, get_pages_with_data
from .providers import call_ai, call_ai_with_retry
from .validators import validate_response, ValidationError

logger = logging.getLogger(__name__)

VALID_ACTIONS = {'merge_plan', 'spoke_rewrite', 'merge_draft', 'spoke_draft'}


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_plan(request):
    """
    POST /api/v1/ai/generate/

    Request body:
        {
            "action": "merge_plan" | "spoke_rewrite" | "merge_draft" | "spoke_draft",
            "conflict_id": 7,
            "site_id": 10
        }
    """
    action = request.data.get('action')
    conflict_id = request.data.get('conflict_id')
    site_id = request.data.get('site_id')

    # Validate input
    if not action or action not in VALID_ACTIONS:
        return Response(
            {'error': f'Invalid action. Must be one of: {", ".join(VALID_ACTIONS)}'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not conflict_id or not site_id:
        return Response(
            {'error': 'conflict_id and site_id are required'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Get site (verify user owns it)
    try:
        site = Site.objects.get(id=site_id, user=request.user)
    except Site.DoesNotExist:
        return Response({'error': 'Site not found'}, status=status.HTTP_404_NOT_FOUND)

    # Get cluster/conflict
    try:
        cluster = ClusterResult.objects.get(
            id=conflict_id,
            analysis_run__site=site,
        )
    except ClusterResult.DoesNotExist:
        return Response({'error': 'Conflict not found'}, status=status.HTTP_404_NOT_FOUND)

    # Load system prompt
    try:
        prompt_obj = SystemPrompt.objects.get(prompt_key=action, is_active=True)
    except SystemPrompt.DoesNotExist:
        return Response(
            {'error': f'No active system prompt found for action: {action}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # Build context payload
    pages_data = get_pages_with_data(cluster, site)
    context_payload = build_context_payload(action, cluster, site, pages_data)

    # Call AI
    try:
        ai_response, provider, model = call_ai(
            prompt_obj.prompt_text, context_payload, action
        )
    except Exception as e:
        logger.error(f"AI call failed: {e}")
        return Response(
            {'error': 'AI generation failed. Please try again.'},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    # Validate response
    try:
        validate_response(action, ai_response)
    except ValidationError as e:
        # Retry once with feedback
        logger.warning(f"Validation failed, retrying: {e}")
        try:
            ai_response, provider, model = call_ai_with_retry(
                prompt_obj.prompt_text, context_payload, action,
                validation_error=str(e),
            )
            validate_response(action, ai_response)
        except (ValidationError, Exception) as retry_err:
            logger.error(f"Retry also failed: {retry_err}")
            return Response(
                {'error': f'AI response validation failed: {retry_err}'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

    # Store the plan
    plan = GeneratedPlan.objects.create(
        site=site,
        conflict_id=conflict_id,
        conflict_query=cluster.gsc_query or cluster.cluster_key,
        action=action,
        prompt_version=prompt_obj.version,
        context_payload=context_payload,
        ai_response=ai_response,
        provider=provider,
        model=model,
    )

    return Response({
        'id': plan.id,
        'action': action,
        'conflict_query': plan.conflict_query,
        'provider': provider,
        'model': model,
        'plan': ai_response,
        'created_at': plan.created_at.isoformat(),
    }, status=status.HTTP_201_CREATED)
