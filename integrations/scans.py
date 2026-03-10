"""
Scan views for WordPress lead generation scanner.
Handles scan creation, status retrieval, and report generation.
"""
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

import requests as http_requests
from bs4 import BeautifulSoup
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

CRAWLER_UA = "Siloq-Scanner/1.0"
HOMEPAGE_TIMEOUT = 10
PAGE_TIMEOUT = 8
MAX_PAGES = 20
MAX_LINK_PAGES = 10

SCHEMA_KEY_TYPES = {
    "LocalBusiness", "Organization", "Service", "FAQPage",
    "BreadcrumbList", "WebPage", "Product",
}


# ---------------------------------------------------------------------------
# Crawler helpers
# ---------------------------------------------------------------------------

def _fetch(url, timeout=PAGE_TIMEOUT):
    """Fetch a URL and return (response, error_string|None)."""
    try:
        resp = http_requests.get(
            url, timeout=timeout,
            headers={"User-Agent": CRAWLER_UA},
            allow_redirects=True,
        )
        if resp.status_code >= 400:
            return None, f"HTTP {resp.status_code}"
        return resp, None
    except http_requests.RequestException as exc:
        return None, str(exc)


def _find_sitemap_urls(base_url):
    """Try /sitemap.xml, /sitemap_index.xml, then robots.txt Sitemap: directive."""
    urls = []
    for path in ("/sitemap.xml", "/sitemap_index.xml"):
        resp, err = _fetch(urljoin(base_url, path), timeout=PAGE_TIMEOUT)
        if resp is not None:
            urls = _parse_sitemap_xml(resp.text, base_url)
            if urls:
                return urls

    # Check robots.txt for Sitemap: directives
    resp, err = _fetch(urljoin(base_url, "/robots.txt"), timeout=PAGE_TIMEOUT)
    if resp is not None:
        for line in resp.text.splitlines():
            if line.strip().lower().startswith("sitemap:"):
                sitemap_url = line.split(":", 1)[1].strip()
                sm_resp, _ = _fetch(sitemap_url, timeout=PAGE_TIMEOUT)
                if sm_resp is not None:
                    urls = _parse_sitemap_xml(sm_resp.text, base_url)
                    if urls:
                        return urls
    return urls


def _parse_sitemap_xml(xml_text, base_url):
    """Extract page URLs from sitemap XML. Skip images, PDFs, query-string URLs."""
    urls = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return urls

    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    # Handle sitemap index → grab first child sitemap
    sitemap_tags = root.findall(".//sm:sitemap/sm:loc", ns)
    if sitemap_tags:
        for tag in sitemap_tags[:3]:
            resp, _ = _fetch(tag.text.strip(), timeout=PAGE_TIMEOUT)
            if resp is not None:
                urls.extend(_parse_sitemap_xml(resp.text, base_url))
                if len(urls) >= MAX_PAGES:
                    break
        return urls[:MAX_PAGES]

    for loc in root.findall(".//sm:loc", ns):
        u = loc.text.strip() if loc.text else ""
        if not u:
            continue
        parsed = urlparse(u)
        ext = parsed.path.rsplit(".", 1)[-1].lower() if "." in parsed.path else ""
        if ext in ("jpg", "jpeg", "png", "gif", "svg", "webp", "pdf"):
            continue
        if parsed.query:
            continue
        urls.append(u)
        if len(urls) >= MAX_PAGES:
            break
    return urls[:MAX_PAGES]


def _extract_internal_links(html, base_url):
    """Extract unique internal links from HTML."""
    soup = BeautifulSoup(html, "lxml")
    base_domain = urlparse(base_url).netloc
    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        full = urljoin(base_url, href)
        parsed = urlparse(full)
        if parsed.netloc != base_domain:
            continue
        if parsed.query:
            continue
        ext = parsed.path.rsplit(".", 1)[-1].lower() if "." in parsed.path else ""
        if ext in ("jpg", "jpeg", "png", "gif", "svg", "webp", "pdf"):
            continue
        clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        links.add(clean)
        if len(links) >= MAX_LINK_PAGES:
            break
    return list(links)[:MAX_LINK_PAGES]


def _crawl_pages(page_urls):
    """Crawl a list of URLs. Return list of dicts with url, html, error."""
    pages = []
    for url in page_urls[:MAX_PAGES]:
        resp, err = _fetch(url, timeout=PAGE_TIMEOUT)
        if resp is not None:
            pages.append({"url": url, "html": resp.text, "error": None})
        else:
            logger.debug("Skipping %s: %s", url, err)
    return pages


# ---------------------------------------------------------------------------
# Page-level extraction
# ---------------------------------------------------------------------------

def _extract_page_data(html, url):
    """Extract meta title, H1s, H2s, H3s, and JSON-LD schema from HTML."""
    soup = BeautifulSoup(html, "lxml")
    data = {"url": url, "meta_title": None, "h1s": [], "h2s": [], "h3s": [], "schema_types": set()}

    # Meta title
    title_tag = soup.find("title")
    if title_tag and title_tag.string:
        data["meta_title"] = title_tag.string.strip()

    # H tags
    for tag_name, key in [("h1", "h1s"), ("h2", "h2s"), ("h3", "h3s")]:
        for tag in soup.find_all(tag_name):
            text = tag.get_text(strip=True)
            if text:
                data[key].append(text)

    # JSON-LD schema
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            ld = json.loads(script.string)
            _collect_types(ld, data["schema_types"])
        except (json.JSONDecodeError, TypeError):
            pass

    return data


def _collect_types(obj, types_set):
    """Recursively collect @type values from JSON-LD."""
    if isinstance(obj, dict):
        if "@type" in obj:
            t = obj["@type"]
            if isinstance(t, list):
                types_set.update(t)
            else:
                types_set.add(t)
        if "@graph" in obj and isinstance(obj["@graph"], list):
            for item in obj["@graph"]:
                _collect_types(item, types_set)
    elif isinstance(obj, list):
        for item in obj:
            _collect_types(item, types_set)


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

AI_CRAWLERS = ["GPTBot", "ClaudeBot", "PerplexityBot", "anthropic-ai", "Google-Extended"]
QUESTION_PREFIXES = re.compile(r'^(What|How|Why|When|Is|Can|Does|Are)\b', re.IGNORECASE)


def _word_set(text):
    if not text:
        return set()
    return set(re.findall(r'\w+', text.lower()))


def _word_overlap(a, b):
    sa, sb = _word_set(a), _word_set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / max(len(sa), len(sb))


def _slug_keywords(url):
    """Extract meaningful keywords from a URL slug."""
    path = urlparse(url).path.strip("/")
    if not path:
        return set()
    # Split on / and - to get individual words, drop very short tokens
    tokens = re.findall(r'[a-z]{3,}', path.lower())
    return set(tokens)


def _fetch_robots_txt(base_url):
    """Fetch and return robots.txt content, or None."""
    resp, _ = _fetch(urljoin(base_url, "/robots.txt"), timeout=PAGE_TIMEOUT)
    return resp.text if resp else None


def _check_ai_crawlers_blocked(robots_text):
    """Return list of AI crawlers blocked in robots.txt."""
    if not robots_text:
        return []
    blocked = []
    current_agents = set()
    for line in robots_text.splitlines():
        line = line.strip()
        if line.lower().startswith("user-agent:"):
            agent = line.split(":", 1)[1].strip()
            current_agents = {agent}
        elif line.lower().startswith("disallow:") and line.split(":", 1)[1].strip():
            for crawler in AI_CRAWLERS:
                if crawler in current_agents:
                    blocked.append(crawler)
            current_agents = set()
    return list(set(blocked))


def _check_noindex(html):
    """Check if page has a robots noindex meta tag."""
    soup = BeautifulSoup(html, "lxml")
    meta = soup.find("meta", attrs={"name": re.compile(r'^robots$', re.I)})
    if meta and meta.get("content") and "noindex" in meta["content"].lower():
        return True
    return False


def _appears_local(pages_data):
    """Heuristic: does the site appear to be a local business?"""
    homepage = pages_data[0] if pages_data else None
    if not homepage:
        return False
    # Has LocalBusiness schema
    if "LocalBusiness" in homepage.get("schema_types", set()):
        return True
    # City/state pattern in titles
    state_abbrs = r'\b[A-Z]{2}\b'
    for p in pages_data:
        t = p.get("meta_title") or ""
        if re.search(state_abbrs, t) and re.search(r'\b[A-Z][a-z]+\b', t):
            return True
    return False


# ---------------------------------------------------------------------------
# Scoring dimensions (5 pillars, weighted)
# ---------------------------------------------------------------------------

def _score_cannibalization(pages_data):
    """Pillar 1: Keyword Cannibalization (30 pts)."""
    score = 30
    issues = []
    auto_fixable = []
    requires_content = []

    titles = [(p["url"], p["meta_title"] or (p["h1s"][0] if p["h1s"] else "")) for p in pages_data]

    # High overlap (>80%) — title/H1 keyword clash
    high_overlap_penalty = 0
    seen_pairs = set()
    for i, (url_a, title_a) in enumerate(titles):
        if not title_a:
            continue
        for j, (url_b, title_b) in enumerate(titles):
            if j <= i or not title_b:
                continue
            pair_key = tuple(sorted([url_a, url_b]))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            overlap = _word_overlap(title_a, title_b)
            path_a = urlparse(url_a).path.rstrip("/") or "/"
            path_b = urlparse(url_b).path.rstrip("/") or "/"

            if overlap > 0.8:
                pct = int(overlap * 100)
                issues.append(f"Pages '{path_a}' and '{path_b}' have {pct}% title overlap")
                high_overlap_penalty += 8
                requires_content.append(f"Keyword cannibalization between '{path_a}' and '{path_b}'")
            elif overlap > 0.7:
                pct = int(overlap * 100)
                issues.append(f"Pages '{path_a}' and '{path_b}' have {pct}% title overlap (near-duplicate)")
                score -= 4  # near-duplicate penalty, capped below
                requires_content.append(f"Rewrite to differentiate '{path_a}' and '{path_b}'")

    score -= min(24, high_overlap_penalty)

    # URL slug overlap: same service keyword in 3+ slugs
    slug_word_counts = {}
    for url_a, _ in titles:
        for kw in _slug_keywords(url_a):
            slug_word_counts.setdefault(kw, []).append(url_a)
    for kw, urls in slug_word_counts.items():
        if len(urls) >= 3:
            issues.append(f"Keyword '{kw}' appears in {len(urls)} URL slugs")
            score -= 6
            requires_content.append(f"Consolidate pages with overlapping slug keyword '{kw}'")
            break  # one slug-overlap penalty max

    # Cap near-duplicate penalty at -12 (already handled by min on high overlap)
    score = max(0, score)
    return {"score": score, "max": 30, "issues": issues,
            "auto_fixable": auto_fixable, "requires_content": requires_content}


def _score_ai_visibility(pages_data, base_url, robots_text, has_llms_txt):
    """Pillar 2: AI Visibility (25 pts)."""
    score = 25
    issues = []
    auto_fixable = []
    requires_content = []

    # Homepage missing LocalBusiness/Organization schema
    homepage_types = pages_data[0]["schema_types"] if pages_data else set()
    if not (homepage_types & {"LocalBusiness", "Organization"}):
        score -= 10
        issues.append("Homepage missing LocalBusiness or Organization schema")
        auto_fixable.append("Add LocalBusiness schema to homepage")

    # Inner pages missing schema (sample up to 5)
    inner = pages_data[1:6]
    if inner:
        missing_schema = sum(1 for p in inner if not p["schema_types"])
        if missing_schema > len(inner) / 2:
            score -= 6
            issues.append(f"{missing_schema} of {len(inner)} sampled inner pages have no schema")
            auto_fixable.append("Add schema markup to inner pages")

    # robots.txt AI crawler blocks
    blocked = _check_ai_crawlers_blocked(robots_text)
    if blocked:
        penalty = min(6, len(blocked) * 3)
        score -= penalty
        for crawler in blocked:
            issues.append(f"{crawler} blocked in robots.txt \u2014 may limit AI Overview visibility")

    # llms.txt check
    if not has_llms_txt:
        score -= 5
        issues.append("No llms.txt \u2014 AI assistants cannot learn your authority structure")
        auto_fixable.append("Generate llms.txt authority file")

    # FAQ schema on question-format H2s
    pages_with_question_h2s = 0
    pages_missing_faq_schema = 0
    for p in pages_data:
        question_h2s = [h for h in p["h2s"] if QUESTION_PREFIXES.match(h)]
        if question_h2s:
            pages_with_question_h2s += 1
            if "FAQPage" not in p["schema_types"]:
                pages_missing_faq_schema += 1
    if pages_with_question_h2s > 0 and pages_missing_faq_schema > 0:
        score -= 4
        issues.append(f"{pages_missing_faq_schema} page(s) have question-format H2s but no FAQ schema")
        requires_content.append("Add FAQ schema to pages with question-format headings")

    score = max(0, score)
    return {"score": score, "max": 25, "issues": issues,
            "auto_fixable": auto_fixable, "requires_content": requires_content}


def _score_meta_titles(pages_data):
    """Pillar 3: Meta Title Health (20 pts)."""
    score = 20
    issues = []
    auto_fixable = []
    requires_content = []

    homepage = pages_data[0] if pages_data else None
    inner = pages_data[1:]

    # Homepage missing title
    if homepage and not homepage["meta_title"]:
        score -= 8
        issues.append("Homepage missing meta title")
        requires_content.append("Missing meta title on homepage (page may need content)")

    # Inner pages missing titles
    inner_missing = sum(1 for p in inner if not p["meta_title"])
    if inner_missing:
        penalty = min(9, inner_missing * 3)
        score -= penalty
        issues.append(f"{inner_missing} inner page{'s' if inner_missing != 1 else ''} missing meta title")

    # Duplicate titles
    title_counts = {}
    for p in pages_data:
        t = p["meta_title"]
        if t:
            tl = t.lower()
            title_counts[tl] = title_counts.get(tl, 0) + 1
    has_duplicates = any(v > 1 for v in title_counts.values())
    if has_duplicates:
        score -= 6
        dup_count = sum(v - 1 for v in title_counts.values() if v > 1)
        issues.append(f"{dup_count} page{'s' if dup_count != 1 else ''} have duplicate titles")
        auto_fixable.append("Fix duplicate meta titles")

    # Title length >65 chars
    long_count = sum(1 for p in pages_data if p["meta_title"] and len(p["meta_title"]) > 65)
    if long_count:
        penalty = min(6, long_count * 3)
        score -= penalty
        issues.append(f"{long_count} page{'s' if long_count != 1 else ''} with title > 65 chars")
        auto_fixable.append("Trim over-length meta titles")

    # Title length <20 chars
    short_count = sum(1 for p in pages_data if p["meta_title"] and len(p["meta_title"]) < 20)
    if short_count:
        penalty = min(6, short_count * 3)
        score -= penalty
        issues.append(f"{short_count} page{'s' if short_count != 1 else ''} with title < 20 chars")
        auto_fixable.append("Expand short meta titles")

    # Local keyword missing from homepage title (only if site appears local)
    if homepage and homepage["meta_title"] and _appears_local(pages_data):
        # Check if title contains any city/state-like tokens (rough heuristic)
        title_words = _word_set(homepage["meta_title"])
        # Look for location tokens across all titles
        location_tokens = set()
        for p in pages_data:
            t = p.get("meta_title") or ""
            # Find capitalized words that look like city names
            for match in re.findall(r'\b([A-Z][a-z]{2,})\b', t):
                location_tokens.add(match.lower())
        # If we found location tokens elsewhere but not in homepage title
        homepage_words = _word_set(homepage["meta_title"])
        if location_tokens and not (homepage_words & location_tokens):
            score -= 5
            issues.append("Homepage meta title missing location keyword")
            auto_fixable.append("Add location keyword to homepage title")

    score = max(0, score)
    return {"score": score, "max": 20, "issues": issues,
            "auto_fixable": auto_fixable, "requires_content": requires_content}


def _score_content_structure(pages_data, homepage_html):
    """Pillar 4: Content Structure (15 pts)."""
    score = 15
    issues = []
    auto_fixable = []
    requires_content = []

    homepage = pages_data[0] if pages_data else None

    if homepage:
        # Multiple H1 tags on homepage
        if len(homepage["h1s"]) > 1:
            score -= 6
            issues.append(f"Homepage has {len(homepage['h1s'])} H1 tags")
            auto_fixable.append("Fix multiple H1 tags")

        # H1 missing on homepage
        if not homepage["h1s"]:
            score -= 8
            issues.append("Homepage missing H1 tag")
            auto_fixable.append("Add H1 tag to homepage")

        # H1/title mismatch
        if homepage["h1s"] and homepage["meta_title"]:
            overlap = _word_overlap(homepage["h1s"][0], homepage["meta_title"])
            if overlap < 0.25:
                score -= 5
                issues.append("H1 and meta title are misaligned on homepage")
                auto_fixable.append("Align H1 with target keyword")

        # Internal links check
        if homepage_html:
            soup = BeautifulSoup(homepage_html, "lxml")
            base_domain = urlparse(pages_data[0]["url"]).netloc
            internal_links = 0
            for a in soup.find_all("a", href=True):
                href = a["href"]
                full = urljoin(pages_data[0]["url"], href)
                if urlparse(full).netloc == base_domain:
                    internal_links += 1
                    if internal_links >= 3:
                        break
            if internal_links < 3:
                score -= 4
                issues.append(f"Homepage has only {internal_links} internal link{'s' if internal_links != 1 else ''}")

    score = max(0, score)
    return {"score": score, "max": 15, "issues": issues,
            "auto_fixable": auto_fixable, "requires_content": requires_content}


def _score_technical(base_url, homepage_resp, homepage_load_time):
    """Pillar 5: Technical Foundation (10 pts)."""
    score = 10
    issues = []
    auto_fixable = []
    requires_content = []

    # SSL check
    if not base_url.startswith("https"):
        score -= 6
        issues.append("Site does not use HTTPS")
    elif homepage_resp is not None:
        # Check if redirected to http
        final_url = homepage_resp.url if hasattr(homepage_resp, 'url') else ""
        if final_url.startswith("http://"):
            score -= 6
            issues.append("Site redirects HTTPS to HTTP")

    # Response time
    if homepage_load_time is not None and homepage_load_time > 4.0:
        score -= 4
        issues.append(f"Page load time: {homepage_load_time:.1f} seconds (above 4s threshold)")

    # Noindex check
    if homepage_resp is not None and _check_noindex(homepage_resp.text):
        score -= 10
        issues.append("Homepage has robots meta noindex tag — Critical")

    score = max(0, score)
    return {"score": score, "max": 10, "issues": issues,
            "auto_fixable": auto_fixable, "requires_content": requires_content}


# ---------------------------------------------------------------------------
# Main scan orchestrator
# ---------------------------------------------------------------------------

def _empty_dimension(max_pts):
    return {"score": 0, "max": max_pts, "issues": [], "auto_fixable": [], "requires_content": []}


def _grade(total):
    if total >= 80:
        return "Healthy"
    elif total >= 60:
        return "Needs Attention"
    return "Critical Issues Found"


def _build_error_result(err_msg, url=""):
    dims = {
        "cannibalization": _empty_dimension(30),
        "ai_visibility": _empty_dimension(25),
        "meta_titles": _empty_dimension(20),
        "content_structure": _empty_dimension(15),
        "technical": _empty_dimension(10),
    }
    return {
        "total_score": 0,
        "grade": "Critical Issues Found",
        "pages_crawled": 0,
        "benchmark": "Sites with strong SEO governance average 82/100. You scored 0.",
        "dimensions": dims,
        "auto_fixable_count": 0,
        "requires_content_count": 0,
        "top_issues": [err_msg],
        "cta": "Siloq can automatically fix 0 of your 1 issues. Start your free trial.",
        "error": err_msg,
    }


def _run_scan(url):
    """Crawl and score a URL. Returns (score, pages_crawled, results_dict, elapsed)."""
    start = time.time()

    # Normalize base URL
    if not url.startswith("http"):
        url = "https://" + url
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    # 1. Fetch homepage (measure load time)
    t0 = time.time()
    homepage_resp, err = _fetch(base_url + "/", timeout=HOMEPAGE_TIMEOUT)
    homepage_load_time = round(time.time() - t0, 2)

    if homepage_resp is None:
        elapsed = round(time.time() - start, 1)
        return 0, 0, _build_error_result(f"Could not fetch {url}: {err}"), elapsed

    # 2. Fetch robots.txt and llms.txt in parallel-ish
    robots_text = _fetch_robots_txt(base_url)

    llms_resp, _ = _fetch(urljoin(base_url, "/llms.txt"), timeout=PAGE_TIMEOUT)
    has_llms_txt = llms_resp is not None

    # 3. Discover pages via sitemap or link extraction
    page_urls = _find_sitemap_urls(base_url)
    limited = False
    if not page_urls:
        page_urls = _extract_internal_links(homepage_resp.text, base_url)
        if not page_urls:
            limited = True

    # Ensure homepage is in the list and is first
    homepage_url = base_url + "/"
    page_urls = [u for u in page_urls if u.rstrip("/") != base_url.rstrip("/")]
    page_urls.insert(0, homepage_url)
    page_urls = page_urls[:MAX_PAGES]

    # 4. Crawl pages (homepage already fetched)
    pages = [{"url": homepage_url, "html": homepage_resp.text, "error": None}]
    remaining = [u for u in page_urls[1:]]
    pages.extend(_crawl_pages(remaining))

    # 5. Extract data from each page
    pages_data = [_extract_page_data(p["html"], p["url"]) for p in pages]

    # 6. Score all 5 pillars
    cann = _score_cannibalization(pages_data)
    ai_vis = _score_ai_visibility(pages_data, base_url, robots_text, has_llms_txt)
    meta = _score_meta_titles(pages_data)
    structure = _score_content_structure(pages_data, homepage_resp.text)
    tech = _score_technical(base_url, homepage_resp, homepage_load_time)

    total_score = cann["score"] + ai_vis["score"] + meta["score"] + structure["score"] + tech["score"]

    # Aggregate auto_fixable and requires_content counts
    all_dims = [cann, ai_vis, meta, structure, tech]
    auto_fixable_count = sum(len(d["auto_fixable"]) for d in all_dims)
    requires_content_count = sum(len(d["requires_content"]) for d in all_dims)
    total_issues = auto_fixable_count + requires_content_count

    # Top issues: collect from pillars with worst scores first
    dim_entries = [
        ("cannibalization", cann),
        ("ai_visibility", ai_vis),
        ("meta_titles", meta),
        ("content_structure", structure),
        ("technical", tech),
    ]
    all_issues = []
    for _, dim in sorted(dim_entries, key=lambda x: x[1]["score"]):
        all_issues.extend(dim["issues"])
    top_issues = all_issues[:5]

    results = {
        "total_score": total_score,
        "grade": _grade(total_score),
        "pages_crawled": len(pages),
        "benchmark": f"Sites with strong SEO governance average 82/100. You scored {total_score}.",
        "dimensions": {
            "cannibalization": cann,
            "ai_visibility": ai_vis,
            "meta_titles": meta,
            "content_structure": structure,
            "technical": tech,
        },
        "auto_fixable_count": auto_fixable_count,
        "requires_content_count": requires_content_count,
        "top_issues": top_issues,
        "cta": f"Siloq can automatically fix {auto_fixable_count} of your {total_issues} issues. Start your free trial.",
    }

    if limited:
        results["note"] = "Limited scan: only homepage analyzed"

    elapsed = round(time.time() - start, 1)
    return total_score, len(pages), results, elapsed


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

    try:
        total_score, pages_crawled, results, elapsed = _run_scan(scan.url)
        scan.status = 'completed'
        scan.score = total_score
        scan.pages_analyzed = pages_crawled
        scan.scan_duration_seconds = elapsed
        scan.completed_at = timezone.now()
        scan.results = results
    except Exception:
        logger.exception("Scan %s failed for %s", scan.id, scan.url)
        scan.status = 'completed'
        scan.score = 0
        scan.pages_analyzed = 0
        scan.scan_duration_seconds = 0
        scan.completed_at = timezone.now()
        scan.results = _build_error_result("Internal scan error")

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
            'issues_found': len(scan.results.get('dimensions', {}).get('cannibalization', {}).get('issues', [])),
            'recommendations': scan.results.get('top_issues', []),
        }
    }

    return Response(report)
