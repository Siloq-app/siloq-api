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
# Scoring dimensions
# ---------------------------------------------------------------------------

def _word_set(text):
    if not text:
        return set()
    return set(re.findall(r'\w+', text.lower()))


def _word_overlap(a, b):
    sa, sb = _word_set(a), _word_set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / max(len(sa), len(sb))


def _score_cannibalization(pages_data):
    """Dimension 1: Cannibalization Risk (25 pts)."""
    issues = []
    num_issues = 0
    titles = [(p["url"], p["meta_title"] or (p["h1s"][0] if p["h1s"] else "")) for p in pages_data]

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

            path_a = urlparse(url_a).path.rstrip("/") or "/"
            path_b = urlparse(url_b).path.rstrip("/") or "/"

            if title_a.lower() == title_b.lower():
                issues.append(f"Pages '{path_a}' and '{path_b}' have identical titles")
                num_issues += 1
            else:
                overlap = _word_overlap(title_a, title_b)
                if overlap > 0.7:
                    pct = int(overlap * 100)
                    issues.append(f"Pages '{path_a}' and '{path_b}' have {pct}% title overlap")
                    num_issues += 1

    score = max(0, 25 - 5 * num_issues)
    return score, issues


def _score_schema(pages_data):
    """Dimension 2: Schema Coverage (25 pts)."""
    issues = []
    score = 0

    pages_with_schema = sum(1 for p in pages_data if p["schema_types"])
    total = len(pages_data)

    # Homepage = first page
    homepage_types = pages_data[0]["schema_types"] if pages_data else set()
    has_lb_org = bool(homepage_types & {"LocalBusiness", "Organization"})

    if has_lb_org:
        score += 10
    else:
        issues.append("Homepage missing LocalBusiness/Organization schema")

    if total > 0 and pages_with_schema / total > 0.5:
        score += 10
    else:
        without = total - pages_with_schema
        issues.append(f"{without} of {total} pages have no structured data")

    all_types = set()
    for p in pages_data:
        all_types.update(p["schema_types"])

    if all_types & {"FAQPage", "Service"}:
        score += 5

    if total > 0 and pages_with_schema == total:
        score += 5

    score = min(25, max(0, score))
    return score, issues


def _score_meta_titles(pages_data):
    """Dimension 3: Meta Title Health (25 pts)."""
    issues = []
    missing = 0
    too_long = 0
    too_short = 0
    title_counts = {}

    for p in pages_data:
        t = p["meta_title"]
        if not t:
            missing += 1
            continue
        if len(t) > 65:
            too_long += 1
        if len(t) < 20:
            too_short += 1
        tl = t.lower()
        title_counts[tl] = title_counts.get(tl, 0) + 1

    duplicates = sum(v - 1 for v in title_counts.values() if v > 1)

    if missing:
        issues.append(f"{missing} page{'s' if missing != 1 else ''} missing meta title")
    if too_long:
        issues.append(f"{too_long} page{'s' if too_long != 1 else ''} with title > 65 chars")
    if too_short:
        issues.append(f"{too_short} page{'s' if too_short != 1 else ''} with title < 20 chars")
    if duplicates:
        issues.append(f"{duplicates} duplicate meta title{'s' if duplicates != 1 else ''}")

    score = 25
    score -= min(15, missing * 5)
    score -= too_long * 3
    score -= too_short * 3
    score -= duplicates * 5
    score = max(0, score)
    return score, issues


def _score_h_structure(pages_data):
    """Dimension 4: H-Tag Structure (25 pts)."""
    issues = []
    no_h1 = 0
    multi_h1 = 0
    h3_no_h2 = 0
    h1_title_mismatch = 0

    for p in pages_data:
        if not p["h1s"]:
            no_h1 += 1
        elif len(p["h1s"]) > 1:
            multi_h1 += 1

        if p["h3s"] and not p["h2s"]:
            h3_no_h2 += 1

        if p["h1s"] and p["meta_title"]:
            overlap = _word_overlap(p["h1s"][0], p["meta_title"])
            if overlap < 0.3:
                h1_title_mismatch += 1

    if no_h1:
        issues.append(f"{no_h1} page{'s' if no_h1 != 1 else ''} missing H1")
    if multi_h1:
        issues.append(f"{multi_h1} page{'s' if multi_h1 != 1 else ''} have multiple H1 tags")
    if h3_no_h2:
        issues.append(f"{h3_no_h2} page{'s' if h3_no_h2 != 1 else ''} have H3 but no H2")
    if h1_title_mismatch:
        issues.append(f"{h1_title_mismatch} page{'s' if h1_title_mismatch != 1 else ''} where H1 doesn't match meta title")

    score = 25
    score -= min(15, no_h1 * 5)
    score -= multi_h1 * 4
    score -= h3_no_h2 * 2
    score -= h1_title_mismatch * 2
    score = max(0, score)
    return score, issues


# ---------------------------------------------------------------------------
# Main scan orchestrator
# ---------------------------------------------------------------------------

def _run_scan(url):
    """Crawl and score a URL. Returns (score, pages_crawled, results_dict)."""
    start = time.time()

    # Normalize base URL
    if not url.startswith("http"):
        url = "https://" + url
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    # 1. Fetch homepage
    homepage_resp, err = _fetch(base_url + "/", timeout=HOMEPAGE_TIMEOUT)
    if homepage_resp is None:
        return 0, 0, {
            "total_score": 0,
            "grade": "Critical Issues Found",
            "pages_crawled": 0,
            "dimensions": {
                "cannibalization": {"score": 0, "max": 25, "issues": []},
                "schema": {"score": 0, "max": 25, "issues": []},
                "meta_titles": {"score": 0, "max": 25, "issues": []},
                "h_structure": {"score": 0, "max": 25, "issues": []},
            },
            "top_issues": [f"Could not fetch site: {err}"],
            "cta": "Siloq can fix these issues automatically. Start your free trial.",
            "error": f"Could not fetch {url}: {err}",
        }

    # 2. Discover pages via sitemap or link extraction
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

    # 3. Crawl pages (homepage already fetched)
    pages = [{"url": homepage_url, "html": homepage_resp.text, "error": None}]
    remaining = [u for u in page_urls[1:]]
    pages.extend(_crawl_pages(remaining))

    # 4. Extract data from each page
    pages_data = [_extract_page_data(p["html"], p["url"]) for p in pages]

    # 5. Score all dimensions
    cann_score, cann_issues = _score_cannibalization(pages_data)
    schema_score, schema_issues = _score_schema(pages_data)
    meta_score, meta_issues = _score_meta_titles(pages_data)
    htag_score, htag_issues = _score_h_structure(pages_data)

    total_score = cann_score + schema_score + meta_score + htag_score

    if total_score >= 80:
        grade = "Healthy"
    elif total_score >= 60:
        grade = "Needs Attention"
    else:
        grade = "Critical Issues Found"

    # Top issues: collect all, sorted roughly by severity (lower dimension scores first)
    all_issues = []
    for dim_issues in sorted(
        [cann_issues, schema_issues, meta_issues, htag_issues],
        key=lambda x: len(x), reverse=True,
    ):
        all_issues.extend(dim_issues)
    top_issues = all_issues[:5]

    results = {
        "total_score": total_score,
        "grade": grade,
        "pages_crawled": len(pages),
        "dimensions": {
            "cannibalization": {"score": cann_score, "max": 25, "issues": cann_issues},
            "schema": {"score": schema_score, "max": 25, "issues": schema_issues},
            "meta_titles": {"score": meta_score, "max": 25, "issues": meta_issues},
            "h_structure": {"score": htag_score, "max": 25, "issues": htag_issues},
        },
        "top_issues": top_issues,
        "cta": "Siloq can fix these issues automatically. Start your free trial.",
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
        scan.results = {
            "total_score": 0,
            "grade": "Critical Issues Found",
            "pages_crawled": 0,
            "dimensions": {
                "cannibalization": {"score": 0, "max": 25, "issues": []},
                "schema": {"score": 0, "max": 25, "issues": []},
                "meta_titles": {"score": 0, "max": 25, "issues": []},
                "h_structure": {"score": 0, "max": 25, "issues": []},
            },
            "top_issues": ["Scan failed due to an internal error"],
            "cta": "Siloq can fix these issues automatically. Start your free trial.",
            "error": "Internal scan error",
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
            'issues_found': len(scan.results.get('dimensions', {}).get('cannibalization', {}).get('issues', [])),
            'recommendations': scan.results.get('top_issues', []),
        }
    }

    return Response(report)
