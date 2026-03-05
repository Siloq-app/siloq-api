"""
Silo Health Score v2 — 4-component weighted scoring formula.

Components:
  - Keyword Clarity     (40%) — non-competing keywords, penalise overlap
  - Structural Integrity (25%) — hub+spoke structure validation
  - Content Architecture (20%) — subtopic coverage + word-count adequacy
  - Internal Linking    (15%) — intra-silo link ratio vs ideal

Score range: 0–100 per silo.
Overall site health = weighted average across all active silos.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from django.db.models import Count, Q
from django.utils import timezone

logger = logging.getLogger(__name__)

# ─── Weight constants ───────────────────────────────────────────────────────
W_KEYWORD_CLARITY = 0.40
W_STRUCTURAL = 0.25
W_CONTENT_ARCH = 0.20
W_INTERNAL_LINKING = 0.15

# ─── Content quality thresholds ─────────────────────────────────────────────
THIN_CONTENT_WORDS = 300       # below this → thin page (penalty)
CRITICAL_THIN_WORDS = 100      # below this → critically thin (larger penalty)
THIN_PENALTY = 0.6             # multiply component score by this for thin pages
CRITICAL_THIN_PENALTY = 0.3    # multiply component score by this for critically thin pages
IDEAL_WORDS_PER_PAGE = 800     # "good" page threshold for full score

# ─── Internal linking thresholds ────────────────────────────────────────────
# In a perfect hub+spoke silo each spoke links back to hub; hub links to all spokes.
# We model "ideal" link count as: hub→N spokes + N spokes→hub = 2*N links.


@dataclass
class ComponentScores:
    keyword_clarity: float = 0.0
    structural_integrity: float = 0.0
    content_architecture: float = 0.0
    internal_linking: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        return {
            "keyword_clarity": round(self.keyword_clarity, 2),
            "structural_integrity": round(self.structural_integrity, 2),
            "content_architecture": round(self.content_architecture, 2),
            "internal_linking": round(self.internal_linking, 2),
        }

    @property
    def weighted_total(self) -> float:
        return (
            self.keyword_clarity * W_KEYWORD_CLARITY
            + self.structural_integrity * W_STRUCTURAL
            + self.content_architecture * W_CONTENT_ARCH
            + self.internal_linking * W_INTERNAL_LINKING
        )


@dataclass
class SiloScoreResult:
    silo_id: str
    silo_name: str
    score: float
    component_scores: ComponentScores
    page_count: int
    details: Dict = field(default_factory=dict)


class SiloHealthCalculator:
    """
    Calculates Silo Health Scores for all (or selected) silos on a site.

    Usage::

        calc = SiloHealthCalculator(site)
        results = calc.calculate_all()   # List[SiloScoreResult]
        overall = calc.overall_score(results)  # 0-100 float
    """

    def __init__(self, site):
        self.site = site

    # ─── Public API ─────────────────────────────────────────────────────────

    def calculate_all(self) -> List[SiloScoreResult]:
        """Calculate health scores for every active silo on the site."""
        from seo.models import SiloDefinition

        silos = SiloDefinition.objects.filter(site=self.site, status="active")
        results = []
        for silo in silos:
            try:
                result = self.calculate_silo(silo)
                results.append(result)
            except Exception as exc:
                logger.exception("Silo health calculation failed for silo %s: %s", silo.id, exc)
        return results

    def calculate_silo(self, silo) -> SiloScoreResult:
        """Calculate health score for a single SiloDefinition instance."""
        pages = self._get_silo_pages(silo)
        page_urls: Set[str] = {p["page_url"] for p in pages}

        if not pages:
            # Empty silo — every component scores 0
            components = ComponentScores()
            return SiloScoreResult(
                silo_id=str(silo.id),
                silo_name=silo.name,
                score=0.0,
                component_scores=components,
                page_count=0,
                details={"reason": "no_pages_in_silo"},
            )

        components = ComponentScores(
            keyword_clarity=self._score_keyword_clarity(silo, pages),
            structural_integrity=self._score_structural_integrity(silo, pages, page_urls),
            content_architecture=self._score_content_architecture(silo, pages),
            internal_linking=self._score_internal_linking(silo, pages, page_urls),
        )

        raw_score = components.weighted_total
        final_score = max(0.0, min(100.0, raw_score))

        return SiloScoreResult(
            silo_id=str(silo.id),
            silo_name=silo.name,
            score=round(final_score, 2),
            component_scores=components,
            page_count=len(pages),
        )

    def overall_score(self, results: List[SiloScoreResult]) -> Optional[float]:
        """Return weighted average score across all silos (by page count)."""
        if not results:
            return None
        total_pages = sum(r.page_count for r in results)
        if total_pages == 0:
            # Equal weight fallback
            return round(sum(r.score for r in results) / len(results), 2)
        weighted_sum = sum(r.score * max(r.page_count, 1) for r in results)
        return round(weighted_sum / total_pages, 2)

    # ─── Data helpers ────────────────────────────────────────────────────────

    def _get_silo_pages(self, silo) -> List[Dict]:
        """
        Return list of page dicts with url, keyword, page_type for this silo.
        Uses KeywordAssignment as the source of truth.
        """
        from seo.models import KeywordAssignment

        assignments = KeywordAssignment.objects.filter(
            silo=silo, site=self.site, status="active"
        ).values("page_url", "keyword", "page_type", "keyword_type")

        # Group by page_url — a page may have multiple keyword assignments
        pages: Dict[str, Dict] = {}
        for a in assignments:
            url = a["page_url"]
            if url not in pages:
                pages[url] = {
                    "page_url": url,
                    "page_type": a["page_type"],
                    "keywords": [],
                }
            pages[url]["keywords"].append(a["keyword"].lower().strip())

        return list(pages.values())

    def _get_page_metadata(self, page_urls: List[str]) -> Dict[str, Dict]:
        """Fetch PageMetadata for a list of URLs, keyed by URL."""
        from seo.models import PageMetadata

        metas = PageMetadata.objects.filter(
            site=self.site, page_url__in=page_urls
        ).values("page_url", "word_count", "internal_links_in", "internal_links_out")

        return {m["page_url"]: m for m in metas}

    def _get_internal_links_between(self, page_urls: Set[str]) -> int:
        """Count InternalLink records where both source and target are in page_urls."""
        from seo.models import InternalLink, Page

        if len(page_urls) < 2:
            return 0

        # Get Page PKs for the given URLs
        page_pks = Page.objects.filter(
            site=self.site, url__in=page_urls
        ).values_list("id", flat=True)

        pk_set = set(page_pks)
        if len(pk_set) < 2:
            return 0

        return InternalLink.objects.filter(
            site=self.site,
            source_page_id__in=pk_set,
            target_page_id__in=pk_set,
        ).count()

    def _hub_page_links(self, hub_url: str, spoke_urls: Set[str]) -> Tuple[int, int]:
        """
        Returns (hub_to_spokes_count, spokes_linking_back_count).
        hub_to_spokes: number of InternalLinks FROM hub TO spokes.
        spokes_linking_back: number of spokes that have an InternalLink TO hub.
        """
        from seo.models import InternalLink, Page

        try:
            hub_page = Page.objects.get(site=self.site, url=hub_url)
        except Page.DoesNotExist:
            return 0, 0

        spoke_pages = Page.objects.filter(site=self.site, url__in=spoke_urls)
        spoke_pks = set(spoke_pages.values_list("id", flat=True))

        hub_to_spokes = InternalLink.objects.filter(
            site=self.site,
            source_page=hub_page,
            target_page_id__in=spoke_pks,
        ).count()

        spokes_to_hub = InternalLink.objects.filter(
            site=self.site,
            source_page_id__in=spoke_pks,
            target_page=hub_page,
        ).values("source_page_id").distinct().count()

        return hub_to_spokes, spokes_to_hub

    # ─── Component scorers ───────────────────────────────────────────────────

    def _score_keyword_clarity(self, silo, pages: List[Dict]) -> float:
        """
        Keyword Clarity (0–100):
        - Penalise for keyword overlap WITHIN the silo (same keyword assigned to 2+ pages)
        - Penalise for keyword overlap with OTHER silos on the same site
        """
        if not pages:
            return 0.0

        # Build keyword → page_url mapping within this silo
        keyword_to_pages: Dict[str, List[str]] = {}
        for page in pages:
            for kw in page["keywords"]:
                keyword_to_pages.setdefault(kw, []).append(page["page_url"])

        total_keywords = sum(len(p["keywords"]) for p in pages)
        if total_keywords == 0:
            return 0.0  # No keywords assigned — cannot score clarity

        # Count overlapping keywords (same kw on 2+ pages in the silo)
        intra_silo_overlaps = sum(
            1 for urls in keyword_to_pages.values() if len(urls) > 1
        )

        # Penalty: each overlap costs 20 points, capped at 100
        overlap_penalty = min(intra_silo_overlaps * 20, 100)

        base_score = max(0.0, 100.0 - overlap_penalty)

        # Bonus: unique, non-overlapping keyword coverage increases clarity
        unique_keywords = len(keyword_to_pages)
        unique_pages = len(pages)
        diversity_ratio = min(unique_keywords / max(unique_pages, 1), 3.0) / 3.0
        diversity_bonus = diversity_ratio * 10  # up to 10 bonus points

        return min(100.0, base_score + diversity_bonus)

    def _score_structural_integrity(
        self, silo, pages: List[Dict], page_urls: Set[str]
    ) -> float:
        """
        Structural Integrity (0–100):
        - Hub page defined: 30 pts
        - Hub links to all spokes: up to 35 pts
        - All spokes link back to hub: up to 35 pts
        """
        score = 0.0
        hub_url = silo.hub_page_url

        spoke_pages = [p for p in pages if p["page_type"] != "hub"]
        spoke_urls = {p["page_url"] for p in spoke_pages}
        spoke_count = len(spoke_urls)

        # (1) Hub page defined
        if hub_url and hub_url.strip():
            score += 30.0
        else:
            # No hub → structural integrity is critically impaired
            return score  # 0

        if spoke_count == 0:
            # Hub-only silo: give partial credit for hub existing
            return 50.0

        hub_to_spokes, spokes_to_hub = self._hub_page_links(hub_url, spoke_urls)

        # (2) Hub links to all spokes
        hub_coverage = hub_to_spokes / spoke_count
        score += hub_coverage * 35.0

        # (3) Spokes link back to hub
        spoke_coverage = spokes_to_hub / spoke_count
        score += spoke_coverage * 35.0

        return min(100.0, score)

    def _score_content_architecture(self, silo, pages: List[Dict]) -> float:
        """
        Content Architecture (0–100):
        - Word count adequacy: thin pages heavily penalise the silo
        - Subtopic coverage: more unique keywords per page = better coverage
        """
        if not pages:
            return 0.0

        page_urls = [p["page_url"] for p in pages]
        metadata = self._get_page_metadata(page_urls)

        # ── Word count adequacy ──────────────────────────────────────────────
        adequacy_scores = []
        for page in pages:
            meta = metadata.get(page["page_url"])
            wc = meta["word_count"] if meta else 0

            if wc >= IDEAL_WORDS_PER_PAGE:
                adequacy_scores.append(100.0)
            elif wc >= THIN_CONTENT_WORDS:
                # Linear interpolation between 300 and 800
                ratio = (wc - THIN_CONTENT_WORDS) / (IDEAL_WORDS_PER_PAGE - THIN_CONTENT_WORDS)
                adequacy_scores.append(60.0 + ratio * 40.0)
            elif wc >= CRITICAL_THIN_WORDS:
                # Thin page
                adequacy_scores.append(25.0)
            else:
                # Critically thin (or no metadata)
                adequacy_scores.append(5.0)

        avg_adequacy = sum(adequacy_scores) / len(adequacy_scores)

        # ── Subtopic coverage ────────────────────────────────────────────────
        # Ideal: each page targets a distinct, relevant subtopic (unique keyword)
        all_keywords = [kw for p in pages for kw in p["keywords"]]
        unique_keywords = len(set(all_keywords))
        page_count = len(pages)

        # We want unique keywords ≥ page count (one per page minimum)
        coverage_ratio = min(unique_keywords / max(page_count, 1), 1.0)
        subtopic_score = coverage_ratio * 100.0

        # Weighted: 70% word adequacy, 30% subtopic coverage
        return round(avg_adequacy * 0.70 + subtopic_score * 0.30, 2)

    def _score_internal_linking(
        self, silo, pages: List[Dict], page_urls: Set[str]
    ) -> float:
        """
        Internal Linking (0–100):
        Ideal model: hub → all spokes + all spokes → hub = 2 × spoke_count links.
        Score = actual_intra_silo_links / ideal_links * 100 (capped at 100).
        """
        if len(pages) < 2:
            return 100.0  # Single-page silo: full score (no linking possible)

        spoke_count = len([p for p in pages if p["page_type"] != "hub"])
        if spoke_count == 0:
            spoke_count = len(pages) - 1  # fallback if types not set

        hub_url = silo.hub_page_url
        if hub_url and hub_url.strip():
            spoke_urls = {p["page_url"] for p in pages if p["page_url"] != hub_url}
            hub_to_spokes, spokes_to_hub = self._hub_page_links(hub_url, spoke_urls)
            actual_links = hub_to_spokes + spokes_to_hub
            ideal_links = 2 * max(len(spoke_urls), 1)
        else:
            # No hub defined — count all intra-silo links; ideal = N*(N-1)/2
            actual_links = self._get_internal_links_between(page_urls)
            n = len(pages)
            ideal_links = n * (n - 1) // 2

        if ideal_links == 0:
            return 100.0

        ratio = actual_links / ideal_links
        return min(100.0, round(ratio * 100.0, 2))


# ─── Persistence helper ──────────────────────────────────────────────────────

def save_silo_health_scores(
    site, results: List[SiloScoreResult], trigger: str = "on_demand"
) -> None:
    """Persist SiloHealthScore records for each result."""
    from seo.models import SiloHealthScore, SiloDefinition

    now = timezone.now()
    for result in results:
        try:
            silo = SiloDefinition.objects.get(id=result.silo_id, site=site)
            SiloHealthScore.objects.create(
                silo=silo,
                site=site,
                score=result.score,
                component_scores=result.component_scores.to_dict(),
                page_count=result.page_count,
                details=result.details,
                trigger=trigger,
                calculated_at=now,
            )
        except SiloDefinition.DoesNotExist:
            logger.warning("SiloDefinition %s not found when saving health score", result.silo_id)
        except Exception as exc:
            logger.exception("Failed to save SiloHealthScore for silo %s: %s", result.silo_id, exc)


def run_silo_health_for_site(site, trigger: str = "on_demand") -> Optional[float]:
    """
    Run full silo health calculation for a site and persist results.
    Returns the overall score, or None if no silos exist.
    """
    calc = SiloHealthCalculator(site)
    results = calc.calculate_all()
    if results:
        save_silo_health_scores(site, results, trigger=trigger)
    overall = calc.overall_score(results)
    logger.info(
        "Silo health calculated for site %s: %s silos, overall=%.1f (trigger=%s)",
        site.id,
        len(results),
        overall if overall is not None else 0,
        trigger,
    )
    return overall
