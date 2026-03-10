"""
Siloq GEO Scorer — v1.1
=======================
Deterministic, pure-Python GEO (Generative Engine Optimization) scoring.
No AI API calls. Auditable, fast, runs on-demand per page.

Score: 0–100 per page.

CONTENT TYPE MODES (set automatically from page_type / post_type):
  local_service  — full 5-signal scoring (default)
  product        — e-commerce product pages (skip answer_first + entity_definition)
  content        — blog/editorial pages (skip entity_definition)

API CONTRACT:
  Endpoint: POST /api/v1/sites/{site_id}/pages/{page_id}/geo-score/
  Body: {
    "html": "<full page HTML string>",
    "meta": {
      "title": str,
      "url": str,
      "word_count": int,
      "page_type": str,       # hub | spoke | orphan | homepage | product
      "post_type": str,       # post | page | product | ...
      "has_schema": bool,     # from Siloq's schema table
      "internal_link_count": int
    }
  }
  Response: GeoScoreResult as JSON (score, grade, breakdown, recommendations)

  Plugin behavior: fetches live page HTML when user clicks "Run GEO Audit".
  Do NOT store HTML at sync time — database size issue at scale (e.g. 745 products).

DROP-IN for Ahmad:
  from siloq_geo_scorer import GeoScorer, detect_content_type

  content_type = detect_content_type(meta)
  result = GeoScorer.score(html=page_html, meta=meta, content_type=content_type)
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# SIGNAL WEIGHTS BY CONTENT TYPE
# Each dict must sum to 100.
# ─────────────────────────────────────────────────────────────────────────────

SIGNAL_WEIGHTS = {
    "local_service": {
        "answer_first_format": 25,
        "faq_structure":       25,
        "entity_definition":   20,   # 15 base + 5 quantified bonus
        "schema_present":      20,
        "internal_link_equity": 10,
    },
    "product": {
        # answer_first and entity_definition don't apply to product pages
        # Redistribute their 45pts → FAQ 40, schema 40, internal_links 20
        "answer_first_format":  0,
        "faq_structure":       40,
        "entity_definition":    0,
        "schema_present":      40,
        "internal_link_equity": 20,
    },
    "content": {
        # Blog/editorial — entity_definition less relevant, answer-first matters more
        "answer_first_format": 30,
        "faq_structure":       35,
        "entity_definition":    0,
        "schema_present":      25,
        "internal_link_equity": 10,
    },
}

for mode, weights in SIGNAL_WEIGHTS.items():
    assert sum(weights.values()) == 100, f"Weights for '{mode}' must sum to 100"


# ─────────────────────────────────────────────────────────────────────────────
# RESULT TYPES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SignalResult:
    name: str
    score: int
    max_points: int
    passed: bool
    detail: str
    recommendation: Optional[str] = None


@dataclass
class GeoScoreResult:
    score: int
    grade: str
    content_type: str
    signals: List[SignalResult] = field(default_factory=list)
    breakdown: Dict[str, int] = field(default_factory=dict)
    recommendations: List[str] = field(default_factory=list)
    page_url: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# DETECTION PATTERNS
# ─────────────────────────────────────────────────────────────────────────────

FAQ_QUESTION_PATTERNS = [
    r'\?$',
    r'^(?:what|how|why|when|where|who|can|does|do|is|are|will|should)\b',
    r'^(?:frequently asked|faq|common questions)',
]

DECLARATIVE_PATTERNS = [
    r'\b(?:is|are|provides?|offers?|serves?|specializes?|has been)\b',
]

# Entity base signals — business type / ownership
ENTITY_BASE_PATTERNS = [
    r'\b(?:LLC|Inc\.|Corp\.|Co\.|Company|Services|Solutions|Group)\b',
    r'\blicensed\b',
    r'\bcertified\b',
    r'\b(?:locally owned|family owned|locally-owned|owner-operated)\b',
    r'\binsured\b',
    r'\bbonded\b',
]

# Quantified claim patterns — "since 1998", "2,400+ jobs", "4.9 stars", etc.
QUANTIFIED_CLAIM_PATTERNS = [
    r'\bsince\s+(?:19|20)\d{2}\b',                                         # since 1998
    r'\bfounded\s+in\s+(?:19|20)\d{2}\b',                                  # founded in 2005
    r'\bfor\s+\d+\s+years?\b',                                              # for 20 years
    r'\b\d[\d,]*\+?\s*(?:jobs|projects|customers|installs|homes|reviews)\b', # 2,400+ jobs
    r'\b\d\.\d\s*(?:stars?|out of 5|\/5)\b',                               # 4.9 stars
    r'\b\d[\d,]*\+?\s*(?:Google reviews?|verified reviews?)\b',             # 500+ Google reviews
    r'\b\d+\s*(?:years? in business|years? of experience|years? serving)\b', # 18 years in business
]

SCHEMA_PATTERNS = [
    r'application/ld\+json',
    r'"@type"\s*:\s*"(?:LocalBusiness|Service|FAQPage|BreadcrumbList|Organization|Product|ItemList)',
    r'itemtype="https?://schema\.org/',
]


# ─────────────────────────────────────────────────────────────────────────────
# CONTENT TYPE DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def detect_content_type(meta: dict) -> str:
    """
    Automatically determine scoring mode from page/post type.
    Plugin should pass post_type from WP (post, page, product, etc.)
    and page_type from Siloq's classification (hub, spoke, orphan, product, homepage).
    """
    post_type = (meta.get("post_type") or "").lower()
    page_type = (meta.get("page_type") or "").lower()

    if post_type == "product" or page_type == "product":
        return "product"
    if post_type == "post" or page_type in ("blog", "article", "content"):
        return "content"
    return "local_service"


# ─────────────────────────────────────────────────────────────────────────────
# SCORER
# ─────────────────────────────────────────────────────────────────────────────

class GeoScorer:

    @classmethod
    def score(cls, html: str, meta: dict, content_type: str = None) -> GeoScoreResult:
        """
        Score a single page for GEO readiness.

        Args:
            html:         Full page HTML string (live-fetched by plugin on demand)
            meta:         Dict — title, url, word_count, page_type, post_type,
                          has_schema (bool), internal_link_count (int)
            content_type: 'local_service' | 'product' | 'content'
                          If None, auto-detected from meta.
        """
        if content_type is None:
            content_type = detect_content_type(meta)

        weights = SIGNAL_WEIGHTS[content_type]
        text_content = cls._extract_text(html)
        first_100_words = cls._first_n_words(text_content, 100)
        headings = cls._extract_headings(html)

        signals = [
            cls._check_answer_first(first_100_words, meta, weights["answer_first_format"]),
            cls._check_faq_structure(headings, text_content, meta, weights["faq_structure"]),
            cls._check_entity_definition(first_100_words, meta, weights["entity_definition"]),
            cls._check_schema(html, meta, weights["schema_present"]),
            cls._check_internal_links(meta, weights["internal_link_equity"]),
        ]

        total = max(0, min(100, sum(s.score for s in signals)))

        return GeoScoreResult(
            score=total,
            grade=cls._grade(total),
            content_type=content_type,
            signals=signals,
            breakdown={s.name: s.score for s in signals},
            recommendations=[s.recommendation for s in signals if s.recommendation],
            page_url=meta.get("url", ""),
        )

    # ── Signal 1: Answer-First Format ─────────────────────────────────────────
    @classmethod
    def _check_answer_first(cls, first_100: str, meta: dict, max_pts: int) -> SignalResult:
        if max_pts == 0:
            return SignalResult("answer_first_format", 0, 0, True, "Not scored for this content type.")

        first_lower = first_100.lower()
        has_declarative = any(re.search(p, first_lower) for p in DECLARATIVE_PATTERNS)
        # Location check on original case (needs capital letters for state abbreviations)
        has_location = bool(re.search(r'\bin\s+[A-Z][a-z]+|,\s*[A-Z]{2}\b', first_100))

        if has_declarative and has_location:
            return SignalResult("answer_first_format", max_pts, max_pts, True,
                "States main claim with location in first 100 words.")
        elif has_declarative or has_location:
            return SignalResult("answer_first_format", max_pts // 2, max_pts, False,
                "Declarative statement found but missing a clear location signal in opening.",
                "Add your city/state to the first sentence. Example: 'Able Electric provides licensed electrical services in Kansas City, MO.'")
        return SignalResult("answer_first_format", 0, max_pts, False,
            "First 100 words don't establish what the business does or where.",
            "Start the page with: '[Business name] is a [service type] in [city, state].'")

    # ── Signal 2: FAQ Structure ───────────────────────────────────────────────
    @classmethod
    def _check_faq_structure(cls, headings: List[dict], text: str, meta: dict, max_pts: int) -> SignalResult:
        if max_pts == 0:
            return SignalResult("faq_structure", 0, 0, True, "Not scored for this content type.")

        question_headings = []
        has_faq_section = False
        for h in headings:
            h_text = h.get("text", "").strip().lower()
            if any(re.search(p, h_text, re.I) for p in FAQ_QUESTION_PATTERNS):
                if "frequently asked" in h_text or h_text.startswith("faq"):
                    has_faq_section = True
                else:
                    question_headings.append(h_text)

        has_faq_schema = "faqpage" in text.lower()
        q_count = len(question_headings)

        if q_count >= 3 or has_faq_schema:
            return SignalResult("faq_structure", max_pts, max_pts, True,
                f"{q_count} question-format headings. Strong FAQ structure for AI citation.")
        elif q_count in (1, 2):
            return SignalResult("faq_structure", max_pts // 2, max_pts, False,
                f"{q_count} question-format heading(s) found.",
                f"Add {3 - q_count} more FAQ questions as H2/H3 headings. Example: 'How much does [service] cost in [city]?'")
        elif has_faq_section:
            return SignalResult("faq_structure", max_pts // 4, max_pts, False,
                "FAQ section heading found but no question-format headings inside.",
                "Rewrite FAQ answer headings as actual questions: 'What does an electrician charge per hour?'")
        return SignalResult("faq_structure", 0, max_pts, False,
            "No FAQ structure detected.",
            "Add a FAQ section with 3–5 questions as H2 headings. This is one of the strongest signals for AI citations.")

    # ── Signal 3: Entity Definition (15 base + 5 quantified bonus) ───────────
    @classmethod
    def _check_entity_definition(cls, first_100: str, meta: dict, max_pts: int) -> SignalResult:
        if max_pts == 0:
            return SignalResult("entity_definition", 0, 0, True, "Not scored for this content type.")

        base_max = max_pts - 5   # e.g. 15 for local_service
        bonus_max = 5

        # Base: entity type / ownership markers in first 100 words or title
        base_matches = [p for p in ENTITY_BASE_PATTERNS if re.search(p, first_100, re.I)]
        if re.search(r'\b(?:LLC|Inc\.|licensed|certified|insured)\b', meta.get("title", ""), re.I):
            base_matches.append("title_entity")

        if len(base_matches) >= 2:
            base_score = base_max
            base_detail = "Entity clearly identified with credentials in opening content."
            base_rec = None
        elif len(base_matches) == 1:
            base_score = base_max // 2
            base_detail = "One entity credential signal found."
            base_rec = "Add licensing, ownership type ('locally owned'), or insurance mention to your first paragraph."
        else:
            base_score = 0
            base_detail = "No entity credential signals in opening content."
            base_rec = "Add to your opening paragraph: '[Business] is a licensed, locally owned [service type] serving [city] since [year].'"

        # Bonus: quantified claims anywhere in first 200 words of page
        first_200 = " ".join(first_100.split())  # already first 100; check full text next
        quantified_matches = [p for p in QUANTIFIED_CLAIM_PATTERNS if re.search(p, first_100, re.I)]
        bonus_score = bonus_max if quantified_matches else 0

        total = base_score + bonus_score
        detail = base_detail
        if bonus_score:
            detail += f" Quantified credibility marker found ({len(quantified_matches)} pattern(s))."
        else:
            detail += " No quantified claims (years, job counts, ratings) found."

        rec = None
        if base_rec:
            rec = base_rec
        elif not bonus_score:
            rec = "Add a specific number to build credibility: years in business, jobs completed, or Google review count. Example: 'Serving Kansas City since 1998 with 2,400+ completed jobs.'"

        return SignalResult("entity_definition", total, max_pts, total == max_pts, detail, rec)

    # ── Signal 4: Schema Present ──────────────────────────────────────────────
    @classmethod
    def _check_schema(cls, html: str, meta: dict, max_pts: int) -> SignalResult:
        if max_pts == 0:
            return SignalResult("schema_present", 0, 0, True, "Not scored for this content type.")

        if meta.get("has_schema"):
            return SignalResult("schema_present", max_pts, max_pts, True,
                "Schema markup applied via Siloq.")

        html_lower = html.lower()
        has_ld_json = bool(re.search(r'application/ld\+json', html_lower))
        has_recognized = any(re.search(p, html, re.I) for p in SCHEMA_PATTERNS[1:])
        has_microdata = bool(re.search(r'itemtype="https?://schema\.org/', html))

        if has_recognized or has_microdata:
            return SignalResult("schema_present", max_pts, max_pts, True,
                "Recognized schema @type detected in page HTML.")
        elif has_ld_json:
            return SignalResult("schema_present", max_pts // 2, max_pts, False,
                "JSON-LD present but no recognized @type.",
                "Add @type: LocalBusiness (or Product for product pages) to your schema so AI systems can classify your business.")
        return SignalResult("schema_present", 0, max_pts, False,
            "No schema markup detected.",
            "Apply schema via Siloq's Schema tab. LocalBusiness + FAQPage schema significantly increases AI citation probability.")

    # ── Signal 5: Internal Link Equity ────────────────────────────────────────
    @classmethod
    def _check_internal_links(cls, meta: dict, max_pts: int) -> SignalResult:
        if max_pts == 0:
            return SignalResult("internal_link_equity", 0, 0, True, "Not scored for this content type.")

        count = meta.get("internal_link_count", 0)
        if count >= 3:
            return SignalResult("internal_link_equity", max_pts, max_pts, True,
                f"{count} inbound internal links. Well-connected in site architecture.")
        elif count in (1, 2):
            return SignalResult("internal_link_equity", max_pts // 2, max_pts, False,
                f"Only {count} inbound internal link(s).",
                "Add links to this page from your hub page and at least 2 related spoke pages.")
        return SignalResult("internal_link_equity", 0, max_pts, False,
            "No inbound internal links — this page is an orphan.",
            "Link to this page from your hub page and related content. Internal linking signals authority to AI crawlers.")

    # ─────────────────────────────────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_text(html: str) -> str:
        if not html:
            return ""
        if BS4_AVAILABLE:
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            return soup.get_text(separator=" ", strip=True)
        text = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.S | re.I)
        text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.S | re.I)
        text = re.sub(r'<[^>]+>', ' ', text)
        return re.sub(r'\s+', ' ', text).strip()

    @staticmethod
    def _first_n_words(text: str, n: int) -> str:
        return " ".join(text.split()[:n])

    @staticmethod
    def _extract_headings(html: str) -> List[dict]:
        if not html:
            return []
        results = []
        for m in re.finditer(r'<(h[1-6])[^>]*>(.*?)</\1>', html, re.I | re.S):
            text = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            if text:
                results.append({"level": m.group(1).lower(), "text": text})
        return results

    @staticmethod
    def _grade(score: int) -> str:
        if score >= 90: return "A"
        if score >= 75: return "B"
        if score >= 60: return "C"
        if score >= 45: return "D"
        return "F"


# ─────────────────────────────────────────────────────────────────────────────
# BATCH SCORER
# ─────────────────────────────────────────────────────────────────────────────

class GeoScorerBatch:

    @classmethod
    def score_site(cls, pages: List[dict]) -> dict:
        """
        Score all pages and return site-level GEO summary.
        Each page dict: { "html": str, "meta": dict }
        """
        results = []
        for page in pages:
            meta = page.get("meta", {})
            content_type = detect_content_type(meta)
            result = GeoScorer.score(html=page.get("html", ""), meta=meta, content_type=content_type)
            results.append(result)

        if not results:
            return {"site_geo_score": 0, "pages": [], "top_opportunities": [],
                    "passing_pages": 0, "failing_pages": 0, "total_pages": 0}

        avg = round(sum(r.score for r in results) / len(results))
        passing = sum(1 for r in results if r.score >= 60)

        return {
            "site_geo_score": avg,
            "site_geo_grade": GeoScorer._grade(avg),
            "pages": results,
            "top_opportunities": sorted(results, key=lambda r: r.score)[:5],
            "passing_pages": passing,
            "failing_pages": len(results) - passing,
            "total_pages": len(results),
        }
