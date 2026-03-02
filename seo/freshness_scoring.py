"""
Content Freshness Scoring
=========================
Scores how fresh/current a page's content is, flags stale pages,
and generates AI-powered update suggestions.

Data sources (all already in Siloq):
  - Page.modified_at       — last WP modified date from sync
  - PageAnalysis.gsc_data  — CTR trend from GSC
  - PageAnalysis.wp_meta   — word count, content snippet
  - Page.word_count        — for significant-change detection

No new external API calls. No new migrations.
"""

import re
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


# ── Scoring constants ─────────────────────────────────────────────────────────

STALE_YEAR_PATTERN = re.compile(
    r'\b(20(?:1[5-9]|2[0-2]))\b'   # years 2015–2022 in body text
)

STATIC_PATTERNS = [
    r'\blast\s+year\b',
    r'\bin\s+20(?:1[5-9]|2[0-2])\b',
    r'\brecently\s+(?:we|our|the)\b',  # "recently we updated" — signals it was once fresh
    r'\bnew\s+for\s+20(?:1[5-9]|2[0-2])\b',
    r'\bupdated\s+(?:in|for)\s+20(?:1[5-9]|2[0-2])\b',
]

FRESHNESS_LABELS = {
    'fresh':    {'min': 80, 'emoji': '✅', 'label': 'Fresh',    'color': 'green'},
    'ok':       {'min': 60, 'emoji': '🟢', 'label': 'OK',       'color': 'green'},
    'aging':    {'min': 40, 'emoji': '🟡', 'label': 'Aging',    'color': 'yellow'},
    'stale':    {'min': 20, 'emoji': '🟠', 'label': 'Stale',    'color': 'orange'},
    'outdated': {'min': 0,  'emoji': '🔴', 'label': 'Outdated', 'color': 'red'},
}


def _label_for_score(score: float) -> dict:
    for key in ('fresh', 'ok', 'aging', 'stale', 'outdated'):
        if score >= FRESHNESS_LABELS[key]['min']:
            return {**FRESHNESS_LABELS[key], 'score': round(score)}
    return {**FRESHNESS_LABELS['outdated'], 'score': round(score)}


# ── Component scorers ──────────────────────────────────────────────────────────

def _score_age(modified_at, word_count: int = 0) -> tuple:
    """
    Score based on days since last significant edit.
    Returns (sub_score 0-100, days_since_edit, note)
    """
    if not modified_at:
        return 40, None, 'Last modified date unknown — assuming aging.'

    now = datetime.now(timezone.utc)
    if hasattr(modified_at, 'tzinfo') and modified_at.tzinfo is None:
        modified_at = modified_at.replace(tzinfo=timezone.utc)
    elif not hasattr(modified_at, 'tzinfo'):
        return 40, None, 'Cannot parse modified date.'

    days = (now - modified_at).days

    # Score curve: 0-30 days = 100, degrades to 0 at 730 days (2 years)
    if days <= 30:
        score = 100
    elif days <= 90:
        score = 100 - ((days - 30) / 60) * 20    # 100 → 80
    elif days <= 180:
        score = 80 - ((days - 90) / 90) * 20     # 80 → 60
    elif days <= 365:
        score = 60 - ((days - 180) / 185) * 25   # 60 → 35
    elif days <= 730:
        score = 35 - ((days - 365) / 365) * 35   # 35 → 0
    else:
        score = 0

    note = f'Last edited {days} days ago ({modified_at.strftime("%b %d, %Y") if modified_at else "unknown"}).'
    return round(score), days, note


def _score_ctr_trend(gsc_data: dict) -> tuple:
    """
    Score based on CTR trend. Declining CTR = content going stale.
    Returns (sub_score 0-100, note)
    """
    if not gsc_data:
        return 50, 'No GSC data available.'

    clicks      = gsc_data.get('total_clicks', 0) or 0
    impressions = gsc_data.get('total_impressions', 0) or 0
    ctr         = gsc_data.get('average_ctr', 0) or 0

    if impressions == 0:
        return 40, 'No GSC impressions — page may not be indexed.'

    # If we have historical data, check trend
    historical = gsc_data.get('historical_ctr', [])  # list of {date, ctr} dicts
    if len(historical) >= 4:
        recent_avg   = sum(p.get('ctr', 0) for p in historical[-2:]) / 2
        older_avg    = sum(p.get('ctr', 0) for p in historical[:2]) / 2
        if older_avg > 0:
            trend = (recent_avg - older_avg) / older_avg
            if trend < -0.30:
                return 20, f'CTR dropped {abs(trend)*100:.0f}% — content likely losing relevance.'
            elif trend < -0.10:
                return 50, f'CTR declining ({trend*100:.0f}%) — monitor for staleness.'
            elif trend > 0.10:
                return 90, f'CTR improving ({trend*100:.0f}%) — content is resonating.'

    # Fallback: score on current CTR
    if ctr >= 0.05:
        return 85, f'CTR {ctr*100:.1f}% — performing well.'
    elif ctr >= 0.02:
        return 65, f'CTR {ctr*100:.1f}% — average performance.'
    elif ctr >= 0.005:
        return 40, f'CTR {ctr*100:.1f}% — below average, review content relevance.'
    else:
        return 20, f'CTR {ctr*100:.1f}% — very low, content may be misaligned with queries.'


def _score_static_patterns(content: str) -> tuple:
    """
    Score based on presence of outdated language patterns.
    Returns (sub_score 0-100, flags: list of str)
    """
    if not content:
        return 70, []

    flags = []
    text  = content.lower()

    # Stale year references
    year_matches = STALE_YEAR_PATTERN.findall(text)
    if year_matches:
        years = list(set(year_matches))
        flags.append(f'Contains outdated year references: {", ".join(years)}')

    # Static language patterns
    for pattern in STATIC_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            snippet = re.search(pattern, text, re.IGNORECASE)
            if snippet:
                flags.append(f'Potentially outdated phrasing detected near: "...{text[max(0,snippet.start()-20):snippet.end()+30]}..."')

    penalty = min(60, len(flags) * 20)
    score   = max(0, 100 - penalty)
    return score, flags


# ── Main freshness scorer ──────────────────────────────────────────────────────

def compute_freshness_score(page, latest_analysis=None) -> dict:
    """
    Compute a comprehensive freshness score for a page.

    Args:
        page:             Page model instance
        latest_analysis:  Most recent PageAnalysis for this page (optional)

    Returns:
        dict with score, label, components, flags, and recommendations.
    """
    modified_at  = getattr(page, 'modified_at', None)
    word_count   = getattr(page, 'word_count', 0) or 0
    gsc_data     = {}
    content      = ''

    if latest_analysis:
        gsc_data = latest_analysis.gsc_data or {}
        content  = (latest_analysis.wp_meta or {}).get('content_snippet', '') or ''

    # Component scores
    age_score,   days_since_edit, age_note       = _score_age(modified_at, word_count)
    ctr_score,   ctr_note                         = _score_ctr_trend(gsc_data)
    static_score, static_flags                    = _score_static_patterns(content)

    # Weighted composite
    # Age: 45% — most important freshness signal
    # CTR: 35% — engagement-based freshness
    # Static patterns: 20% — language quality signal
    composite = (age_score * 0.45) + (ctr_score * 0.35) + (static_score * 0.20)

    label_info = _label_for_score(composite)
    warning    = composite < 60

    recommendations = _freshness_recommendations(
        composite, age_score, days_since_edit, ctr_score, static_flags, page
    )

    return {
        'score':        label_info['score'],
        'label':        label_info['label'],
        'emoji':        label_info['emoji'],
        'color':        label_info['color'],
        'warning':      warning,
        'components': {
            'age': {
                'score': age_score,
                'weight': 0.45,
                'days_since_edit': days_since_edit,
                'last_modified': modified_at.isoformat() if modified_at and hasattr(modified_at, 'isoformat') else None,
                'note': age_note,
            },
            'ctr_trend': {
                'score': ctr_score,
                'weight': 0.35,
                'note': ctr_note,
            },
            'static_patterns': {
                'score': static_score,
                'weight': 0.20,
                'flags': static_flags,
            },
        },
        'outdated_flags': static_flags,
        'recommendations': recommendations,
    }


def _freshness_recommendations(composite, age_score, days_since_edit, ctr_score, static_flags, page) -> list:
    recs = []

    if days_since_edit and days_since_edit > 365:
        recs.append(
            f'This page hasn\'t been meaningfully updated in over a year. '
            f'Google now penalizes static content. Review and update the core body copy.'
        )
    elif days_since_edit and days_since_edit > 180:
        recs.append(
            'This page is 6+ months old with no significant edits. '
            'Add a "Last updated" date, refresh any statistics or references, and expand the content.'
        )

    if ctr_score < 40:
        recs.append(
            'CTR is declining — the page\'s title tag and meta description may no longer match '
            'what searchers are looking for. Update both to reflect current search intent.'
        )

    for flag in static_flags[:2]:  # Top 2 flags only
        if 'year' in flag.lower():
            recs.append(
                'Replace outdated year references (e.g. "in 2021") with current year or '
                'relative language ("this year", "currently"). '
                'Year references signal to Google the content is not maintained.'
            )
            break

    if composite < 40 and not recs:
        recs.append(
            'This page scores low on freshness across all signals. '
            'A full content refresh — adding new sections, updating stats, and improving the intro — '
            'is recommended.'
        )

    return recs


# ── Bulk freshness for a site ──────────────────────────────────────────────────

def compute_site_freshness_summary(pages_with_analyses: list) -> dict:
    """
    Compute freshness scores for a list of (page, analysis) tuples.
    Returns summary stats and per-page scores sorted by staleness.
    """
    scores = []
    for page, analysis in pages_with_analyses:
        result = compute_freshness_score(page, analysis)
        scores.append({
            'page_id':  page.id,
            'page_url': page.url,
            'title':    page.title,
            **result,
        })

    scores.sort(key=lambda x: x['score'])  # Most stale first

    stale_count  = sum(1 for s in scores if s['score'] < 40)
    aging_count  = sum(1 for s in scores if 40 <= s['score'] < 60)
    fresh_count  = sum(1 for s in scores if s['score'] >= 60)
    avg_score    = sum(s['score'] for s in scores) / len(scores) if scores else 0

    return {
        'site_freshness_score': round(avg_score),
        'total_pages':  len(scores),
        'stale_pages':  stale_count,
        'aging_pages':  aging_count,
        'fresh_pages':  fresh_count,
        'pages':        scores,
    }
