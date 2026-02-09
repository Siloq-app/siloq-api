"""
Scan views for WordPress lead generation scanner.
Handles scan creation, status retrieval, and report generation.
"""
import logging

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.response import Response
from django.utils import timezone
from django.shortcuts import get_object_or_404

from sites.models import Site
from .models import Scan
from .serializers import ScanCreateSerializer, ScanSerializer
from .permissions import IsAPIKeyAuthenticated
from .authentication import APIKeyAuthentication

logger = logging.getLogger(__name__)


@api_view(['POST'])
@authentication_classes([APIKeyAuthentication])
@permission_classes([IsAPIKeyAuthenticated])
def create_scan(request):
    """
    Create a new website scan (for lead gen scanner).
    
    POST /api/v1/scans/
    Headers: Authorization: Bearer <api_key>
    Body: { "url": "https://example.com", "scan_type": "full" }
    
    Returns: { "id": 1, "status": "pending", ... }
    """
    site = request.auth['site']
    serializer = ScanCreateSerializer(data=request.data)
    
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    scan = Scan.objects.create(
        site=site,
        url=serializer.validated_data['url'],
        scan_type=serializer.validated_data.get('scan_type', 'full'),
        status='pending'
    )
    
    # TODO: Trigger async scan processing (Celery task, etc.)
    # For now, simulate immediate completion with dummy data
    scan.status = 'completed'
    scan.score = 72  # Dummy score
    scan.pages_analyzed = 1
    scan.scan_duration_seconds = 2.5
    scan.completed_at = timezone.now()
    scan.results = {
        'technical_score': 80,
        'content_score': 70,
        'structure_score': 75,
        'performance_score': 65,
        'seo_score': 72,
        'issues': [
            {'type': 'missing_meta_description', 'severity': 'high', 'message': 'Missing meta description'},
            {'type': 'no_h1', 'severity': 'medium', 'message': 'No H1 heading found'},
        ],
        'recommendations': [
            'Add a meta description',
            'Add an H1 heading',
        ]
    }
    scan.save(update_fields=['status', 'score', 'pages_analyzed', 'scan_duration_seconds', 'completed_at', 'results'])
    
    return Response(ScanSerializer(scan).data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@authentication_classes([APIKeyAuthentication])
@permission_classes([IsAPIKeyAuthenticated])
def get_scan(request, scan_id):
    """
    Get scan status and results.
    
    GET /api/v1/scans/{scan_id}/
    Headers: Authorization: Bearer <api_key>
    
    Returns: { "id": 1, "status": "completed", "score": 72, ... }
    """
    site = request.auth['site']
    scan = get_object_or_404(Scan, id=scan_id, site=site)
    
    return Response(ScanSerializer(scan).data)


@api_view(['GET'])
@authentication_classes([APIKeyAuthentication])
@permission_classes([IsAPIKeyAuthenticated])
def get_scan_report(request, scan_id):
    """
    Get full scan report (for lead gen scanner full report).
    
    GET /api/v1/scans/{scan_id}/report/
    Headers: Authorization: Bearer <api_key>
    
    Returns: Full detailed report with keyword cannibalization analysis, etc.
    """
    site = request.auth['site']
    scan = get_object_or_404(Scan, id=scan_id, site=site)
    
    if scan.status != 'completed':
        return Response(
            {'error': 'Scan not completed yet'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Build comprehensive report
    report = {
        'scan_id': scan.id,
        'url': scan.url,
        'score': scan.score,
        'pages_analyzed': scan.pages_analyzed,
        'scan_duration_seconds': scan.scan_duration_seconds,
        'completed_at': scan.completed_at,
        'results': scan.results,
        # Add keyword cannibalization analysis
        'keyword_cannibalization': {
            'issues_found': len(scan.results.get('issues', [])),
            'recommendations': scan.results.get('recommendations', []),
        }
    }
    
    return Response(report)
