"""
Context payload assembly — builds the JSON structure sent to the AI
from GSC data, WordPress page meta, and cannibalization cluster data.
"""
import logging
import statistics
from typing import Optional

logger = logging.getLogger(__name__)


def build_context_payload(action: str, cluster, site, pages_with_data: list) -> dict:
    """
    Build the context payload per the spec (Section 2.1).

    Args:
        action: merge_plan | spoke_rewrite | merge_draft | spoke_draft
        cluster: ClusterResult instance
        site: Site instance
        pages_with_data: list of dicts with page + seo_data + gsc info
    """
    total_clicks = sum(p.get('clicks', 0) for p in pages_with_data)
    total_impressions = sum(p.get('impressions', 0) for p in pages_with_data)

    # Calculate position volatility from all position trends
    all_positions = []
    for p in pages_with_data:
        trend = p.get('position_trend', [])
        if trend:
            all_positions.extend(trend)
    position_volatility = round(statistics.stdev(all_positions), 1) if len(all_positions) > 1 else 0

    conflict_pages = []
    for p in pages_with_data:
        page_clicks = p.get('clicks', 0)
        click_share = round((page_clicks / total_clicks * 100), 1) if total_clicks > 0 else 0
        position_trend = p.get('position_trend', [])
        page_volatility = round(statistics.stdev(position_trend), 1) if len(position_trend) > 1 else 0

        conflict_pages.append({
            'url': p.get('url', ''),
            'title': p.get('title', ''),
            'avg_position': p.get('avg_position', 0),
            'clicks': page_clicks,
            'impressions': p.get('impressions', 0),
            'ctr': p.get('ctr', 0),
            'click_share_pct': click_share,
            'position_trend': position_trend,
            'related_queries': p.get('related_queries', []),
            'wp_meta': {
                'h1': p.get('h1', ''),
                'meta_description': p.get('meta_description', ''),
                'focus_keyword': p.get('focus_keyword', ''),
                'word_count': p.get('word_count', 0),
                'internal_links_in': p.get('internal_links_in', 0),
                'internal_links_out': p.get('internal_links_out', 0),
                'schema_type': p.get('schema_type', ''),
            },
        })

    return {
        'action': action,
        'conflict': {
            'query': cluster.gsc_query or cluster.cluster_key,
            'total_clicks': total_clicks,
            'total_impressions': total_impressions,
            'position_volatility': position_volatility,
            'pages': conflict_pages,
        },
        'site_context': {
            'domain': site.url,
            'industry': site.business_type or 'unknown',
            'silo_health_score': 0,  # TODO: calculate from conflict data
            'total_pages': site.pages.count(),
        },
    }


def get_pages_with_data(cluster, site) -> list:
    """
    Extract page data from a ClusterResult, enriching with SEO data from the DB.
    Returns list of dicts ready for build_context_payload.
    """
    from seo.models import Page

    pages_data = []
    pages_json = cluster.pages_json or []
    gsc_data = cluster.gsc_data_json or {}

    # gsc_data may have per-page entries keyed by URL
    gsc_pages = gsc_data.get('pages', {}) if isinstance(gsc_data, dict) else {}

    for page_info in pages_json:
        page_url = page_info.get('url', '')

        # Try to find the Page in DB for WP meta
        page_obj = None
        seo_data = None
        try:
            page_obj = Page.objects.filter(site=site, url__icontains=page_url).first()
            if page_obj:
                seo_data = getattr(page_obj, 'seo_data', None)
        except Exception:
            pass

        # Get GSC data for this page
        page_gsc = gsc_pages.get(page_url, {})

        entry = {
            'url': page_url,
            'title': page_info.get('title', '') or (page_obj.title if page_obj else ''),
            'clicks': page_gsc.get('clicks', page_info.get('clicks', 0)),
            'impressions': page_gsc.get('impressions', page_info.get('impressions', 0)),
            'avg_position': page_gsc.get('position', page_info.get('position', 0)),
            'ctr': page_gsc.get('ctr', page_info.get('ctr', 0)),
            'position_trend': page_gsc.get('position_trend', []),
            'related_queries': page_gsc.get('related_queries', []),
            # WP meta from SEO data
            'h1': seo_data.h1_text if seo_data else '',
            'meta_description': seo_data.meta_description if seo_data else (
                page_obj.yoast_description if page_obj else ''
            ),
            'focus_keyword': '',
            'word_count': seo_data.word_count if seo_data else 0,
            'internal_links_in': seo_data.internal_links_count if seo_data else 0,
            'internal_links_out': seo_data.external_links_count if seo_data else 0,
            'schema_type': seo_data.schema_type if seo_data else '',
        }
        pages_data.append(entry)

    return pages_data
