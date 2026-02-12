"""
SEO Cannibalization Detection Engine

Based on validated rules from real GSC data analysis:
- E-commerce patterns (Crystallized Couture)
- Service business patterns (EMS Cleanup)

Key Principle: Two pages ranking for similar keywords is only a problem
if they are trying to do the SAME JOB (Intent Hierarchy).
"""
import re
from collections import defaultdict
from typing import List, Dict, Any, Optional, Tuple, Set
from urllib.parse import urlparse
from django.utils import timezone


# =============================================================================
# SYNONYM DICTIONARIES
# =============================================================================

ATTRIBUTE_SYNONYMS = {
    'rhinestone': {'bling', 'crystal', 'sparkle', 'sequin', 'glitter', 'bedazzle'},
    'bling': {'rhinestone', 'crystal', 'sparkle', 'sequin', 'glitter'},
    'custom': {'personalized', 'customized', 'customizable', 'bespoke'},
    'warm up': {'warmup', 'warm-up', 'tracksuit', 'track suit'},
}

LISTICLE_PATTERNS = [
    r'top-?\d+', r'best-', r'\d+-best', r'-guide$', r'-review', 
    r'-tips$', r'-ideas$', r'how-to-'
]

INTENT_MARKERS = {
    'informational': ['how', 'what', 'why', 'guide', 'tips', 'ideas', 'tutorial'],
    'commercial': ['buy', 'price', 'cost', 'near me', 'service', 'company', 'hire'],
    'listicle': ['best', 'top', 'review', 'vs', 'compare', 'ranking'],
    'navigational': ['login', 'contact', 'about', 'hours', 'location'],
}


# =============================================================================
# PAGE TYPE CLASSIFICATION
# =============================================================================

def classify_page_type(url: str, post_type: str = None) -> str:
    """
    Classify a page by its structural type.
    
    Returns: 'blog', 'product', 'category', 'service', 'location', 
             'team', 'homepage', 'general'
    """
    if not url:
        return 'general'
    
    path = urlparse(url).path.lower()
    
    # Homepage check
    if path in ['/', ''] or path.rstrip('/') == '':
        return 'homepage'
    
    # Use post_type if available (from WordPress sync)
    if post_type:
        if post_type == 'product':
            return 'product'
        if post_type in ['product_cat', 'product_category']:
            return 'category'
        if post_type == 'post':
            # Check if it's a listicle blog
            if any(re.search(p, path) for p in LISTICLE_PATTERNS):
                return 'listicle_blog'
            return 'blog'
    
    # URL pattern matching
    patterns = {
        'listicle_blog': LISTICLE_PATTERNS,
        'blog': [r'/blog/', r'/news/', r'/articles/', r'/post/', r'/posts/', r'\d{4}/\d{2}/'],
        'product': [r'/product/', r'/products/', r'/item/', r'/p/', r'/shop/[^/]+/[^/]+'],
        'category': [r'/product-category/', r'/category/', r'/collection/', r'/c/', r'/shop/$'],
        'service': [r'/service/', r'/services/', r'/residential/', r'/commercial/', r'/solutions/'],
        'location': [r'/location/', r'/locations/', r'/service-area/', r'/service-areas/', r'/city/', r'/cities/'],
        'team': [r'/teams?/', r'/groups?/', r'/organizations?/'],
    }
    
    for page_type, regexes in patterns.items():
        for pattern in regexes:
            if re.search(pattern, path):
                return page_type
    
    return 'general'


def is_listicle_url(url: str) -> bool:
    """Check if URL indicates a listicle/best-of article."""
    if not url:
        return False
    path = urlparse(url).path.lower()
    return any(re.search(p, path) for p in LISTICLE_PATTERNS)


def extract_url_keywords(url: str) -> Set[str]:
    """Extract meaningful keywords from URL slug."""
    if not url:
        return set()
    
    try:
        path = urlparse(url).path.strip('/')
    except:
        path = url.strip('/')
    
    # Split by / - _
    parts = re.split(r'[/\-_]', path.lower())
    
    # Filter out noise
    stop_slugs = {
        'page', 'pages', 'post', 'posts', 'product', 'products',
        'category', 'categories', 'tag', 'tags', 'shop', 'store',
        'blog', 'news', 'article', 'articles', 'index', 'home',
        'www', 'http', 'https', 'html', 'php', 'aspx', 'htm',
        'the', 'and', 'for', 'with', 'our', 'your',
    }
    # Also filter years
    stop_slugs.update(str(y) for y in range(2015, 2030))
    
    return {p for p in parts if p and len(p) > 2 and p not in stop_slugs and not p.isdigit()}


def get_query_intent(query: str) -> str:
    """Classify query intent."""
    query = query.lower()
    
    # Check listicle first (most specific)
    if any(w in query for w in INTENT_MARKERS['listicle']):
        return 'listicle'
    if any(w in query for w in INTENT_MARKERS['informational']):
        return 'informational'
    if any(w in query for w in INTENT_MARKERS['navigational']):
        return 'navigational'
    
    # Default to transactional/commercial for product-related queries
    return 'transactional'


def is_plural_query(query: str) -> bool:
    """Check if query appears to be plural (category intent)."""
    words = query.lower().split()
    if not words:
        return False
    # Check last significant word
    last_word = words[-1]
    # Simple heuristic: ends in 's' but not 'ss'
    return last_word.endswith('s') and not last_word.endswith('ss')


def are_synonyms(word1: str, word2: str) -> bool:
    """Check if two words are synonyms based on our dictionary."""
    w1, w2 = word1.lower(), word2.lower()
    if w1 == w2:
        return True
    
    for key, synonyms in ATTRIBUTE_SYNONYMS.items():
        all_words = {key} | synonyms
        if w1 in all_words and w2 in all_words:
            return True
    
    return False


def find_synonym_overlap(keywords1: Set[str], keywords2: Set[str]) -> List[Tuple[str, str]]:
    """Find synonym pairs between two keyword sets."""
    overlaps = []
    for k1 in keywords1:
        for k2 in keywords2:
            if k1 != k2 and are_synonyms(k1, k2):
                overlaps.append((k1, k2))
    return overlaps


# =============================================================================
# STATIC ANALYSIS (Without GSC Data)
# =============================================================================

def detect_static_cannibalization(pages, include_noindex: bool = False) -> List[Dict[str, Any]]:
    """
    Detect potential cannibalization from URL/content analysis.
    This is a PREDICTION - GSC data validates it.
    """
    issues = []
    page_list = list(pages)
    
    if len(page_list) < 2:
        return issues
    
    # Build indexes
    page_data = {}
    for page in page_list:
        if not include_noindex and getattr(page, 'is_noindex', False):
            continue
        
        url = page.url or ''
        page_data[page.id] = {
            'page': page,
            'url': url,
            'title': page.title or '',
            'type': classify_page_type(url, getattr(page, 'post_type', None)),
            'keywords': extract_url_keywords(url),
            'is_money_page': getattr(page, 'is_money_page', False),
            'is_listicle': is_listicle_url(url),
        }
    
    processed_pairs = set()
    
    # Check each pair
    for id_a, data_a in page_data.items():
        for id_b, data_b in page_data.items():
            if id_a >= id_b:
                continue
            
            pair_key = (id_a, id_b)
            if pair_key in processed_pairs:
                continue
            processed_pairs.add(pair_key)
            
            issue = _check_pair_conflict(data_a, data_b)
            if issue:
                issues.append(issue)
    
    # Sort by severity
    severity_order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}
    issues.sort(key=lambda x: severity_order.get(x['severity'], 3))
    
    return issues[:30]


def _check_pair_conflict(data_a: Dict, data_b: Dict) -> Optional[Dict]:
    """Check if two pages have a cannibalization conflict."""
    type_a, type_b = data_a['type'], data_b['type']
    url_a, url_b = data_a['url'], data_b['url']
    kw_a, kw_b = data_a['keywords'], data_b['keywords']
    
    # Calculate keyword overlap
    overlap = kw_a & kw_b
    if not overlap:
        return None
    
    overlap_ratio = len(overlap) / max(len(kw_a | kw_b), 1)
    
    # =========================================================================
    # RULE 1: Listicle Blog vs Category (HIGH - E-commerce)
    # =========================================================================
    if (data_a['is_listicle'] and type_b == 'category') or \
       (data_b['is_listicle'] and type_a == 'category'):
        
        blog_data = data_a if data_a['is_listicle'] else data_b
        cat_data = data_b if data_a['is_listicle'] else data_a
        
        return {
            'type': 'listicle_vs_category',
            'severity': 'HIGH',
            'keyword': ', '.join(overlap),
            'explanation': f"Blog post '{blog_data['title']}' may steal rankings from category page for commercial keywords.",
            'recommendation': "De-optimize blog title for commercial keywords. Add prominent link from blog → category.",
            'competing_pages': [
                {'id': data_a['page'].id, 'url': url_a, 'title': data_a['title'], 'page_type': type_a},
                {'id': data_b['page'].id, 'url': url_b, 'title': data_b['title'], 'page_type': type_b},
            ],
            'suggested_king': {'id': cat_data['page'].id, 'url': cat_data['url'], 'title': cat_data['title']},
        }
    
    # =========================================================================
    # RULE 2: Multiple Listicle Blogs (HIGH - Merge)
    # =========================================================================
    if data_a['is_listicle'] and data_b['is_listicle'] and overlap_ratio > 0.3:
        return {
            'type': 'listicle_vs_listicle',
            'severity': 'HIGH',
            'keyword': ', '.join(overlap),
            'explanation': f"Two 'Best/Top' articles competing: '{data_a['title']}' vs '{data_b['title']}'",
            'recommendation': "MERGE into one comprehensive guide. 301 redirect the weaker article.",
            'competing_pages': [
                {'id': data_a['page'].id, 'url': url_a, 'title': data_a['title'], 'page_type': type_a},
                {'id': data_b['page'].id, 'url': url_b, 'title': data_b['title'], 'page_type': type_b},
            ],
            'suggested_king': None,  # Needs click data to determine
        }
    
    # =========================================================================
    # RULE 3: Attribute Synonyms (MEDIUM - E-commerce)
    # =========================================================================
    synonym_pairs = find_synonym_overlap(kw_a, kw_b)
    if synonym_pairs and type_a == type_b:
        # Two pages of same type with synonym attributes
        return {
            'type': 'attribute_synonym',
            'severity': 'MEDIUM',
            'keyword': f"{synonym_pairs[0][0]} ≈ {synonym_pairs[0][1]}",
            'explanation': f"Pages use synonymous attributes: {synonym_pairs[0][0]} vs {synonym_pairs[0][1]}",
            'recommendation': "301 redirect the weaker page to the stronger. These target the same user intent.",
            'competing_pages': [
                {'id': data_a['page'].id, 'url': url_a, 'title': data_a['title'], 'page_type': type_a},
                {'id': data_b['page'].id, 'url': url_b, 'title': data_b['title'], 'page_type': type_b},
            ],
            'suggested_king': None,  # Needs click data
        }
    
    # =========================================================================
    # RULE 4: Service Audience Split (HIGH - Service Business)
    # =========================================================================
    if ('residential' in url_a.lower() and 'commercial' in url_b.lower()) or \
       ('commercial' in url_a.lower() and 'residential' in url_b.lower()):
        return {
            'type': 'audience_split',
            'severity': 'HIGH',
            'keyword': ', '.join(overlap),
            'explanation': "Residential and Commercial pages for same service. Often 80%+ content overlap.",
            'recommendation': "MERGE if content is similar. REWRITE with 70%+ unique content if keeping both.",
            'competing_pages': [
                {'id': data_a['page'].id, 'url': url_a, 'title': data_a['title'], 'page_type': type_a},
                {'id': data_b['page'].id, 'url': url_b, 'title': data_b['title'], 'page_type': type_b},
            ],
            'suggested_king': None,
        }
    
    # =========================================================================
    # RULE 5: Blog vs Service Page (HIGH - Service Business)
    # =========================================================================
    if (type_a == 'blog' and type_b == 'service') or (type_a == 'service' and type_b == 'blog'):
        blog_data = data_a if type_a == 'blog' else data_b
        service_data = data_b if type_a == 'blog' else data_a
        
        if overlap_ratio > 0.3:
            return {
                'type': 'blog_vs_service',
                'severity': 'HIGH',
                'keyword': ', '.join(overlap),
                'explanation': f"Blog may steal traffic from service page for commercial keywords.",
                'recommendation': "Convert blog to case study that LINKS to service page. Remove commercial keyword targeting from blog.",
                'competing_pages': [
                    {'id': data_a['page'].id, 'url': url_a, 'title': data_a['title'], 'page_type': type_a},
                    {'id': data_b['page'].id, 'url': url_b, 'title': data_b['title'], 'page_type': type_b},
                ],
                'suggested_king': {'id': service_data['page'].id, 'url': service_data['url'], 'title': service_data['title']},
            }
    
    # =========================================================================
    # RULE 6: Location Boilerplate (MEDIUM - Service Business)
    # =========================================================================
    if type_a == 'location' and type_b == 'location' and overlap_ratio > 0.5:
        return {
            'type': 'location_boilerplate',
            'severity': 'MEDIUM',
            'keyword': ', '.join(overlap),
            'explanation': "Location pages have significant URL overlap. Likely templated content.",
            'recommendation': "Rewrite with LOCAL EVIDENCE: job photos, city-specific reviews, local landmarks.",
            'competing_pages': [
                {'id': data_a['page'].id, 'url': url_a, 'title': data_a['title'], 'page_type': type_a},
                {'id': data_b['page'].id, 'url': url_b, 'title': data_b['title'], 'page_type': type_b},
            ],
            'suggested_king': None,
        }
    
    # =========================================================================
    # SAFE PATTERNS - DO NOT FLAG
    # =========================================================================
    
    # Category + Product = SAFE (different intents)
    if {type_a, type_b} == {'category', 'product'}:
        return None
    
    # Team + Product = SAFE (parent-child)
    if {type_a, type_b} == {'team', 'product'}:
        return None
    
    # Service + Location = SAFE (should cross-link)
    if {type_a, type_b} == {'service', 'location'}:
        return None
    
    # =========================================================================
    # FALLBACK: High overlap but unclassified
    # =========================================================================
    if overlap_ratio > 0.6:
        return {
            'type': 'url_overlap',
            'severity': 'LOW',
            'keyword': ', '.join(overlap),
            'explanation': f"High URL keyword overlap ({int(overlap_ratio*100)}%) detected.",
            'recommendation': "Review manually - may need differentiation or consolidation.",
            'competing_pages': [
                {'id': data_a['page'].id, 'url': url_a, 'title': data_a['title'], 'page_type': type_a},
                {'id': data_b['page'].id, 'url': url_b, 'title': data_b['title'], 'page_type': type_b},
            ],
            'suggested_king': None,
        }
    
    return None


# =============================================================================
# GSC DATA ANALYSIS (The "Ultimate Truth")
# =============================================================================

def analyze_gsc_data(gsc_data: List[Dict]) -> List[Dict[str, Any]]:
    """
    Analyze GSC data to find validated cannibalization.
    
    Input: List of dicts with keys: query, page_url, clicks, impressions, position
    Output: List of confirmed conflicts
    """
    issues = []
    
    # Filter noise (< 20 impressions)
    valid_data = [d for d in gsc_data if d.get('impressions', 0) >= 20]
    
    # Group by query
    query_groups = defaultdict(list)
    for row in valid_data:
        query_groups[row['query'].lower()].append(row)
    
    for query, rows in query_groups.items():
        if len(rows) < 2:
            continue
        
        # Sort by impressions (highest first)
        rows.sort(key=lambda x: x.get('impressions', 0), reverse=True)
        
        total_imps = sum(r.get('impressions', 0) for r in rows)
        if total_imps == 0:
            continue
        
        # Top 2 contenders
        leader = rows[0]
        challenger = rows[1]
        
        leader_share = leader.get('impressions', 0) / total_imps
        challenger_share = challenger.get('impressions', 0) / total_imps
        
        # If leader has >90% share, Google has decided - skip
        if leader_share > 0.9:
            continue
        
        # Classify pages and query
        leader_type = classify_page_type(leader.get('page_url', ''))
        challenger_type = classify_page_type(challenger.get('page_url', ''))
        query_intent = get_query_intent(query)
        is_plural = is_plural_query(query)
        
        issue = _check_gsc_conflict(
            query, query_intent, is_plural,
            leader, leader_type, leader_share,
            challenger, challenger_type, challenger_share
        )
        
        if issue:
            issues.append(issue)
    
    # Sort by severity
    severity_order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}
    issues.sort(key=lambda x: severity_order.get(x['severity'], 3))
    
    return issues[:50]


def _check_gsc_conflict(
    query: str, query_intent: str, is_plural: bool,
    leader: Dict, leader_type: str, leader_share: float,
    challenger: Dict, challenger_type: str, challenger_share: float
) -> Optional[Dict]:
    """Check GSC data for specific conflict patterns."""
    
    leader_url = leader.get('page_url', '')
    challenger_url = challenger.get('page_url', '')
    leader_clicks = leader.get('clicks', 0)
    challenger_clicks = challenger.get('clicks', 0)
    
    split_str = f"{int(leader_share*100)}% / {int(challenger_share*100)}%"
    
    # =========================================================================
    # GSC RULE 1: Blog vs Category for Commercial Query
    # =========================================================================
    if query_intent == 'transactional':
        leader_is_blog = leader_type in ['blog', 'listicle_blog']
        challenger_is_blog = challenger_type in ['blog', 'listicle_blog']
        
        if (leader_is_blog and challenger_type == 'category') or \
           (challenger_is_blog and leader_type == 'category'):
            
            blog_url = leader_url if leader_is_blog else challenger_url
            cat_url = challenger_url if leader_is_blog else leader_url
            
            return {
                'type': 'gsc_blog_vs_category',
                'severity': 'HIGH',
                'query': query,
                'explanation': f"Blog competing with Category for commercial query.",
                'recommendation': "De-optimize blog for this keyword. Link blog → category.",
                'impression_split': split_str,
                'competing_pages': [
                    {'url': leader_url, 'type': leader_type, 'clicks': leader_clicks, 'share': f"{int(leader_share*100)}%"},
                    {'url': challenger_url, 'type': challenger_type, 'clicks': challenger_clicks, 'share': f"{int(challenger_share*100)}%"},
                ],
                'suggested_winner': cat_url,
            }
    
    # =========================================================================
    # GSC RULE 2: Product Ranking for Plural Query (Wrong Page Type)
    # =========================================================================
    if is_plural and leader_type == 'product':
        return {
            'type': 'gsc_product_for_plural',
            'severity': 'MEDIUM',
            'query': query,
            'explanation': f"Product page ranking for plural query '{query}' (category intent).",
            'recommendation': "Strengthen Category page. Check if Product is over-optimized for generic terms.",
            'impression_split': split_str,
            'competing_pages': [
                {'url': leader_url, 'type': leader_type, 'clicks': leader_clicks, 'share': f"{int(leader_share*100)}%"},
                {'url': challenger_url, 'type': challenger_type, 'clicks': challenger_clicks, 'share': f"{int(challenger_share*100)}%"},
            ],
            'suggested_winner': challenger_url if challenger_type == 'category' else None,
        }
    
    # =========================================================================
    # GSC RULE 3: Audience Split (Res vs Comm)
    # =========================================================================
    if ('residential' in leader_url.lower() and 'commercial' in challenger_url.lower()) or \
       ('commercial' in leader_url.lower() and 'residential' in challenger_url.lower()):
        return {
            'type': 'gsc_audience_split',
            'severity': 'HIGH',
            'query': query,
            'explanation': f"Residential and Commercial pages splitting impressions 50/50.",
            'recommendation': "MERGE pages if service is identical. REWRITE with 70%+ unique content if keeping both.",
            'impression_split': split_str,
            'competing_pages': [
                {'url': leader_url, 'type': leader_type, 'clicks': leader_clicks, 'share': f"{int(leader_share*100)}%"},
                {'url': challenger_url, 'type': challenger_type, 'clicks': challenger_clicks, 'share': f"{int(challenger_share*100)}%"},
            ],
            'suggested_winner': None,
        }
    
    # =========================================================================
    # GSC RULE 4: Homepage Cannibalization
    # =========================================================================
    if leader_type == 'homepage' and challenger_type == 'service':
        return {
            'type': 'gsc_homepage_hoarding',
            'severity': 'MEDIUM',
            'query': query,
            'explanation': f"Homepage ranking instead of dedicated Service page.",
            'recommendation': "Prune service content from homepage. Add clear link HP → Service page.",
            'impression_split': split_str,
            'competing_pages': [
                {'url': leader_url, 'type': leader_type, 'clicks': leader_clicks, 'share': f"{int(leader_share*100)}%"},
                {'url': challenger_url, 'type': challenger_type, 'clicks': challenger_clicks, 'share': f"{int(challenger_share*100)}%"},
            ],
            'suggested_winner': challenger_url,
        }
    
    # =========================================================================
    # GSC RULE 5: Near 50/50 Split (Direct Competition)
    # =========================================================================
    if challenger_share > 0.35 and leader_type == challenger_type:
        return {
            'type': 'gsc_direct_competition',
            'severity': 'MEDIUM',
            'query': query,
            'explanation': f"Two {leader_type} pages splitting traffic nearly 50/50.",
            'recommendation': "Consolidate or Canonicalize. Google can't decide which to rank.",
            'impression_split': split_str,
            'competing_pages': [
                {'url': leader_url, 'type': leader_type, 'clicks': leader_clicks, 'share': f"{int(leader_share*100)}%"},
                {'url': challenger_url, 'type': challenger_type, 'clicks': challenger_clicks, 'share': f"{int(challenger_share*100)}%"},
            ],
            'suggested_winner': leader_url if leader_clicks > challenger_clicks else challenger_url,
        }
    
    # =========================================================================
    # GSC RULE 6: Authority Dilution (High Imps, Zero Clicks on Blog)
    # =========================================================================
    if leader_type in ['blog', 'listicle_blog'] and leader_clicks == 0 and leader.get('impressions', 0) > 50:
        return {
            'type': 'gsc_authority_dilution',
            'severity': 'LOW',
            'query': query,
            'explanation': f"Blog ranking for '{query}' but getting 0 clicks. May be wrong audience.",
            'recommendation': "Re-optimize blog title to be more niche-specific. Remove generic keyword targeting.",
            'impression_split': split_str,
            'competing_pages': [
                {'url': leader_url, 'type': leader_type, 'clicks': leader_clicks, 'share': f"{int(leader_share*100)}%"},
            ],
            'suggested_winner': None,
        }
    
    return None


# =============================================================================
# HEALTH SCORE CALCULATION
# =============================================================================

def calculate_health_score(site) -> Dict[str, Any]:
    """Calculate site SEO health score."""
    pages = site.pages.all()
    total_pages = pages.count()
    
    if total_pages == 0:
        return {
            'health_score': 0,
            'health_score_delta': 0,
            'breakdown': {'base_score': 0, 'cannibalization_penalty': 0, 'seo_data_penalty': 0, 'money_page_bonus': 0}
        }
    
    score = 75
    
    # Cannibalization penalties
    issues = detect_static_cannibalization(pages)
    penalty = sum(10 if i['severity'] == 'HIGH' else 5 if i['severity'] == 'MEDIUM' else 2 for i in issues)
    score -= min(penalty, 40)
    
    # SEO data penalty
    pages_without_seo = sum(1 for p in pages if not hasattr(p, 'seo_data') or not p.seo_data)
    seo_penalty = min((pages_without_seo / total_pages) * 20, 20)
    score -= seo_penalty
    
    # Money page bonus
    money_pages = pages.filter(is_money_page=True).count()
    if money_pages > 0:
        score += 5
    
    return {
        'health_score': max(0, min(100, round(score))),
        'health_score_delta': 0,
        'breakdown': {
            'base_score': 75,
            'cannibalization_penalty': -penalty,
            'seo_data_penalty': -round(seo_penalty),
            'money_page_bonus': 5 if money_pages > 0 else 0,
        }
    }


# =============================================================================
# MAIN ANALYSIS FUNCTION
# =============================================================================

def detect_cannibalization(pages, include_noindex: bool = False) -> List[Dict[str, Any]]:
    """
    Main entry point for cannibalization detection (static analysis).
    For GSC-validated analysis, use analyze_gsc_data() separately.
    """
    return detect_static_cannibalization(pages, include_noindex)


def analyze_site(site) -> Dict[str, Any]:
    """Run full analysis on a site."""
    pages = site.pages.all().prefetch_related('seo_data')
    
    health = calculate_health_score(site)
    issues = detect_static_cannibalization(pages)
    
    # Count by severity
    high_count = sum(1 for i in issues if i['severity'] == 'HIGH')
    medium_count = sum(1 for i in issues if i['severity'] == 'MEDIUM')
    
    return {
        'site_id': site.id,
        'analyzed_at': timezone.now().isoformat(),
        'health_score': health['health_score'],
        'health_score_delta': health['health_score_delta'],
        'health_breakdown': health['breakdown'],
        'cannibalization_issues': issues,
        'cannibalization_count': len(issues),
        'high_severity_count': high_count,
        'medium_severity_count': medium_count,
        'recommendations': _generate_recommendations(issues),
        'recommendation_count': len(issues),
        'page_count': pages.count(),
        'money_page_count': pages.filter(is_money_page=True).count(),
    }


def _generate_recommendations(issues: List[Dict]) -> List[Dict]:
    """Generate actionable recommendations from issues."""
    recs = []
    for issue in issues[:10]:
        recs.append({
            'type': issue['type'],
            'priority': issue['severity'],
            'title': f"Fix: {issue['type'].replace('_', ' ').title()}",
            'description': issue['explanation'],
            'action': issue['recommendation'],
            'competing_pages': issue.get('competing_pages', []),
        })
    return recs
