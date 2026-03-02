"""
Phase 0.5: Entity Extraction

Pre-processing phase that extracts and classifies named entities from every
page BEFORE any overlap comparisons run.  This eliminates false positives
caused by token-level matching — e.g. two pages that both contain "jacket"
should NOT be flagged as conflicts when they sell completely different
products (VIP Jacket vs All Star Jacket) within the same brand line.

Design decisions:
- ONE Claude API call per site (batch all pages), not one call per page
- Results stored in PageClassification.entities (JSONField)
- Re-extract only when title or URL changes (compare md5 hash)
- Falls back gracefully when ANTHROPIC_API_KEY is not configured

Entity types:
  brand          — manufacturer / company name (Chasse, Nike, Kohler)
  brand_line     — brand + specific product line (Chasse Performance, Nike Dri-FIT)
  product_name   — specific product identifier (VIP Jacket, All Star Jacket)
  product_category — generic product type (jacket, uniform, jersey)
  service_type   — service offering (kitchen remodeling, emergency plumbing)
  location       — geographic entity (Kansas City, Downtown, Overland Park)
  descriptor     — generic modifier (custom, professional, best, affordable)
  sport_filter   — sport or activity category (cheer, dance, football)
"""

import hashlib
import json
import logging
import os
import re
from typing import List, Optional

from .models import PageClassification

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
ANTHROPIC_MODEL = 'claude-sonnet-4-20250514'
MAX_TOKENS = 8192

# ---------------------------------------------------------------------------
# System prompt (sent once per batch call)
# ---------------------------------------------------------------------------

ENTITY_EXTRACTION_PROMPT = """You are an SEO entity classifier. Given a list of web pages (URL, title, H1, meta description), extract and classify the named entities on each page.

Entity types: brand, brand_line, product_name, product_category, service_type, location, descriptor, sport_filter

Rules:
- If two or more consecutive words form a brand or product line name, keep them as ONE entity ("Chasse Performance" not "Chasse" + "Performance")
- Product names are specific identifiers that distinguish one product from another within the same line ("VIP Jacket" vs "All Star Jacket")
- When uncertain if something is a brand, check: does it appear as a proper noun across multiple pages? If the same capitalized term appears in multiple product titles, it's likely a brand or brand_line
- Service types are what the business does ("kitchen remodeling", "emergency plumbing", "teeth whitening")
- Descriptors are generic modifiers that don't identify a specific entity ("custom", "best", "professional", "affordable")

Return a JSON array with one object per page:
[
  {
    "url": "/page-slug",
    "entities": [
      {"text": "Chasse Performance", "type": "brand_line", "confidence": 0.95},
      {"text": "VIP Jacket", "type": "product_name", "confidence": 0.90},
      {"text": "Jacket", "type": "product_category", "confidence": 0.85}
    ]
  }
]"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_phase0_entity_extraction(classifications: List[PageClassification]) -> None:
    """
    Phase 0.5 entry point — called from the pipeline after Phase 1.

    Extracts named entities for all classifications in one batched Claude
    call and updates each PageClassification.entities in-place.
    Persists results to the DB with a bulk_update.

    Args:
        classifications: List of PageClassification objects (already saved).
    """
    if not classifications:
        return

    if not ANTHROPIC_API_KEY:
        logger.warning(
            "Phase 0.5 skipped: ANTHROPIC_API_KEY not configured. "
            "Set ANTHROPIC_API_KEY to enable entity extraction."
        )
        return

    # Build page payloads for the batch call
    pages_payload = _build_page_payloads(classifications)

    if not pages_payload:
        return

    try:
        extracted = _call_claude_batch(pages_payload)
    except Exception as exc:
        logger.error("Phase 0.5 entity extraction failed: %s", exc, exc_info=True)
        return

    # Map extracted entities back to PageClassification objects
    entity_map = {item['url']: item.get('entities', []) for item in extracted}

    updated = []
    for pc in classifications:
        path = _normalized_path(pc.url)
        if path in entity_map:
            pc.entities = entity_map[path]
            updated.append(pc)

    if updated:
        PageClassification.objects.bulk_update(updated, ['entities'])
        logger.info(
            "Phase 0.5: extracted entities for %d/%d pages",
            len(updated),
            len(classifications),
        )


def extract_entities_for_pages(pages: List[dict]) -> List[dict]:
    """
    Public helper — extract entities for an arbitrary list of page dicts.

    Used by the API endpoint POST /api/v1/sites/{site_id}/pages/extract-entities/

    Args:
        pages: List of dicts with keys: url, title, h1, meta

    Returns:
        List of dicts: [{"url": ..., "entities": [...]}, ...]

    Raises:
        RuntimeError: if ANTHROPIC_API_KEY is not configured
        Exception: propagated from Anthropic API on failure
    """
    if not pages:
        return []

    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not configured. "
            "Set this environment variable to enable entity extraction."
        )

    return _call_claude_batch(pages)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_page_payloads(classifications: List[PageClassification]) -> List[dict]:
    """Convert PageClassification objects to lightweight page dicts."""
    return [
        {
            'url': _normalized_path(pc.url),
            'title': pc.title or '',
            'h1': pc.title or '',   # Phase 1 doesn't separately store H1; use title as proxy
            'meta': '',             # Not stored in PageClassification; omit
        }
        for pc in classifications
        if pc.url
    ]


def _normalized_path(url: str) -> str:
    """
    Extract the path component from a URL for use as the entity map key.

    Examples:
        'https://example.com/chasse-performance-vip-jacket/' → '/chasse-performance-vip-jacket/'
        '/products/vip-jacket'                               → '/products/vip-jacket'
    """
    from urllib.parse import urlparse
    parsed = urlparse(url)
    path = parsed.path or '/'
    if not path.endswith('/'):
        path = path + '/'
    return path


def _call_claude_batch(pages: List[dict]) -> List[dict]:
    """
    Send one batched Claude API call for all pages.

    Args:
        pages: List of dicts with keys: url, title, h1, meta

    Returns:
        Parsed JSON array from Claude's response.

    Raises:
        RuntimeError: if the response cannot be parsed as a valid JSON array.
    """
    import anthropic  # deferred import — optional dependency

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    user_message = (
        "Here are the pages to classify:\n\n"
        + json.dumps(pages, indent=2)
    )

    message = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=MAX_TOKENS,
        temperature=0.1,   # Low temperature for classification accuracy
        system=ENTITY_EXTRACTION_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw_text = "".join(
        block.text for block in message.content if block.type == "text"
    )

    return _parse_entity_response(raw_text)


def _parse_entity_response(raw_text: str) -> List[dict]:
    """
    Parse Claude's response into a list of page-entity dicts.

    Handles both clean JSON arrays and markdown-fenced JSON blocks.

    Returns:
        List of dicts: [{"url": ..., "entities": [...]}, ...]

    Raises:
        ValueError: if the response cannot be parsed as a JSON array.
    """
    # Strip markdown code fences
    cleaned = re.sub(r'```(?:json)?\s*', '', raw_text).strip()
    cleaned = cleaned.rstrip('`').strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        # Attempt to extract just the JSON array portion
        match = re.search(r'\[.*\]', cleaned, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                raise ValueError(
                    f"Phase 0.5: Could not parse Claude entity response as JSON array. "
                    f"Raw text (first 500 chars): {raw_text[:500]}"
                ) from exc
        else:
            raise ValueError(
                f"Phase 0.5: No JSON array found in Claude response. "
                f"Raw text (first 500 chars): {raw_text[:500]}"
            ) from exc

    if not isinstance(parsed, list):
        raise ValueError(
            f"Phase 0.5: Expected JSON array, got {type(parsed).__name__}. "
            f"Raw text (first 500 chars): {raw_text[:500]}"
        )

    # Validate and normalise each entry
    result = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        url = item.get('url', '')
        entities = item.get('entities', [])
        if not isinstance(entities, list):
            entities = []
        # Normalise entity entries
        clean_entities = []
        for ent in entities:
            if isinstance(ent, dict) and 'text' in ent and 'type' in ent:
                clean_entities.append({
                    'text': str(ent['text']),
                    'type': str(ent['type']),
                    'confidence': float(ent.get('confidence', 1.0)),
                })
        result.append({'url': url, 'entities': clean_entities})

    return result
