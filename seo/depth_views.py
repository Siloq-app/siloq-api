"""
Views for Topical Depth & Semantic Closure Engine.

Endpoints:
  - topic_boundary        GET/POST/PATCH  /sites/{site_id}/silos/{silo_id}/topic-boundary
  - generate_subtopic_map POST            /sites/{site_id}/silos/{silo_id}/generate-subtopic-map
  - depth_scores          GET/POST        /sites/{site_id}/silos/{silo_id}/depth-scores
  - gap_report            GET             /sites/{site_id}/silos/{silo_id}/gap-report
  - subtopic_map_view     GET             /sites/{site_id}/silos/{silo_id}/subtopic-map
  - add_subtopic_to_plan  POST            /sites/{site_id}/silos/{silo_id}/subtopics/{subtopic_id}/add-to-plan
  - link_relationships    GET/POST        /sites/{site_id}/silos/{silo_id}/link-relationships
"""
import uuid

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from seo.depth_engine import (
    assess_link_relationships,
    build_brief_prompt,
    generate_subtopic_map as gen_subtopic_map,
    score_silo_depth,
)
from seo.models import (
    ContentJob,
    SemanticLinkRelationship,
    SiloDefinition,
    SiloDepthScore,
    SiloTopicBoundary,
    SubtopicMap,
)
from seo.serializers import (
    SemanticLinkRelationshipSerializer,
    SiloDepthScoreSerializer,
    SiloTopicBoundarySerializer,
    SubtopicMapSerializer,
)
from sites.models import Site


# ─────────────────────────────────────────────────────────────
# 1. Topic Boundary (GET / POST / PATCH)
# ─────────────────────────────────────────────────────────────

@api_view(['GET', 'POST', 'PATCH'])
@permission_classes([IsAuthenticated])
def topic_boundary(request, site_id, silo_id):
    site = get_object_or_404(Site, id=site_id, user=request.user)
    silo = get_object_or_404(SiloDefinition, id=silo_id, site=site)

    if request.method == 'GET':
        boundary = get_object_or_404(SiloTopicBoundary, silo=silo, site=site)
        return Response(SiloTopicBoundarySerializer(boundary).data)

    # POST or PATCH
    core_topic = request.data.get('core_topic')
    if request.method == 'POST' and not core_topic:
        return Response({'error': 'core_topic is required'}, status=status.HTTP_400_BAD_REQUEST)

    defaults = {}
    if core_topic is not None:
        defaults['core_topic'] = core_topic
    if 'adjacent_topics' in request.data:
        defaults['adjacent_topics'] = request.data['adjacent_topics']
    if 'out_of_scope_topics' in request.data:
        defaults['out_of_scope_topics'] = request.data['out_of_scope_topics']
    if 'entity_type' in request.data:
        defaults['entity_type_override'] = request.data['entity_type']

    boundary, created = SiloTopicBoundary.objects.update_or_create(
        site=site, silo=silo, defaults=defaults,
    )

    return Response({
        'boundary_id': boundary.id,
        'silo_id': str(silo_id),
        'data': SiloTopicBoundarySerializer(boundary).data,
    }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


# ─────────────────────────────────────────────────────────────
# 2. Generate Subtopic Map (POST)
# ─────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_subtopic_map_view(request, site_id, silo_id):
    site = get_object_or_404(Site, id=site_id, user=request.user)
    silo = get_object_or_404(SiloDefinition, id=silo_id, site=site)
    get_object_or_404(SiloTopicBoundary, silo=silo, site=site)

    try:
        subtopics = gen_subtopic_map(str(silo_id), site_id)
        return Response({
            'subtopics_generated': len(subtopics),
            'silo_id': str(silo_id),
            'subtopics': SubtopicMapSerializer(subtopics, many=True).data,
        }, status=status.HTTP_201_CREATED)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_502_BAD_GATEWAY)


# ─────────────────────────────────────────────────────────────
# 3. Depth Scores (GET / POST)
# ─────────────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def depth_scores(request, site_id, silo_id):
    site = get_object_or_404(Site, id=site_id, user=request.user)
    silo = get_object_or_404(SiloDefinition, id=silo_id, site=site)

    if request.method == 'GET':
        score = SiloDepthScore.objects.filter(
            silo=silo, site=site,
        ).order_by('-scored_at').first()
        if not score:
            return Response({'error': 'No depth scores yet. Run a scan first.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(SiloDepthScoreSerializer(score).data)

    # POST — recalculate
    try:
        score = score_silo_depth(str(silo_id), site_id)
        if not score:
            return Response(
                {'error': 'No subtopic map found. Generate subtopics first.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(SiloDepthScoreSerializer(score).data, status=status.HTTP_201_CREATED)
    except SiloTopicBoundary.DoesNotExist:
        return Response(
            {'error': 'Topic boundary not defined. Create one first.'},
            status=status.HTTP_400_BAD_REQUEST,
        )


# ─────────────────────────────────────────────────────────────
# 4. Gap Report (GET)
# ─────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def gap_report(request, site_id, silo_id):
    site = get_object_or_404(Site, id=site_id, user=request.user)
    silo = get_object_or_404(SiloDefinition, id=silo_id, site=site)
    boundary = get_object_or_404(SiloTopicBoundary, silo=silo, site=site)

    subtopics = SubtopicMap.objects.filter(silo=silo, site=site)

    critical_gaps = subtopics.filter(
        coverage_status='missing', priority_score__gte=80,
    ).order_by('-priority_score')

    thin_pages = subtopics.filter(
        coverage_status='thin', priority_score__gte=70,
    ).order_by('-priority_score')

    stale_pages = subtopics.filter(
        coverage_status='stale', priority_score__gte=60,
    ).order_by('-priority_score')

    standard_gaps = subtopics.filter(
        coverage_status='missing', priority_score__range=(50, 79),
    ).order_by('-priority_score')

    def enrich_gap(s):
        content_type = 'evidence' if s.subtopic_type == 'evidence' else 'architecture'
        return {
            'id': s.id,
            'subtopic_label': s.subtopic_label,
            'subtopic_type': s.subtopic_type,
            'priority_score': s.priority_score,
            'coverage_status': s.coverage_status,
            'content_type': content_type,
            'brief_prompt': build_brief_prompt(s, boundary),
        }

    return Response({
        'critical_gaps': [enrich_gap(s) for s in critical_gaps],
        'thin_pages': [enrich_gap(s) for s in thin_pages],
        'stale_pages': [enrich_gap(s) for s in stale_pages],
        'standard_gaps': [enrich_gap(s) for s in standard_gaps],
        'total_gap_count': (
            critical_gaps.count() + thin_pages.count() +
            stale_pages.count() + standard_gaps.count()
        ),
        'estimated_closure_gap': (
            f"{critical_gaps.count() + standard_gaps.count()} pages to reach 80% topical closure"
        ),
    })


# ─────────────────────────────────────────────────────────────
# 5. Subtopic Map (GET)
# ─────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def subtopic_map_view(request, site_id, silo_id):
    site = get_object_or_404(Site, id=site_id, user=request.user)
    silo = get_object_or_404(SiloDefinition, id=silo_id, site=site)

    subtopics = SubtopicMap.objects.filter(silo=silo, site=site).order_by('-priority_score')

    # Group by type
    grouped = {}
    for st in subtopics:
        t = st.subtopic_type
        if t not in grouped:
            grouped[t] = []
        grouped[t].append(SubtopicMapSerializer(st).data)

    return Response({
        'silo_id': str(silo_id),
        'total': subtopics.count(),
        'by_type': grouped,
        'all': SubtopicMapSerializer(subtopics, many=True).data,
    })


# ─────────────────────────────────────────────────────────────
# 6. Add Subtopic to Plan (POST)
# ─────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_subtopic_to_plan(request, site_id, silo_id, subtopic_id):
    site = get_object_or_404(Site, id=site_id, user=request.user)
    silo = get_object_or_404(SiloDefinition, id=silo_id, site=site)
    subtopic = get_object_or_404(SubtopicMap, id=subtopic_id, silo=silo, site=site)
    boundary = get_object_or_404(SiloTopicBoundary, silo=silo, site=site)

    content_type = request.data.get('content_type') or (
        'evidence' if subtopic.subtopic_type == 'evidence' else 'architecture'
    )

    brief_prompt = build_brief_prompt(subtopic, boundary)

    job = ContentJob.objects.create(
        site=site,
        job_type='supporting_content',
        topic=subtopic.subtopic_label,
        recommendation=brief_prompt,
        status='pending',
        priority='high' if subtopic.priority_score >= 80 else 'medium',
        created_by=request.user,
    )

    return Response({
        'content_plan_item_id': job.id,
        'subtopic_id': subtopic.id,
        'brief_prompt': brief_prompt,
        'content_type': content_type,
    }, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────────────────────
# 7. Link Relationships (GET / POST)
# ─────────────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def link_relationships(request, site_id, silo_id):
    site = get_object_or_404(Site, id=site_id, user=request.user)
    silo = get_object_or_404(SiloDefinition, id=silo_id, site=site)

    if request.method == 'GET':
        from seo.depth_engine import get_silo_page_ids
        page_ids = get_silo_page_ids(str(silo_id), site_id)
        rels = SemanticLinkRelationship.objects.filter(
            site=site, source_page_id__in=page_ids,
        ).order_by('-assessed_at')
        return Response({
            'total': rels.count(),
            'relationships': SemanticLinkRelationshipSerializer(rels, many=True).data,
        })

    # POST — run assessment
    try:
        result = assess_link_relationships(site_id, str(silo_id))
        return Response(result, status=status.HTTP_201_CREATED)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_502_BAD_GATEWAY)
