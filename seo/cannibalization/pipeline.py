"""
Cannibalization Detection Pipeline Orchestrator

Runs all 7 phases sequentially:
1. Phase 1: Ingest and classify pages
2. Phase 2: Build safe pairs filter
3. Phase 3: Static detection (POTENTIAL)
4. Phase 4: GSC validation (CONFIRMED)
5. Phase 5: Wrong winner detection
6. Phase 6: Clustering and priority scoring
7. Phase 7: Fix recommendations

Main entry point: run_analysis(site_id, include_gsc=True)
"""
from datetime import datetime, timedelta
from django.utils import timezone
from django.db import transaction
from sites.models import Site
from .models import AnalysisRun, ClusterResult, PageClassification
from . import phase1_ingest
from . import phase2_safe_filters
from . import phase3_static_detect
from . import phase4_gsc_validate
from . import phase4b_homepage
from . import phase5_wrong_winner
from . import phase_blog_service
from . import phase6_cluster
from . import phase7_fix


def run_analysis(site_id: int, include_gsc: bool = True, gsc_days: int = 90) -> AnalysisRun:
    """
    Run complete cannibalization analysis for a site.
    
    Args:
        site_id: Site ID to analyze
        include_gsc: Whether to include GSC data (Phase 4-5)
        gsc_days: Number of days of GSC data to fetch (default 90)
    
    Returns:
        AnalysisRun object with all results
    """
    # Get site
    try:
        site = Site.objects.get(id=site_id)
    except Site.DoesNotExist:
        raise ValueError(f"Site with ID {site_id} not found")
    
    # Create analysis run
    analysis_run = AnalysisRun.objects.create(
        site=site,
        status='running',
        gsc_connected=include_gsc,
    )
    
    try:
        # =====================================================================
        # PHASE 1: Ingest and Classify
        # =====================================================================
        classifications = phase1_ingest.run_phase1(analysis_run, site)
        analysis_run.total_pages_analyzed = len(classifications)
        analysis_run.save()
        
        if not classifications:
            analysis_run.mark_failed("No pages found to analyze")
            return analysis_run
        
        # =====================================================================
        # PHASE 2: Safe Filters
        # =====================================================================
        safe_pairs = phase2_safe_filters.run_phase2(classifications)
        
        # =====================================================================
        # PHASE 3: Static Detection
        # =====================================================================
        static_issues = phase3_static_detect.run_phase3(classifications, safe_pairs)
        
        # =====================================================================
        # PHASE 4 & 5: GSC Validation (if enabled)
        # =====================================================================
        gsc_data = []      # Initialized here so blog/service phase can access it
        gsc_issues = []
        wrong_winner_issues = []

        if include_gsc:
            # Fetch GSC data (aggregate + daily for flip-flop detection)
            gsc_data = _fetch_gsc_data(site, gsc_days)
            gsc_daily_data = _fetch_gsc_daily_data(site, days=28)  # 28 days for flip-flop correlation
            
            if gsc_data:
                # Set GSC date range
                end_date = timezone.now().date()
                start_date = end_date - timedelta(days=gsc_days)
                analysis_run.gsc_date_start = start_date
                analysis_run.gsc_date_end = end_date
                analysis_run.save()
                
                # Get brand name for branded query filtering
                brand_name = _get_brand_name(site)
                homepage_title = _get_homepage_title(site)
                
                # Phase 4: GSC validation (now with flip-flop detection)
                gsc_issues = phase4_gsc_validate.run_phase4(
                    classifications,
                    gsc_data,
                    gsc_daily_data,  # NEW: Pass daily data for flip-flop detection
                    brand_name,
                    homepage_title
                )
                
                # Phase 4b: Homepage cannibalization detection
                # Detects homepage splitting/hoarding service-query impressions.
                # Runs after Phase 4 so it can complement (not duplicate) GSC_HOMEPAGE_SPLIT
                # detections, focusing on the homepage-specific conflict type.
                homepage_issues = phase4b_homepage.detect_homepage_cannibalization(
                    classifications,
                    gsc_data,
                    brand_name,
                )
                gsc_issues.extend(homepage_issues)

                # Upgrade static issues with GSC data
                static_issues = phase4_gsc_validate.upgrade_static_issues(static_issues, gsc_issues)
                
                # Phase 5: Wrong winner detection
                wrong_winner_issues = phase5_wrong_winner.run_phase5(
                    classifications,
                    gsc_data,
                    brand_name,
                    homepage_title
                )
        
        # =====================================================================
        # SEVERITY GATE: Cap structural-only conflicts at MEDIUM
        # =====================================================================
        # Issues from Phase 3 (static detection) that were NOT upgraded by
        # Phase 4 GSC validation are "structural warnings" — title/slug
        # overlap with zero search traffic proof.  These must never be
        # HIGH or CRITICAL because flagging zero-impression overlaps as
        # HIGH erodes user trust.
        blog_service_issues = phase_blog_service.run_phase_blog_service(
            classifications,
            gsc_data=gsc_data or None,
        )

        all_issues = static_issues + gsc_issues + wrong_winner_issues + blog_service_issues

        for issue in all_issues:
            # Only touch SITE_DUPLICATION / POTENTIAL issues (Phase 3)
            bucket = issue.get('bucket', 'SITE_DUPLICATION')
            badge  = issue.get('badge', 'POTENTIAL')

            # Skip anything already GSC-validated or from Phase 4/5
            if issue.get('gsc_validated'):
                issue['conflict_subtype'] = 'active_conflict'
                continue
            if bucket == 'SEARCH_CONFLICT' or badge in ('CONFIRMED', 'WRONG_WINNER'):
                issue['conflict_subtype'] = 'active_conflict'
                continue

            # Check whether ANY page in this issue has GSC impressions
            has_gsc_data = False
            for page in issue.get('pages', []):
                # PageClassification objects won't have gsc_impressions,
                # but dict-style pages (from serialisation) might.
                if hasattr(page, '__getitem__'):
                    if page.get('gsc_impressions', 0) > 0 or page.get('impressions', 0) > 0:
                        has_gsc_data = True
                        break

            if not has_gsc_data:
                # Structural warning — cap severity
                if issue.get('severity', '').upper() in ('HIGH', 'SEVERE', 'CRITICAL'):
                    issue['severity'] = 'MEDIUM'
                issue['conflict_subtype'] = 'structural_warning'
                issue['note'] = (
                    'No search traffic data yet. Monitor \u2014 if both '
                    'pages start ranking, they may compete.'
                )
            else:
                issue['conflict_subtype'] = 'active_conflict'

        # =====================================================================
        # PHASE 6: Clustering
        # =====================================================================
        clustered_issues = phase6_cluster.run_phase6(all_issues)
        
        # =====================================================================
        # PHASE 7: Fix Recommendations
        # =====================================================================
        fix_plan = phase7_fix.run_phase7(clustered_issues, dry_run=True)
        
        # =====================================================================
        # SAVE RESULTS
        # =====================================================================
        with transaction.atomic():
            # Save clusters
            cluster_objects = []
            for cluster in clustered_issues:
                # Build pages_json
                pages_json = [
                    {
                        'page_id': page.page_id,
                        'url': page.url,
                        'title': page.title,
                        'classified_type': page.classified_type,
                        'normalized_path': page.normalized_path,
                    }
                    for page in cluster['pages']
                ]
                
                # Extract GSC query (first query if multiple)
                gsc_query = ''
                gsc_total_imps = 0
                gsc_total_clicks = 0
                gsc_data_json = {}
                
                if cluster['gsc_data']:
                    gsc_data_json = cluster['gsc_data']
                    if 'queries' in gsc_data_json and gsc_data_json['queries']:
                        gsc_query = gsc_data_json['queries'][0]
                    gsc_total_imps = gsc_data_json.get('total_impressions', 0)
                    gsc_total_clicks = gsc_data_json.get('total_clicks', 0)
                
                # Suggest canonical
                suggested_canonical = ''
                if cluster['action_code'] in ['REDIRECT_TO_CANONICAL', 'REDIRECT_OR_DIFFERENTIATE']:
                    canonical_page = phase7_fix._suggest_canonical(cluster['pages'], cluster)
                    if canonical_page:
                        suggested_canonical = canonical_page.url
                
                # Propagate structural_warning metadata from issues
                conflict_subtype = 'active_conflict'
                note = ''
                for iss in cluster.get('issues', []):
                    if iss.get('conflict_subtype') == 'structural_warning':
                        conflict_subtype = 'structural_warning'
                        note = iss.get('note', '')
                        break

                cluster_obj = ClusterResult(
                    analysis_run=analysis_run,
                    cluster_key=cluster['cluster_key'],
                    bucket=cluster['bucket'],
                    badge=cluster['badge'],
                    conflict_type=cluster['conflict_type'],
                    severity=cluster['severity'],
                    action_code=cluster['action_code'],
                    priority_score=cluster['priority_score'],
                    page_count=cluster['page_count'],
                    pages_json=pages_json,
                    gsc_query=gsc_query,
                    gsc_total_impressions=gsc_total_imps,
                    gsc_total_clicks=gsc_total_clicks,
                    gsc_data_json=gsc_data_json,
                    recommendation=cluster['recommendation'],
                    suggested_canonical_url=suggested_canonical,
                    conflict_subtype=conflict_subtype,
                    note=note,
                )
                cluster_objects.append(cluster_obj)
            
            ClusterResult.objects.bulk_create(cluster_objects)
            
            # Update analysis run counts
            analysis_run.total_clusters_found = len(cluster_objects)
            
            # Count by bucket
            analysis_run.search_conflict_count = sum(1 for c in clustered_issues if c['bucket'] == 'SEARCH_CONFLICT')
            analysis_run.site_duplication_count = sum(1 for c in clustered_issues if c['bucket'] == 'SITE_DUPLICATION')
            analysis_run.wrong_winner_count = sum(1 for c in clustered_issues if c['bucket'] == 'WRONG_WINNER')
            analysis_run.blog_overlap_count = sum(1 for c in clustered_issues if c['bucket'] == 'BLOG_OVERLAP')
            
            # Count by badge
            analysis_run.confirmed_count = sum(1 for c in clustered_issues if c['badge'] == 'CONFIRMED')
            analysis_run.potential_count = sum(1 for c in clustered_issues if c['badge'] == 'POTENTIAL')
            analysis_run.wrong_winner_badge_count = sum(1 for c in clustered_issues if c['badge'] == 'WRONG_WINNER')
            
            analysis_run.mark_completed()
        
        return analysis_run
    
    except Exception as e:
        analysis_run.mark_failed(str(e))
        raise


def _fetch_gsc_data(site: Site, days: int = 90) -> list:
    """
    Fetch GSC data for the site.
    
    Returns list of dicts with keys: query, page, clicks, impressions, position
    """
    try:
        # Import GSC service (assumed to exist in the project)
        from integrations.gsc import get_gsc_data
        
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=days)
        
        # Fetch data (this is a placeholder - actual implementation depends on GSC integration)
        gsc_data = get_gsc_data(
            site=site,
            start_date=start_date,
            end_date=end_date,
            dimensions=['query', 'page'],
        )
        
        return gsc_data
    
    except ImportError:
        # GSC integration not available
        return []
    except Exception as e:
        # Log error but don't fail the entire analysis
        print(f"GSC fetch error: {e}")
        return []


def _fetch_gsc_daily_data(site: Site, days: int = 28) -> list:
    """
    Fetch daily GSC data for flip-flop detection.
    
    Returns list of dicts with keys: date, query, page, position, clicks, impressions
    """
    try:
        # Import GSC views helper
        from integrations.gsc_views import fetch_gsc_daily_data, _get_valid_access_token
        
        # Get valid access token
        access_token = _get_valid_access_token(site)
        if not access_token or not site.gsc_site_url:
            return []
        
        # Fetch daily data with date dimension
        daily_data = fetch_gsc_daily_data(
            access_token=access_token,
            site_url=site.gsc_site_url,
            days=days,
        )
        
        return daily_data
    
    except ImportError:
        # GSC integration not available
        return []
    except Exception as e:
        # Log error but don't fail the entire analysis
        print(f"GSC daily data fetch error: {e}")
        return []


def _get_brand_name(site: Site) -> str:
    """Get brand name from site metadata or onboarding."""
    # Try site metadata
    if hasattr(site, 'brand_name') and site.brand_name:
        return site.brand_name
    
    # Try to extract from site name
    if site.name:
        return site.name
    
    return ''


def _get_homepage_title(site: Site) -> str:
    """Get homepage title for brand extraction."""
    from seo.models import Page
    
    try:
        homepage = Page.objects.filter(site=site, is_homepage=True).first()
        if homepage:
            return homepage.title or ''
    except Exception:
        pass
    
    return ''


def get_latest_analysis(site_id: int):
    """Get the most recent completed analysis for a site."""
    try:
        return AnalysisRun.objects.filter(
            site_id=site_id,
            status='completed'
        ).order_by('-completed_at').first()
    except AnalysisRun.DoesNotExist:
        return None


def get_analysis_results(analysis_run_id: int) -> dict:
    """
    Get formatted results for an analysis run.
    
    Returns:
        {
            'analysis_run': AnalysisRun object,
            'clusters': list of ClusterResult objects,
            'summary': dict with counts and stats,
        }
    """
    try:
        analysis_run = AnalysisRun.objects.get(id=analysis_run_id)
    except AnalysisRun.DoesNotExist:
        return None
    
    clusters = ClusterResult.objects.filter(
        analysis_run=analysis_run
    ).order_by('-priority_score')
    
    summary = {
        'total_pages': analysis_run.total_pages_analyzed,
        'total_clusters': analysis_run.total_clusters_found,
        'gsc_connected': analysis_run.gsc_connected,
        'buckets': {
            'SEARCH_CONFLICT': analysis_run.search_conflict_count,
            'SITE_DUPLICATION': analysis_run.site_duplication_count,
            'WRONG_WINNER': analysis_run.wrong_winner_count,
            'BLOG_OVERLAP': analysis_run.blog_overlap_count,
        },
        'badges': {
            'CONFIRMED': analysis_run.confirmed_count,
            'POTENTIAL': analysis_run.potential_count,
            'WRONG_WINNER': analysis_run.wrong_winner_badge_count,
        },
    }
    
    return {
        'analysis_run': analysis_run,
        'clusters': list(clusters),
        'summary': summary,
    }
