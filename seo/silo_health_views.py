"""
API endpoints for Silo Health Score v2.

GET  /api/v1/sites/{site_id}/silo-health/
     Returns current health scores for every silo + overall site health.

POST /api/v1/sites/{site_id}/silo-health/recalculate/
     Trigger an on-demand recalculation (synchronous; returns fresh scores).
"""
import logging

from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status as drf_status

from sites.models import Site
from seo.models import SiloDefinition, SiloHealthScore
from seo.silo_health import SiloHealthCalculator

logger = logging.getLogger(__name__)


def _check_site_access(request, site_id: int):
    """Return (site, error_response) — one of which will be None."""
    try:
        site = Site.objects.get(id=site_id, user=request.user)
    except Site.DoesNotExist:
        return None, Response(
            {"error": {"code": "SITE_NOT_FOUND", "message": "Site not found.", "status": 404}},
            status=drf_status.HTTP_404_NOT_FOUND,
        )
    return site, None


def _latest_score_per_silo(site) -> dict:
    """
    Return a dict of {silo_id: SiloHealthScore} with the most recent score
    record for each silo.  Ordered DESC so first occurrence per silo wins.
    """
    all_records = (
        SiloHealthScore.objects
        .filter(site=site)
        .select_related("silo")
        .order_by("-calculated_at")
    )
    latest: dict = {}
    for record in all_records:
        silo_key = str(record.silo_id)
        if silo_key not in latest:
            latest[silo_key] = record
    return latest


def _serialize_silo_score(silo: SiloDefinition, score_record) -> dict:
    """Serialise a single silo with its latest health score."""
    if score_record is None:
        return {
            "silo_id": str(silo.id),
            "silo_name": silo.name,
            "silo_slug": silo.slug,
            "score": None,
            "component_scores": None,
            "page_count": None,
            "calculated_at": None,
            "trigger": None,
        }

    return {
        "silo_id": str(silo.id),
        "silo_name": silo.name,
        "silo_slug": silo.slug,
        "score": float(score_record.score),
        "component_scores": {
            k: float(v) if v is not None else None
            for k, v in score_record.component_scores.items()
        },
        "page_count": score_record.page_count,
        "calculated_at": score_record.calculated_at.isoformat(),
        "trigger": score_record.trigger,
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def silo_health_scores(request, site_id: int):
    """
    GET /api/v1/sites/{site_id}/silo-health/

    Returns:
    {
        "overall_score": 74.3,
        "silo_count": 5,
        "calculated_at": "2026-02-18T12:00:00Z",
        "silos": [
            {
                "silo_id": "...",
                "silo_name": "Roofing Services",
                "score": 82.5,
                "component_scores": {
                    "keyword_clarity": 90.0,
                    "structural_integrity": 75.0,
                    "content_architecture": 80.0,
                    "internal_linking": 85.0
                },
                "page_count": 6,
                "calculated_at": "2026-02-18T12:00:00Z",
                "trigger": "gsc_connect"
            },
            ...
        ]
    }

    If no scores have been calculated yet for some silos, those silos appear
    with score=null and a "needs_calculation": true flag. The overall_score
    is computed from whichever silos have scores.
    """
    site, err = _check_site_access(request, site_id)
    if err:
        return err

    silos = list(SiloDefinition.objects.filter(site=site, status="active").order_by("name"))

    if not silos:
        return Response({
            "overall_score": None,
            "silo_count": 0,
            "calculated_at": None,
            "silos": [],
            "meta": {"needs_calculation": False},
        })

    latest_scores = _latest_score_per_silo(site)

    silo_data = []
    scored_scores = []
    latest_calc_at = None

    for silo in silos:
        record = latest_scores.get(str(silo.id))
        silo_data.append(_serialize_silo_score(silo, record))

        if record is not None:
            scored_scores.append(float(record.score))
            if latest_calc_at is None or record.calculated_at > latest_calc_at:
                latest_calc_at = record.calculated_at

    overall_score = None
    if scored_scores:
        overall_score = round(sum(scored_scores) / len(scored_scores), 2)

    needs_calculation = len(scored_scores) < len(silos)

    return Response({
        "overall_score": overall_score,
        "silo_count": len(silos),
        "calculated_at": latest_calc_at.isoformat() if latest_calc_at else None,
        "silos": silo_data,
        "meta": {
            "needs_calculation": needs_calculation,
            "silos_without_score": len(silos) - len(scored_scores),
        },
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def silo_health_recalculate(request, site_id: int):
    """
    POST /api/v1/sites/{site_id}/silo-health/recalculate/

    Trigger an on-demand synchronous recalculation and return fresh scores.
    """
    site, err = _check_site_access(request, site_id)
    if err:
        return err

    trigger = request.data.get("trigger", "on_demand")

    try:
        calc = SiloHealthCalculator(site)
        results = calc.calculate_all()

        if results:
            # Persist with trigger label
            from seo.models import SiloHealthScore as _SHS, SiloDefinition as _SD

            now = timezone.now()
            for result in results:
                try:
                    silo_obj = _SD.objects.get(id=result.silo_id, site=site)
                    _SHS.objects.create(
                        silo=silo_obj,
                        site=site,
                        score=result.score,
                        component_scores=result.component_scores.to_dict(),
                        page_count=result.page_count,
                        details=result.details,
                        trigger=trigger,
                        calculated_at=now,
                    )
                except Exception as exc:
                    logger.exception("Failed saving health score for silo %s: %s", result.silo_id, exc)

        overall = calc.overall_score(results)

        silo_data = []
        for r in results:
            silo_data.append({
                "silo_id": r.silo_id,
                "silo_name": r.silo_name,
                "score": r.score,
                "component_scores": r.component_scores.to_dict(),
                "page_count": r.page_count,
            })

        return Response({
            "overall_score": overall,
            "silo_count": len(results),
            "calculated_at": timezone.now().isoformat(),
            "trigger": trigger,
            "silos": silo_data,
        }, status=drf_status.HTTP_200_OK)

    except Exception as exc:
        logger.exception("Silo health recalculation failed for site %s: %s", site_id, exc)
        return Response(
            {"error": {"code": "CALCULATION_FAILED", "message": str(exc), "status": 500}},
            status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
