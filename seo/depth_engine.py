"""
Topical Depth & Semantic Closure Engine — scoring, subtopic generation,
freshness monitoring, and link relationship classification.
"""
import json
import logging
import re
from datetime import timedelta
from difflib import SequenceMatcher

import anthropic
from django.conf import settings
from django.db import models
from django.utils import timezone

from seo.models import (
    ContentDecayLog,
    InternalLink,
    Page,
    SemanticLinkRelationship,
    SiloDefinition,
    SiloDepthScore,
    SiloTopicBoundary,
    SubtopicMap,
)
from sites.models import Site

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# ENTITY TYPE MAPPING
# ─────────────────────────────────────────────────────────────

ENTITY_TYPE_MAP = {
    # local_business → 180d warning, 365d critical
    'local_service': 'local_business',
    'local_service_multi': 'local_business',
    'electrical': 'local_business',
    'plumbing': 'local_business',
    'hvac': 'local_business',
    'roofing': 'local_business',
    'dental': 'local_business',
    'medical': 'local_business',
    'medical_practice': 'local_business',
    'restaurant': 'local_business',
    'event_venue': 'local_business',
    # ecommerce → 120d warning, 240d critical
    'ecommerce': 'ecommerce',
    'retail': 'ecommerce',
    # publisher → 90d warning, 180d critical
    'blog': 'publisher',
    'news': 'publisher',
    'publisher': 'publisher',
    'content_publisher': 'publisher',
    # b2b → 180d warning, 365d critical
    'saas': 'b2b',
    'b2b': 'b2b',
    'agency': 'b2b',
}

FRESHNESS_THRESHOLDS = {
    'local_business': {'warning': 180, 'critical': 365},
    'ecommerce':      {'warning': 120, 'critical': 240},
    'publisher':      {'warning': 90,  'critical': 180},
    'b2b':            {'warning': 180, 'critical': 365},
}


def get_entity_type(site, silo_boundary=None) -> str:
    """
    Returns the 4-way entity type for a site.
    Checks silo_topic_boundaries.entity_type_override first (per-silo override),
    falls back to sites.business_type → ENTITY_TYPE_MAP → defaults to 'local_business'.
    """
    if silo_boundary and silo_boundary.entity_type_override:
        return silo_boundary.entity_type_override

    business_type = getattr(site, 'business_type', '') or ''
    return ENTITY_TYPE_MAP.get(business_type, 'local_business')


def get_freshness_thresholds(entity_type: str) -> dict:
    return FRESHNESS_THRESHOLDS.get(entity_type, FRESHNESS_THRESHOLDS['local_business'])


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def get_silo_pages(silo_id: str, site_id: int):
    """Return all published pages assigned to a silo via PageMetadata."""
    from seo.models import PageMetadata
    page_ids = PageMetadata.objects.filter(
        silo_id=silo_id, page__site_id=site_id,
    ).values_list('page_id', flat=True)
    return list(Page.objects.filter(id__in=page_ids, status='publish'))


def get_silo_page_ids(silo_id: str, site_id: int) -> list:
    """Return list of page IDs in a silo."""
    from seo.models import PageMetadata
    return list(PageMetadata.objects.filter(
        silo_id=silo_id, page__site_id=site_id,
    ).values_list('page_id', flat=True))


def get_hub_page_id(silo_id: str, site_id: int):
    """Return the hub (target) page ID for a silo, or None."""
    try:
        silo = SiloDefinition.objects.get(id=silo_id, site_id=site_id)
        return silo.target_page_id
    except SiloDefinition.DoesNotExist:
        return None


def count_connected_pages(silo_id: str, site_id: int) -> int:
    """Count pages that have at least one internal link to/from the hub."""
    hub_page_id = get_hub_page_id(silo_id, site_id)
    if not hub_page_id:
        return 0

    silo_page_ids = get_silo_page_ids(silo_id, site_id)
    connected = set()
    links = InternalLink.objects.filter(
        site_id=site_id,
    ).filter(
        models.Q(source_page_id=hub_page_id, target_page_id__in=silo_page_ids) |
        models.Q(target_page_id=hub_page_id, source_page_id__in=silo_page_ids)
    ).values_list('source_page_id', 'target_page_id')

    for src, tgt in links:
        if src == hub_page_id:
            connected.add(tgt)
        else:
            connected.add(src)
    return len(connected)


def count_disconnected_pages(silo_id: str, site_id: int) -> int:
    """Count pages with zero internal links to/from any other silo page."""
    silo_page_ids = get_silo_page_ids(silo_id, site_id)
    if not silo_page_ids:
        return 0

    linked_pages = set()
    links = InternalLink.objects.filter(
        site_id=site_id,
        source_page_id__in=silo_page_ids,
        target_page_id__in=silo_page_ids,
    ).values_list('source_page_id', 'target_page_id')

    for src, tgt in links:
        linked_pages.add(src)
        linked_pages.add(tgt)

    return len(set(silo_page_ids) - linked_pages)


def detect_scope_creep(silo_id: str, site_id: int) -> bool:
    """
    Detect scope creep: if > 30% of subtopics are 'adjacent' or 'edge_case' type.
    """
    subtopics = SubtopicMap.objects.filter(silo_id=silo_id, site_id=site_id)
    total = subtopics.count()
    if total == 0:
        return False
    edge_count = subtopics.filter(subtopic_type__in=['adjacent', 'edge_case']).count()
    return (edge_count / total) > 0.30


def detect_depth_mistakes(silo_id, site_id, thin_count, total_pages, disconnected, scope_creep_flag) -> list:
    """Generate a list of depth mistake flag objects."""
    flags = []
    if total_pages > 0 and thin_count / total_pages > 0.30:
        flags.append({
            'type': 'high_thin_ratio',
            'message': f'{thin_count}/{total_pages} pages are thin (> 30%)',
            'severity': 'warning',
        })
    if total_pages > 0 and disconnected / total_pages > 0.20:
        flags.append({
            'type': 'disconnected_pages',
            'message': f'{disconnected}/{total_pages} pages have no internal links within silo',
            'severity': 'warning',
        })
    if scope_creep_flag:
        flags.append({
            'type': 'scope_creep',
            'message': 'Over 30% of subtopics are adjacent/edge-case — possible topical drift',
            'severity': 'warning',
        })

    missing_core = SubtopicMap.objects.filter(
        silo_id=silo_id, site_id=site_id,
        subtopic_type='core', coverage_status='missing',
    ).count()
    if missing_core > 0:
        flags.append({
            'type': 'missing_core_subtopics',
            'message': f'{missing_core} core subtopic(s) have no page coverage',
            'severity': 'critical',
        })
    return flags


def find_matching_page(subtopic: dict, existing_pages) -> Page | None:
    """Fuzzy-match a subtopic label/slug against existing page titles/URLs."""
    label = subtopic.get('subtopic_label', '').lower()
    slug = subtopic.get('subtopic_slug', '').lower()

    best_match = None
    best_score = 0.0

    for page in existing_pages:
        title = (page.get('title', '') if isinstance(page, dict) else page.title).lower()
        url = (page.get('url', '') if isinstance(page, dict) else page.url).lower()

        title_score = SequenceMatcher(None, label, title).ratio()
        slug_score = SequenceMatcher(None, slug, url.rstrip('/').split('/')[-1]).ratio()
        score = max(title_score, slug_score)

        if score > best_score:
            best_score = score
            best_match = page

    if best_score >= 0.55:
        if isinstance(best_match, dict):
            page_id = best_match.get('id')
            try:
                return Page.objects.get(id=page_id)
            except Page.DoesNotExist:
                return None
        return best_match
    return None


def assess_page_depth(page) -> str:
    """Assess whether a page is 'covered' or 'thin'."""
    content = page.content if isinstance(page, Page) else ''
    if not content:
        return 'thin'
    word_count = len(content.split())
    has_h2 = '<h2' in content.lower()
    if word_count < 300 or not has_h2:
        return 'thin'
    return 'covered'


def count_thin_pages(silo_id: str, site_id: int) -> int:
    """
    A page is thin if:
    - word count < 300 (computed from pages.content)
    - OR no H2 headings in content
    - OR no internal links to/from hub
    """
    pages = get_silo_pages(silo_id, site_id)
    hub_page_id = get_hub_page_id(silo_id, site_id)
    thin = 0
    for page in pages:
        wc = len(page.content.split()) if page.content else 0
        has_h2 = '<h2' in (page.content or '').lower()
        has_hub_link = False
        if hub_page_id:
            has_hub_link = InternalLink.objects.filter(
                site_id=site_id,
            ).filter(
                models.Q(source_page_id=page.id, target_page_id=hub_page_id) |
                models.Q(target_page_id=page.id, source_page_id=hub_page_id)
            ).exists()
        if wc < 300 or not has_h2 or not has_hub_link:
            thin += 1
    return thin


def create_approaching_notification(site, page, days_old, warning_threshold):
    """Create a FreshnessAlert for pages approaching decay threshold."""
    from seo.models import FreshnessAlert
    try:
        FreshnessAlert.objects.update_or_create(
            site=site,
            page=page,
            alert_type='approaching_decay',
            is_resolved=False,
            defaults={
                'message': (
                    f'Page "{page.title}" was last updated {days_old} days ago '
                    f'(warning threshold: {warning_threshold} days)'
                ),
            },
        )
    except Exception as e:
        logger.warning(f"Could not create approaching notification for page {page.id}: {e}")


def extract_link_context(link) -> str:
    """Extract ~50-word context window around anchor text from source page content."""
    content = link.source_page.content or ''
    anchor = link.anchor_text or ''
    if not anchor or not content:
        return ''

    # Strip HTML tags for context extraction
    text = re.sub(r'<[^>]+>', ' ', content)
    text = re.sub(r'\s+', ' ', text).strip()

    idx = text.lower().find(anchor.lower())
    if idx == -1:
        return ''

    words = text.split()
    # Find approximate word position
    char_count = 0
    word_idx = 0
    for i, word in enumerate(words):
        char_count += len(word) + 1
        if char_count >= idx:
            word_idx = i
            break

    start = max(0, word_idx - 25)
    end = min(len(words), word_idx + 25)
    return ' '.join(words[start:end])


def classify_link_relationship(anchor_text, context, source_topic, target_topic) -> str:
    """Use Claude to classify a link's semantic relationship type."""
    prompt = (
        "Classify the semantic relationship of this internal link.\n\n"
        f"Anchor text: {anchor_text}\n"
        f"Surrounding context: {context}\n"
        f"Source page topic: {source_topic}\n"
        f"Target page topic: {target_topic}\n\n"
        "Return ONLY one word: hierarchical | sequential | comparative | "
        "complementary | prerequisite | evidence | unclassified"
    )
    try:
        api_key = getattr(settings, 'ANTHROPIC_API_KEY', None)
        if not api_key:
            return 'unclassified'
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=20,
            messages=[{"role": "user", "content": prompt}],
        )
        result = message.content[0].text.strip().lower()
        valid = {'hierarchical', 'sequential', 'comparative', 'complementary', 'prerequisite', 'evidence', 'unclassified'}
        return result if result in valid else 'unclassified'
    except Exception as e:
        logger.error(f"Link classification failed: {e}")
        return 'unclassified'


def build_brief_prompt(subtopic, boundary) -> str:
    """Build the AI brief prompt for a subtopic gap."""
    if subtopic.subtopic_type == 'evidence':
        return (
            f"Write a case study / project example page for {subtopic.subtopic_label} "
            f"for a {boundary.effective_entity_type}. "
            "Required: specific service performed, location/city, specific job detail, outcome, timeframe. "
            "Do not write generically. If specific details not provided, output structured template with [PLACEHOLDER] fields. "
            "Do not fabricate specifics."
        )

    location = ''
    try:
        profile = boundary.site.entity_profile
        location = getattr(profile, 'service_areas', [''])[0] if profile.service_areas else ''
    except Exception:
        pass

    return (
        f"Write a comprehensive page for {subtopic.subtopic_label} as a spoke within the "
        f"{boundary.core_topic} silo for a {boundary.effective_entity_type} in {location}. "
        "Achieve semantic closure on this specific subtopic — answer all common user questions. "
        "Minimum 600 words. Include relevant H2 structure, internal link to hub page."
    )


def reassess_subtopic_coverage(silo_id: str, site_id: int):
    """Re-check coverage status for all subtopics in a silo."""
    subtopics = SubtopicMap.objects.filter(silo_id=silo_id, site_id=site_id)
    silo_pages = get_silo_pages(silo_id, site_id)
    page_dicts = [{'id': p.id, 'title': p.title, 'url': p.url} for p in silo_pages]

    for subtopic in subtopics:
        matched = find_matching_page(
            {'subtopic_label': subtopic.subtopic_label, 'subtopic_slug': subtopic.subtopic_slug},
            page_dicts,
        )
        if matched:
            page_obj = matched if isinstance(matched, Page) else Page.objects.filter(id=matched['id']).first()
            if page_obj:
                depth = assess_page_depth(page_obj)
                # Check staleness
                if page_obj.modified_at:
                    boundary = SiloTopicBoundary.objects.filter(silo_id=silo_id, site_id=site_id).first()
                    if boundary:
                        entity_type = boundary.effective_entity_type
                        thresholds = get_freshness_thresholds(entity_type)
                        days_old = (timezone.now() - page_obj.modified_at).days
                        if days_old >= thresholds['warning']:
                            depth = 'stale'

                subtopic.coverage_status = depth
                subtopic.mapped_page = page_obj
            else:
                subtopic.coverage_status = 'missing'
                subtopic.mapped_page = None
        else:
            subtopic.coverage_status = 'missing'
            subtopic.mapped_page = None
        subtopic.last_assessed = timezone.now()
        subtopic.save()


# ─────────────────────────────────────────────────────────────
# SUBTOPIC MAP GENERATION (AI-driven)
# ─────────────────────────────────────────────────────────────

SUBTOPIC_GENERATION_PROMPT = """You are an SEO topic authority analyst. Generate a comprehensive subtopic map.

Core Topic: {core_topic}
Entity Type: {entity_type}
Adjacent In-Scope Topics: {adjacent_topics}
Existing Pages in Silo: {page_titles_and_urls}

Generate ALL subtopics needed to achieve topical closure on "{core_topic}" as a {entity_type}.

Return ONLY a JSON array, no preamble, no markdown. Each item:
{{
  "subtopic_label": "string",
  "subtopic_slug": "url-friendly-string",
  "subtopic_type": "core|supporting|adjacent|edge_case|comparative|evidence",
  "priority_score": 1-100,
  "rationale": "one sentence"
}}

Include a subtopic if:
- It's a common user question in this topic domain
- It's a variation, edge case, or specific application of the core topic
- A topical authority on {core_topic} would be expected to cover it

Exclude if:
- It requires different domain expertise
- It matches out_of_scope_topics: {out_of_scope_topics}
- It would dilute the entity's topical identity
"""


def generate_subtopic_map(silo_id: str, site_id: int) -> list:
    """
    AI-driven subtopic map generation. Called as background job.
    Returns list of subtopic records inserted into subtopic_map table.
    """
    boundary = SiloTopicBoundary.objects.get(silo_id=silo_id, site_id=site_id)
    from seo.models import PageMetadata
    page_ids = PageMetadata.objects.filter(
        silo_id=silo_id, page__site_id=site_id,
    ).values_list('page_id', flat=True)
    existing_pages = list(Page.objects.filter(
        id__in=page_ids, status='publish',
    ).values('id', 'title', 'url'))

    prompt = SUBTOPIC_GENERATION_PROMPT.format(
        core_topic=boundary.core_topic,
        entity_type=boundary.effective_entity_type,
        adjacent_topics=json.dumps(boundary.adjacent_topics),
        page_titles_and_urls=json.dumps(existing_pages),
        out_of_scope_topics=json.dumps(boundary.out_of_scope_topics),
    )

    api_key = getattr(settings, 'ANTHROPIC_API_KEY', None)
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=4096,
        system="You are an SEO subtopic analyst. Always respond with valid JSON only.",
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    # Strip markdown code fences if present
    if raw.startswith('```'):
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
    subtopics = json.loads(raw)

    for subtopic in subtopics:
        matched_page = find_matching_page(subtopic, existing_pages)
        if matched_page:
            page_obj = matched_page if isinstance(matched_page, Page) else Page.objects.filter(id=matched_page['id']).first()
            coverage_status = assess_page_depth(page_obj) if page_obj else 'missing'
            mapped_page_id = page_obj.id if page_obj else None
        else:
            coverage_status = 'missing'
            mapped_page_id = None

        SubtopicMap.objects.update_or_create(
            silo_id=silo_id,
            subtopic_slug=subtopic['subtopic_slug'],
            defaults={
                'site_id': site_id,
                'subtopic_label': subtopic['subtopic_label'],
                'subtopic_type': subtopic.get('subtopic_type', 'supporting'),
                'coverage_status': coverage_status,
                'mapped_page_id': mapped_page_id,
                'priority_score': subtopic.get('priority_score', 50),
                'last_assessed': timezone.now(),
            },
        )

    return list(SubtopicMap.objects.filter(silo_id=silo_id, site_id=site_id))


# ─────────────────────────────────────────────────────────────
# DEPTH SCORING
# ─────────────────────────────────────────────────────────────

def score_silo_depth(silo_id: str, site_id: int) -> SiloDepthScore | None:
    subtopics = SubtopicMap.objects.filter(silo_id=silo_id, site_id=site_id)
    total = subtopics.count()
    if total == 0:
        return None

    covered_or_thin = subtopics.filter(coverage_status__in=['covered', 'thin']).count()
    covered_only = subtopics.filter(coverage_status='covered').count()

    # Component 1: Coverage Breadth (30 pts)
    breadth_score = (covered_or_thin / total) * 30

    # Component 2: Coverage Depth (35 pts)
    depth_score = (covered_only / total) * 35

    # Component 3: Freshness (20 pts)
    boundary = SiloTopicBoundary.objects.get(silo_id=silo_id, site_id=site_id)
    entity_type = boundary.effective_entity_type
    thresholds = get_freshness_thresholds(entity_type)
    warning_days = thresholds['warning']

    silo_pages = get_silo_pages(silo_id, site_id)
    total_pages = len(silo_pages)
    cutoff = timezone.now() - timedelta(days=warning_days)
    fresh_pages = [p for p in silo_pages if p.modified_at and p.modified_at >= cutoff]
    freshness_score = (len(fresh_pages) / total_pages * 20) if total_pages > 0 else 0

    # Component 4: Structural Connectivity (15 pts)
    connected = count_connected_pages(silo_id, site_id)
    connectivity_score = min((connected / total_pages * 15), 15) if total_pages > 0 else 0
    scope_creep_flag = detect_scope_creep(silo_id, site_id)
    if scope_creep_flag:
        connectivity_score = max(0, connectivity_score - 5)

    semantic_density = round(breadth_score + depth_score + freshness_score + connectivity_score)

    # Topical Closure Score
    high_priority = subtopics.filter(priority_score__gte=70)
    hp_total = high_priority.count()
    hp_covered = high_priority.filter(coverage_status='covered').count()
    hp_closure = hp_covered / hp_total if hp_total > 0 else 0
    total_coverage = covered_only / total

    closure_score = ((hp_closure * 0.60) + (total_coverage * 0.40)) * 100

    # Penalties
    if subtopics.filter(priority_score=100, coverage_status='missing').exists():
        closure_score -= 10
    critical_decay = ContentDecayLog.objects.filter(
        silo_id=silo_id, site_id=site_id, decay_severity='critical', resolved_at__isnull=True,
    ).count()
    closure_score -= min(critical_decay * 5, 20)
    disconnected = count_disconnected_pages(silo_id, site_id)
    if total_pages > 0 and disconnected / total_pages > 0.20:
        closure_score -= 5

    closure_score = max(0, min(100, round(closure_score)))

    thin_count = count_thin_pages(silo_id, site_id)
    stale_count = subtopics.filter(coverage_status='stale').count()
    missing_count = subtopics.filter(coverage_status='missing').count()

    mistake_flags = detect_depth_mistakes(
        silo_id, site_id, thin_count, total_pages, disconnected, scope_creep_flag,
    )

    # Normalize freshness to 0-100
    freshness_normalized = round(freshness_score * 5)

    return SiloDepthScore.objects.create(
        site_id=site_id,
        silo_id=silo_id,
        semantic_density_score=semantic_density,
        topical_closure_score=closure_score,
        coverage_breadth_pct=round(covered_or_thin / total * 100, 2) if total > 0 else 0,
        coverage_depth_pct=round(covered_only / total * 100, 2) if total > 0 else 0,
        thin_page_count=thin_count,
        missing_subtopic_count=missing_count,
        stale_page_count=stale_count,
        scope_creep_flag=scope_creep_flag,
        disconnected_page_count=disconnected,
        freshness_score=freshness_normalized,
        depth_mistake_flags=mistake_flags,
    )


# ─────────────────────────────────────────────────────────────
# LINK RELATIONSHIP ASSESSMENT
# ─────────────────────────────────────────────────────────────

def assess_link_relationships(site_id: int, silo_id: str) -> dict:
    """On-demand. Hard cap: 200 links per run."""
    silo_page_ids = get_silo_page_ids(silo_id, site_id)
    links = InternalLink.objects.filter(
        site_id=site_id,
        source_page_id__in=silo_page_ids,
    ).select_related('source_page', 'target_page')[:200]

    total_in_silo = InternalLink.objects.filter(
        site_id=site_id, source_page_id__in=silo_page_ids,
    ).count()

    classified = []
    for link in links:
        context = extract_link_context(link)
        rel_type = classify_link_relationship(
            anchor_text=link.anchor_text or '',
            context=context,
            source_topic=link.source_page.title,
            target_topic=link.target_page.title if link.target_page else '',
        )

        SemanticLinkRelationship.objects.update_or_create(
            source_page_id=link.source_page_id,
            target_page_id=link.target_page_id,
            defaults={
                'site_id': site_id,
                'relationship_type': rel_type,
                'anchor_text': (link.anchor_text or '')[:500],
                'anchor_context': context,
                'relationship_confidence': 'medium',
                'assessed_at': timezone.now(),
            },
        )
        classified.append({'link_id': link.id, 'type': rel_type})

    quality_count = sum(1 for c in classified if c['type'] != 'unclassified')

    message = f"Assessed {len(classified)} of {total_in_silo} links."
    if total_in_silo > 200:
        message += f" Run again to assess remaining {total_in_silo - 200} links."

    return {
        'assessed': len(classified),
        'total_in_silo': total_in_silo,
        'quality_ratio': round(quality_count / len(classified) * 100, 1) if classified else 0,
        'message': message,
    }


# ─────────────────────────────────────────────────────────────
# DECAY MONITORING (daily)
# ─────────────────────────────────────────────────────────────

def run_freshness_monitor():
    """Daily job. Check pages approaching decay threshold."""
    for site in Site.objects.filter(is_active=True):
        boundaries = SiloTopicBoundary.objects.filter(site=site)
        for boundary in boundaries:
            entity_type = boundary.effective_entity_type
            thresholds = get_freshness_thresholds(entity_type)
            pages = get_silo_pages(str(boundary.silo_id), site.id)

            for page in pages:
                if not page.modified_at:
                    continue
                days_old = (timezone.now() - page.modified_at).days

                severity = None
                if days_old >= thresholds['critical']:
                    severity = 'critical'
                elif days_old >= thresholds['warning']:
                    severity = 'warning'
                elif days_old >= thresholds['warning'] - 30:
                    create_approaching_notification(site, page, days_old, thresholds['warning'])
                    continue
                else:
                    continue

                ContentDecayLog.objects.update_or_create(
                    site=site, page=page, silo_id=boundary.silo_id,
                    resolved_at__isnull=True,
                    defaults={
                        'last_modified': page.modified_at.date(),
                        'days_since_update': days_old,
                        'decay_severity': severity,
                    },
                )


def run_weekly_depth_scan():
    """Weekly job. Re-score all silos with defined topic boundaries."""
    for boundary in SiloTopicBoundary.objects.select_related('site', 'silo').all():
        try:
            reassess_subtopic_coverage(str(boundary.silo_id), boundary.site_id)
            score_silo_depth(str(boundary.silo_id), boundary.site_id)
        except Exception as e:
            logger.error(f"Depth scan failed for silo {boundary.silo_id}: {e}")
            continue


def purge_old_decay_logs():
    """Purge resolved decay entries older than 90 days."""
    cutoff = timezone.now() - timedelta(days=90)
    deleted, _ = ContentDecayLog.objects.filter(resolved_at__lt=cutoff).delete()
    logger.info(f"Purged {deleted} old decay log entries")
