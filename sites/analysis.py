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
        'product': [r'/product/', r'/products/', r'/item/', r'/p/', r'/shop/[^/]+/[^/]+/?$'],
        'category': [r'/product-category/', r'/category/', r'/collection/', r'/c/', r'/shop/[^/]+/?$', r'/product-rentals/[^/]+/?$'],
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


STOP_WORDS = {
    'page', 'pages', 'post', 'posts', 'product', 'products',
    'category', 'categories', 'tag', 'tags', 'shop', 'store',
    'blog', 'news', 'article', 'articles', 'index', 'home',
    'www', 'http', 'https', 'html', 'php', 'aspx', 'htm',
    'the', 'and', 'for', 'with', 'our', 'your', 'all', 'you',
    'how', 'what', 'why', 'when', 'where', 'which', 'who',
    'this', 'that', 'from', 'into', 'about', 'more', 'most',
    'one', 'stop', 'need', 'needs', 'right', 'best', 'top',
    'choose', 'choosing', 'find', 'finding', 'get', 'getting',
}
STOP_WORDS.update(str(y) for y in range(2015, 2030))


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
    
    return {p for p in parts if p and len(p) > 2 and p not in STOP_WORDS and not p.isdigit()}


def extract_title_keywords(title: str) -> Set[str]:
    """Extract meaningful keywords from page title."""
    if not title:
        return set()
    
    # Split by spaces and common separators
    parts = re.split(r'[\s\-–—|:,./]+', title.lower())
    
    return {p for p in parts if p and len(p) > 2 and p not in STOP_WORDS and not p.isdigit()}


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

def detect_static_cannibalization(pages, include_noindex: bool = False, impressions_map: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    """
    Detect potential cannibalization from URL/content analysis.
    This is a PREDICTION - GSC data validates it.
    """
    issues = []
    page_list = list(pages)
    
    if impressions_map is None:
        impressions_map = {}

    if len(page_list) < 2:
        return issues
    
    # Build indexes
    page_data = {}
    for page in page_list:
        if not include_noindex and getattr(page, 'is_noindex', False):
            continue
        
        url = page.url or ''
        title = page.title or ''
        url_kw = extract_url_keywords(url)
        title_kw = extract_title_keywords(title)
        # Combined keywords = union of URL + title keywords for broader matching
        combined_kw = url_kw | title_kw
        page_data[page.id] = {
            'page': page,
            'url': url,
            'title': title,
            'type': classify_page_type(url, getattr(page, 'post_type', None)),
            'keywords': url_kw,
            'title_keywords': title_kw,
            'combined_keywords': combined_kw,
            'is_money_page': getattr(page, 'is_money_page', False),
            'is_listicle': is_listicle_url(url),
        }
    
    # =========================================================================
    # PRE-SCAN: Detect duplicate folder structures (same slug in different paths)
    # This catches /shop/X, /product-rentals/X, /product-category/X patterns
    # =========================================================================
    raw_issues = []
    slug_to_pages = defaultdict(list)  # final slug -> list of page data
    for pid, data in page_data.items():
        path = urlparse(data['url']).path.rstrip('/')
        if not path:
            continue
        slug = path.split('/')[-1]
        if slug:
            slug_to_pages[slug].append(data)
    
    # Pages involved in folder duplication — track to avoid double-flagging
    folder_dup_ids = set()
    
    for slug, pages_with_slug in slug_to_pages.items():
        if len(pages_with_slug) < 2:
            continue
        
        # Get the parent folders for each page with this slug
        folder_groups = defaultdict(list)
        for pd in pages_with_slug:
            path = urlparse(pd['url']).path.rstrip('/')
            parts = path.strip('/').split('/')
            parent = '/'.join(parts[:-1]) if len(parts) > 1 else '/'
            folder_groups[parent].append(pd)
        
        # If same slug exists in 2+ different parent folders = duplicate folder structure
        if len(folder_groups) >= 2:
            all_dup_pages = []
            for folder_pages in folder_groups.values():
                for pd in folder_pages:
                    all_dup_pages.append({
                        'id': pd['page'].id, 'url': pd['url'],
                        'title': pd['title'], 'page_type': pd['type'],
                    })
                    folder_dup_ids.add(pd['page'].id)
            
            raw_issues.append({
                'type': 'duplicate_folder',
                'severity': 'HIGH',
                '_shared_slug': slug,
                'keyword': slug.replace('-', ' '),
                'explanation': f"'{slug}' exists under {len(folder_groups)} different URL folders. Each duplicate splits authority for the same keywords.",
                'recommendation': "Pick ONE canonical folder structure, 301 redirect the others to it.",
                'competing_pages': all_dup_pages,
                'suggested_king': all_dup_pages[0] if all_dup_pages else None,
            })
    
    # =========================================================================
    # PRE-SCAN: Detect -old suffix pages (immediate redirect candidates)
    # =========================================================================
    for pid, data in page_data.items():
        path = urlparse(data['url']).path.rstrip('/')
        if '-old' in path.split('/')[-1]:
            # Find the non-old version
            clean_path = path.replace('-old', '')
            for pid2, data2 in page_data.items():
                if pid2 != pid and urlparse(data2['url']).path.rstrip('/') == clean_path:
                    raw_issues.append({
                        'type': 'near_duplicate_url',
                        'severity': 'HIGH',
                        'keyword': clean_path.split('/')[-1].replace('-', ' '),
                        'explanation': f"Page has an '-old' version that should be redirected immediately.",
                        'recommendation': "301 redirect the -old URL to the current version.",
                        'competing_pages': [
                            {'id': data['page'].id, 'url': data['url'], 'title': data['title'], 'page_type': data['type']},
                            {'id': data2['page'].id, 'url': data2['url'], 'title': data2['title'], 'page_type': data2['type']},
                        ],
                        'suggested_king': {'id': data2['page'].id, 'url': data2['url'], 'title': data2['title']},
                    })
                    folder_dup_ids.add(pid)
                    folder_dup_ids.add(pid2)
                    break
    
    # =========================================================================
    # PAIRWISE COMPARISON (skip pages already flagged in pre-scans)
    # =========================================================================
    keyword_to_pages = defaultdict(set)
    for pid, data in page_data.items():
        if pid in folder_dup_ids:
            continue  # Already handled
        for kw in data['combined_keywords']:
            keyword_to_pages[kw].add(pid)
    
    pair_shared_count = defaultdict(int)
    for kw, pids in keyword_to_pages.items():
        pid_list = sorted(pids)
        for i in range(len(pid_list)):
            for j in range(i + 1, len(pid_list)):
                pair_shared_count[(pid_list[i], pid_list[j])] += 1
    
    candidate_pairs = {pair for pair, count in pair_shared_count.items() if count >= 2}
    
    for id_a, id_b in candidate_pairs:
        data_a = page_data[id_a]
        data_b = page_data[id_b]
        
        issue = _check_pair_conflict(data_a, data_b, impressions=impressions_map)
        if issue:
            # Apply impression-weighted severity capping
            issue = _apply_impression_severity(issue, impressions_map)
            raw_issues.append(issue)
    
    # =========================================================================
    # CLUSTER GROUPING: Merge pairwise conflicts into clusters
    # If 6 location pages all trigger "location_boilerplate", show 1 cluster
    # with 6 pages — NOT 15 pairwise conflicts.
    # =========================================================================
    issues = _cluster_issues(raw_issues)
    
    # Tag all static issues as "potential" - not GSC validated
    for issue in issues:
        issue['validation_status'] = 'potential'
        issue['validation_source'] = 'url_pattern'
        issue['gsc_data'] = None
    
    # Sort by severity
    severity_order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2, 'INFO': 3}
    issues.sort(key=lambda x: severity_order.get(x['severity'], 4))
    
    return issues[:30]


def _get_cluster_key(issue: Dict) -> str:
    """
    Get a specific clustering key for an issue.
    Each cluster must contain pages that share the SAME fix.
    """
    conflict_type = issue.get('type', 'unknown')
    pages = issue.get('competing_pages', [])
    urls = [p.get('url', '') for p in pages]
    
    if conflict_type == 'near_duplicate_url':
        # Cluster by the BASE slug (without -2, -old suffix)
        # So obstacle-course pairs stay separate from belmont-stakes pairs
        for url in urls:
            slug = urlparse(url).path.rstrip('/').split('/')[-1]
            base_slug = re.sub(r'-\d+$', '', slug).rstrip('-')
            return f"near_duplicate:{base_slug}"
    
    if conflict_type == 'duplicate_folder':
        # Cluster by the shared slug/category name
        slug = issue.get('_shared_slug', '')
        return f"duplicate_folder:{slug}"
    
    if conflict_type == 'location_boilerplate':
        # Cluster by the service keyword
        for url in urls:
            path = urlparse(url).path.lower().strip('/')
            parts = path.split('/')
            if len(parts) >= 2 and parts[0] in ('service-area', 'service-areas', 'locations', 'location'):
                return f"location_boilerplate:{parts[1]}"
    
    # Default: cluster by type + shared keyword
    kw = issue.get('keyword', '')
    return f"{conflict_type}:{kw[:50]}"


def _cluster_issues(raw_issues: List[Dict]) -> List[Dict]:
    """
    Group pairwise conflicts into clusters.
    
    Rules:
    - Every cluster must contain pages that share the SAME conflict type AND same fix.
    - Max 15 pages per cluster. If larger, it means grouping is too broad.
    - Near-duplicate pairs cluster by their BASE slug (not all near-dupes together).
    """
    if not raw_issues:
        return []
    
    # Group by specific cluster key
    cluster_map = defaultdict(lambda: {
        'pages': {},
        'issues': [],
        'type': None,
        'severity': None,
        'explanation': None,
        'recommendation': None,
        'suggested_king': None,
    })
    
    for issue in raw_issues:
        cluster_key = _get_cluster_key(issue)
        
        cluster = cluster_map[cluster_key]
        cluster['type'] = issue.get('type', 'unknown')
        cluster['issues'].append(issue)
        
        sev_order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}
        if cluster['severity'] is None or sev_order.get(issue['severity'], 3) < sev_order.get(cluster['severity'], 3):
            cluster['severity'] = issue['severity']
            cluster['explanation'] = issue.get('explanation', '')
            cluster['recommendation'] = issue.get('recommendation', '')
        
        if issue.get('suggested_king') and not cluster['suggested_king']:
            cluster['suggested_king'] = issue['suggested_king']
        
        for page in issue.get('competing_pages', []):
            pid = page.get('id')
            if pid and pid not in cluster['pages']:
                cluster['pages'][pid] = page
    
    # Convert clusters to issue format
    clustered_issues = []
    for cluster_key, cluster in cluster_map.items():
        all_pages = list(cluster['pages'].values())
        num_pairs = len(cluster['issues'])
        
        # Extract display keyword from cluster key
        display_keyword = cluster_key.split(':', 1)[-1].replace('-', ' ').replace('_', ' ') if ':' in cluster_key else cluster_key
        
        if len(all_pages) >= 3:
            clustered_issues.append({
                'type': cluster['type'],
                'severity': cluster['severity'],
                'keyword': display_keyword,
                'is_cluster': True,
                'cluster_size': len(all_pages),
                'pairs_collapsed': num_pairs,
                'explanation': f"{len(all_pages)} pages involved. " + (cluster['explanation'] or ''),
                'recommendation': cluster['recommendation'] or '',
                'competing_pages': all_pages[:15],  # Cap display at 15
                'suggested_king': cluster['suggested_king'],
            })
        else:
            issue = cluster['issues'][0]
            orig_kw = issue.get('keyword', display_keyword)
            if orig_kw.count(',') >= 4:
                orig_kw = display_keyword
            issue['keyword'] = orig_kw
            clustered_issues.append(issue)
    
    return clustered_issues


def _extract_geographic_slug(url: str) -> Optional[str]:
    """Extract the geographic/city slug from a location URL."""
    path = urlparse(url).path.lower().strip('/')
    parts = path.split('/')
    
    # Common patterns:
    # /service-area/<service>/<city>/  → city is last
    # /locations/<city>/               → city is last
    # /service-areas/<city>/           → city is last
    if len(parts) >= 2:
        # Last non-empty segment is likely the city
        last = parts[-1]
        # Check it's not a service word
        service_words = {'service', 'services', 'area', 'areas', 'location', 'locations'}
        if last and last not in service_words:
            return last
    
    return None


def _extract_location_service(url: str) -> Optional[str]:
    """Extract the service keyword from a location URL like /service-area/event-planner/brooklyn/."""
    path = urlparse(url).path.lower().strip('/')
    parts = path.split('/')
    
    # Pattern: <folder>/<service>/<city>
    location_folders = {'service-area', 'service-areas', 'locations', 'location', 'city', 'areas'}
    if len(parts) >= 3 and parts[0] in location_folders:
        return parts[1].replace('-', ' ')
    if len(parts) >= 2 and parts[0] in location_folders:
        return parts[1].replace('-', ' ')
    
    return None


def _is_parent_child(url_a: str, url_b: str) -> bool:
    """Check if one URL is a parent (hub) of the other (spoke) by URL path."""
    path_a = urlparse(url_a).path.rstrip('/')
    path_b = urlparse(url_b).path.rstrip('/')
    
    if not path_a or not path_b or path_a == path_b:
        return False
    
    return path_b.startswith(path_a + '/') or path_a.startswith(path_b + '/')


def _apply_impression_severity(issue: Dict, impressions_map: Dict[str, int]) -> Dict:
    """Apply impression-weighted severity capping to a cannibalization issue.
    
    Rules:
    - Both pages have 0 impressions AND score < 20 → 'INFO'
    - Both pages have 0 impressions → cap at 'LOW'
    - Max impressions < 10 → cap at 'MEDIUM'
    - Adds impression data to competing_pages and total_impressions to issue
    """
    if not impressions_map:
        return issue

    severity_rank = {'INFO': 0, 'LOW': 1, 'MEDIUM': 2, 'HIGH': 3}
    competing = issue.get('competing_pages', [])
    page_impressions = []

    for page in competing:
        url = page.get('url', '')
        imp = impressions_map.get(url, 0)
        page['impressions'] = imp
        page_impressions.append(imp)

    max_imp = max(page_impressions) if page_impressions else 0
    all_zero = all(i == 0 for i in page_impressions)
    issue['total_impressions'] = sum(page_impressions)

    current = issue.get('severity', 'LOW')

    if all_zero:
        # Cosmetic similarity only — compute a rough score from overlap ratio in keyword field
        kw_count = len(issue.get('keyword', '').split(', '))
        if kw_count < 3:
            cap = 'INFO'
        else:
            cap = 'LOW'
        if severity_rank.get(current, 1) > severity_rank.get(cap, 0):
            issue['severity'] = cap
    elif max_imp < 10:
        if severity_rank.get(current, 2) > severity_rank['MEDIUM']:
            issue['severity'] = 'MEDIUM'

    return issue


def _check_pair_conflict(data_a: Dict, data_b: Dict, impressions: Optional[Dict[str, int]] = None) -> Optional[Dict]:
    """Check if two pages have a cannibalization conflict."""
    type_a, type_b = data_a['type'], data_b['type']
    url_a, url_b = data_a['url'], data_b['url']
    # Use combined keywords (URL + title) for overlap detection
    kw_a = data_a.get('combined_keywords') or data_a['keywords']
    kw_b = data_b.get('combined_keywords') or data_b['keywords']
    
    # Calculate keyword overlap
    overlap = kw_a & kw_b
    if not overlap:
        return None
    
    overlap_ratio = len(overlap) / max(len(kw_a | kw_b), 1)
    
    # =========================================================================
    # PARENT-CHILD EXCLUSION: Hub page and spoke page = SAFE
    # A category/hub and its child pages sharing keywords is correct architecture
    # =========================================================================
    if _is_parent_child(url_a, url_b):
        return None
    
    # =========================================================================
    # RULE 1: Listicle Blog vs Category (HIGH - E-commerce)
    # Requires meaningful keyword phrase overlap, not just a single generic word
    # =========================================================================
    if (data_a['is_listicle'] and type_b == 'category') or \
       (data_b['is_listicle'] and type_a == 'category'):
        
        blog_data = data_a if data_a['is_listicle'] else data_b
        cat_data = data_b if data_a['is_listicle'] else data_a
        
        # Must share at least 2 meaningful keywords to be a real conflict
        # "dance" alone matching a dance jacket blog and a dance team category is NOT cannibalization
        if len(overlap) < 2:
            return None
        
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
    if data_a['is_listicle'] and data_b['is_listicle'] and overlap_ratio > 0.3 and len(overlap) >= 2:
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
    # RULE 6: Location Pages — Geography Exclusion + Boilerplate Detection
    # =========================================================================
    if type_a == 'location' and type_b == 'location':
        # Extract geographic slugs from URLs
        geo_a = _extract_geographic_slug(url_a)
        geo_b = _extract_geographic_slug(url_b)
        
        # Different cities targeting the same service = SAFE (valid local SEO architecture)
        if geo_a and geo_b and geo_a != geo_b:
            # Only flag if titles are nearly identical (boilerplate content issue, not keyword conflict)
            title_a = data_a['title'].lower()
            title_b = data_b['title'].lower()
            # Strip city names from titles to compare service description
            for geo in (geo_a, geo_b):
                for variant in (geo, geo.replace('-', ' ')):
                    title_a = title_a.replace(variant, '').strip()
                    title_b = title_b.replace(variant, '').strip()
            
            # If titles are identical after stripping city = boilerplate
            if title_a and title_b and title_a == title_b:
                service_kw = _extract_location_service(url_a) or ', '.join(overlap)
                return {
                    'type': 'location_boilerplate',
                    'severity': 'MEDIUM',
                    'keyword': service_kw,
                    'explanation': f"Location pages for different cities share identical templated content. This is a content quality issue, not a keyword conflict.",
                    'recommendation': "Rewrite each with unique local evidence: local venue references, neighborhood-specific reviews, area-specific photos, local partnerships.",
                    'competing_pages': [
                        {'id': data_a['page'].id, 'url': url_a, 'title': data_a['title'], 'page_type': type_a},
                        {'id': data_b['page'].id, 'url': url_b, 'title': data_b['title'], 'page_type': type_b},
                    ],
                    'suggested_king': None,
                }
            
            # Different cities, different content = SAFE
            return None
        
        # Same city or unknown geography with high overlap = potential conflict
        if overlap_ratio > 0.5:
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
        
        # Location pages with low overlap = SAFE
        return None
    
    # =========================================================================
    # RULE 7: Near-Duplicate URLs (HIGH - e.g. /obstacle-course/ vs /obstacle-course-2/)
    # =========================================================================
    path_a = urlparse(url_a).path.rstrip('/')
    path_b = urlparse(url_b).path.rstrip('/')
    # Check if one URL is the other plus a number suffix
    if re.match(re.escape(path_a) + r'-\d+$', path_b) or \
       re.match(re.escape(path_b) + r'-\d+$', path_a):
        return {
            'type': 'near_duplicate_url',
            'severity': 'HIGH',
            'keyword': path_a.split('/')[-1].replace('-', ' '),
            'explanation': f"Near-duplicate URLs detected. One appears to be a numbered variant of the other.",
            'recommendation': "Consolidate into one URL. 301 redirect the numbered variant to the primary page.",
            'competing_pages': [
                {'id': data_a['page'].id, 'url': url_a, 'title': data_a['title'], 'page_type': type_a},
                {'id': data_b['page'].id, 'url': url_b, 'title': data_b['title'], 'page_type': type_b},
            ],
            'suggested_king': {'id': data_a['page'].id, 'url': url_a, 'title': data_a['title']},
        }
    
    # =========================================================================
    # RULE 8: Title Keyword Overlap (Service Business — catches blog vs service via titles)
    # Two pages with 50%+ title keyword overlap targeting the same topic
    # =========================================================================
    title_kw_a = data_a.get('title_keywords', set())
    title_kw_b = data_b.get('title_keywords', set())
    title_overlap = title_kw_a & title_kw_b
    title_overlap_ratio = len(title_overlap) / max(len(title_kw_a | title_kw_b), 1) if (title_kw_a or title_kw_b) else 0
    
    if title_overlap_ratio >= 0.4 and len(title_overlap) >= 2:
        # Blog/general page competing with service page via title keywords
        if type_a != type_b and 'blog' in (type_a, type_b) or 'general' in (type_a, type_b):
            sev = 'HIGH' if title_overlap_ratio >= 0.6 else 'MEDIUM'
            return {
                'type': 'title_keyword_overlap',
                'severity': sev,
                'keyword': ', '.join(sorted(title_overlap)[:5]),
                'explanation': f"Pages have {int(title_overlap_ratio*100)}% title keyword overlap: '{data_a['title']}' vs '{data_b['title']}'",
                'recommendation': "The blog/informational page should link to the service page and avoid targeting the same primary keyword.",
                'competing_pages': [
                    {'id': data_a['page'].id, 'url': url_a, 'title': data_a['title'], 'page_type': type_a},
                    {'id': data_b['page'].id, 'url': url_b, 'title': data_b['title'], 'page_type': type_b},
                ],
                'suggested_king': None,
            }
        # Same type pages with high title overlap
        if type_a == type_b and title_overlap_ratio >= 0.5:
            return {
                'type': 'title_keyword_overlap',
                'severity': 'MEDIUM',
                'keyword': ', '.join(sorted(title_overlap)[:5]),
                'explanation': f"Two {type_a} pages with {int(title_overlap_ratio*100)}% title keyword overlap may compete for the same queries.",
                'recommendation': "Differentiate titles and target keywords, or consolidate into one stronger page.",
                'competing_pages': [
                    {'id': data_a['page'].id, 'url': url_a, 'title': data_a['title'], 'page_type': type_a},
                    {'id': data_b['page'].id, 'url': url_b, 'title': data_b['title'], 'page_type': type_b},
                ],
                'suggested_king': None,
            }
    
    # =========================================================================
    # SAFE PATTERNS - DO NOT FLAG
    # =========================================================================
    
    # Category + Product = SAFE (different intents: browse vs buy)
    if {type_a, type_b} == {'category', 'product'}:
        return None
    
    # Product + Product with distinct slugs = SAFE (valid product catalog)
    # Products in the same or different categories are individual items, not competing
    if type_a == 'product' and type_b == 'product':
        slug_a = urlparse(url_a).path.rstrip('/').split('/')[-1]
        slug_b = urlparse(url_b).path.rstrip('/').split('/')[-1]
        if slug_a != slug_b:
            return None
    
    # Team pages are organizational/navigational - SAFE with everything
    # Teams are specific organizations (e.g. "Starlight Dance Center"), not SEO targets
    if type_a == 'team' or type_b == 'team':
        return None
    
    # Service + Location = SAFE (should cross-link)
    if {type_a, type_b} == {'service', 'location'}:
        return None
    
    # =========================================================================
    # ADDITIONAL SAFE PATTERNS
    # =========================================================================
    
    # Category + Category = likely duplicate folder (handled in pre-scan) or safe
    if type_a == 'category' and type_b == 'category':
        return None  # Duplicate folders caught in pre-scan; remaining are safe
    
    # General/page types with parent-child URL relationship = SAFE
    # (Parent-child check is at the top, but catch any that slipped through)
    
    # If pages are deeply nested under different top-level sections = different context
    parts_a = [p for p in urlparse(url_a).path.strip('/').split('/') if p]
    parts_b = [p for p in urlparse(url_b).path.strip('/').split('/') if p]
    if len(parts_a) >= 2 and len(parts_b) >= 2 and parts_a[0] != parts_b[0]:
        # Different top-level sections (e.g., /event-services/ vs /shop/) = usually different intent
        # Only flag if overlap is extremely high AND same page type
        if overlap_ratio < 0.8 or type_a != type_b:
            return None
    
    # =========================================================================
    # FALLBACK: High overlap, same page type, unclassified
    # Now uses combined (URL+title) keywords, so lower threshold is appropriate
    # =========================================================================
    if overlap_ratio > 0.5 and type_a == type_b and len(overlap) >= 3:
        return {
            'type': 'url_overlap',
            'severity': 'LOW',
            'keyword': ', '.join(sorted(overlap)[:5]),
            'explanation': f"High URL keyword overlap ({int(overlap_ratio*100)}%) between two {type_a} pages.",
            'recommendation': "Review manually — may need differentiation or consolidation.",
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
        
        # Include ALL pages in cluster, not just top 2
        all_pages_in_cluster = rows[:]
        
        # Top 2 contenders
        leader = rows[0]
        challenger = rows[1]
        
        leader_share = leader.get('impressions', 0) / total_imps
        challenger_share = challenger.get('impressions', 0) / total_imps
        
        # If leader has >85% share, Google has decided - skip
        # (Changed from 90% to 85% per v2 spec)
        if leader_share > 0.85:
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
            # Tag all GSC issues as validated
            issue['validation_status'] = 'gsc_validated'
            issue['validation_source'] = 'google_search_console'
            issue['gsc_data'] = {
                'total_impressions': total_imps,
                'pages_in_cluster': len(all_pages_in_cluster),
                'all_competing_pages': [
                    {
                        'url': r.get('page_url', r.get('page', '')),
                        'clicks': r.get('clicks', 0),
                        'impressions': r.get('impressions', 0),
                        'position': round(r.get('position', 0), 1),
                        'share': f"{int(r.get('impressions', 0) / total_imps * 100)}%",
                    }
                    for r in all_pages_in_cluster
                ],
            }
            issues.append(issue)
    
    # Sort: GSC-validated first, then by total impressions descending
    def sort_key(x):
        imps = x.get('gsc_data', {}).get('total_impressions', 0) if x.get('gsc_data') else 0
        return (-imps,)
    issues.sort(key=sort_key)
    
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
# GEO HEALTH CHECKS (Generative Engine Optimization)
# =============================================================================

# Phrases that indicate context-dependent writing (bad for AI extraction)
CONTEXT_DEPENDENT_PHRASES = [
    r'\bas mentioned above\b', r'\bas stated earlier\b', r'\bas we discussed\b',
    r'\bthis is why\b', r'\bthat\'s why\b', r'\bfor this reason\b',
    r'\bas shown above\b', r'\bsee above\b', r'\bbelow we\b',
    r'\bthe following\b', r'\bthe above\b', r'\bthe latter\b', r'\bthe former\b',
]


def check_entity_grounding(page, business_name: str = None, city: str = None) -> Dict[str, Any]:
    """
    GEO Check: Does the page mention business name + city in first 100 words?
    AI engines use this to validate entity authority.
    """
    content = (page.content or '')[:1500]  # Roughly first 100-200 words
    content_lower = content.lower()
    
    has_business_name = False
    has_city = False
    
    if business_name:
        has_business_name = business_name.lower() in content_lower
    
    if city:
        has_city = city.lower() in content_lower
    
    passed = has_business_name and has_city
    
    return {
        'check': 'entity_grounding',
        'passed': passed,
        'has_business_name': has_business_name,
        'has_city': has_city,
        'recommendation': None if passed else "Add business name and city to the first paragraph for AI entity verification."
    }


def check_answer_capsule(page) -> Dict[str, Any]:
    """
    GEO Check: Does the page lead with a direct answer (40-80 words)?
    AI engines extract the opening paragraph for citations.
    """
    content = page.content or ''
    
    # Try to find first paragraph (before first H2 or after ~100 words)
    # Simple heuristic: first 500 chars that aren't headings
    first_para = ''
    lines = content.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Skip headings
        if line.startswith('#') or line.startswith('<h'):
            continue
        # Skip HTML tags
        clean_line = re.sub(r'<[^>]+>', '', line)
        if clean_line:
            first_para = clean_line
            break
    
    word_count = len(first_para.split()) if first_para else 0
    
    # Check for Rule of Five elements (simplified)
    has_specific_data = bool(re.search(r'\$\d+|\d+%|\d+ years?|\d+ reviews?|\d+-star', first_para.lower()))
    
    passed = 40 <= word_count <= 120 and has_specific_data
    
    return {
        'check': 'answer_capsule',
        'passed': passed,
        'first_para_words': word_count,
        'has_specific_data': has_specific_data,
        'recommendation': None if passed else "Add a 40-80 word Answer Capsule with specific data (price, timeframe, credentials) at the start of the page."
    }


def check_schema_presence(page) -> Dict[str, Any]:
    """
    GEO Check: Does the page have LocalBusiness, Service, or FAQPage schema?
    Essential for AI entity verification.
    """
    content = page.content or ''
    
    # Check for JSON-LD schema
    has_local_business = 'LocalBusiness' in content or '"@type":"LocalBusiness"' in content
    has_service = '"Service"' in content or '"@type":"Service"' in content
    has_faq = 'FAQPage' in content or '"@type":"FAQPage"' in content
    has_any_schema = 'application/ld+json' in content
    
    passed = has_any_schema and (has_local_business or has_service or has_faq)
    
    return {
        'check': 'schema_presence',
        'passed': passed,
        'has_schema': has_any_schema,
        'has_local_business': has_local_business,
        'has_service': has_service,
        'has_faq': has_faq,
        'recommendation': None if passed else "Add FAQPage, Service, or LocalBusiness schema markup for AI entity verification."
    }


def check_extractability(page) -> Dict[str, Any]:
    """
    GEO Check: Are paragraphs self-contained or context-dependent?
    AI engines extract paragraphs in isolation - context-dependent phrases break.
    """
    content = (page.content or '').lower()
    
    found_phrases = []
    for pattern in CONTEXT_DEPENDENT_PHRASES:
        matches = re.findall(pattern, content)
        found_phrases.extend(matches)
    
    passed = len(found_phrases) == 0
    
    return {
        'check': 'extractability',
        'passed': passed,
        'context_dependent_count': len(found_phrases),
        'found_phrases': found_phrases[:5],  # Show first 5
        'recommendation': None if passed else f"Remove context-dependent phrases ({', '.join(found_phrases[:3])}...) - AI engines extract paragraphs in isolation."
    }


def check_question_headings(page) -> Dict[str, Any]:
    """
    GEO Check: Are H2/H3 headings phrased as questions?
    Question-format headings map directly to AI queries.
    """
    content = page.content or ''
    
    # Find all H2 and H3 headings
    h2_matches = re.findall(r'<h2[^>]*>([^<]+)</h2>', content, re.IGNORECASE)
    h3_matches = re.findall(r'<h3[^>]*>([^<]+)</h3>', content, re.IGNORECASE)
    
    # Also check markdown-style
    md_h2 = re.findall(r'^## (.+)$', content, re.MULTILINE)
    md_h3 = re.findall(r'^### (.+)$', content, re.MULTILINE)
    
    all_headings = h2_matches + h3_matches + md_h2 + md_h3
    
    question_headings = [h for h in all_headings if '?' in h or h.lower().startswith(('how', 'what', 'why', 'when', 'where', 'who', 'which', 'can', 'does', 'is', 'are'))]
    
    question_ratio = len(question_headings) / len(all_headings) if all_headings else 0
    passed = question_ratio >= 0.3 or len(all_headings) == 0  # At least 30% questions, or no headings
    
    return {
        'check': 'question_headings',
        'passed': passed,
        'total_headings': len(all_headings),
        'question_headings': len(question_headings),
        'question_ratio': round(question_ratio, 2),
        'recommendation': None if passed else "Convert H2/H3 headings to question format (e.g., 'How much does X cost?') for better AI query matching."
    }


def analyze_geo_readiness(page, business_name: str = None, city: str = None) -> Dict[str, Any]:
    """
    Run all GEO health checks on a page.
    Returns a GEO score and individual check results.
    """
    checks = [
        check_entity_grounding(page, business_name, city),
        check_answer_capsule(page),
        check_schema_presence(page),
        check_extractability(page),
        check_question_headings(page),
    ]
    
    passed_count = sum(1 for c in checks if c['passed'])
    total_checks = len(checks)
    geo_score = round((passed_count / total_checks) * 100)
    
    return {
        'geo_score': geo_score,
        'checks_passed': passed_count,
        'checks_total': total_checks,
        'checks': {c['check']: c for c in checks},
        'recommendations': [c['recommendation'] for c in checks if c['recommendation']],
    }


# =============================================================================
# MAIN ANALYSIS FUNCTION
# =============================================================================

def detect_cannibalization(pages, include_noindex: bool = False, impressions_map: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    """
    Main entry point for cannibalization detection (static analysis).
    For GSC-validated analysis, use analyze_gsc_data() separately.
    
    Args:
        impressions_map: Optional dict mapping page URL -> total impressions from GSC.
                         Used to weight severity scoring.
    """
    return detect_static_cannibalization(pages, include_noindex, impressions_map=impressions_map)


def analyze_site(site) -> Dict[str, Any]:
    """Run full analysis on a site including GEO readiness."""
    pages = site.pages.filter(status='publish', is_noindex=False).prefetch_related('seo_data')
    
    health = calculate_health_score(site)
    issues = detect_static_cannibalization(pages)
    
    # Count by severity
    high_count = sum(1 for i in issues if i['severity'] == 'HIGH')
    medium_count = sum(1 for i in issues if i['severity'] == 'MEDIUM')
    
    # Get business info for GEO checks
    business_name = site.name
    city = None
    if site.service_areas:
        # Try to extract city from service areas
        areas = site.service_areas if isinstance(site.service_areas, list) else []
        if areas:
            city = areas[0] if isinstance(areas[0], str) else None
    
    # Run GEO analysis on service/money pages
    geo_results = []
    service_pages = [p for p in pages if classify_page_type(p.url, getattr(p, 'post_type', None)) in ['service', 'product', 'category', 'general']]
    for page in service_pages[:20]:  # Limit to 20 pages
        geo = analyze_geo_readiness(page, business_name, city)
        geo_results.append({
            'page_id': page.id,
            'page_url': page.url,
            'page_title': page.title,
            'geo_score': geo['geo_score'],
            'checks': geo['checks'],
            'recommendations': geo['recommendations'],
        })
    
    # Calculate average GEO score
    avg_geo_score = round(sum(g['geo_score'] for g in geo_results) / len(geo_results)) if geo_results else 0
    geo_issues_count = sum(1 for g in geo_results if g['geo_score'] < 60)
    
    gsc_connected = bool(getattr(site, 'gsc_refresh_token', None))
    
    return {
        'site_id': site.id,
        'analyzed_at': timezone.now().isoformat(),
        'health_score': health['health_score'],
        'health_score_delta': health['health_score_delta'],
        'health_breakdown': health['breakdown'],
        'cannibalization_issues': issues,
        'cannibalization_count': len(issues),
        'gsc_connected': gsc_connected,
        'high_severity_count': high_count,
        'medium_severity_count': medium_count,
        'recommendations': _generate_recommendations(issues),
        'recommendation_count': len(issues),
        'page_count': pages.count(),
        'money_page_count': pages.filter(is_money_page=True).count(),
        # GEO Analysis
        'geo_score': avg_geo_score,
        'geo_pages_analyzed': len(geo_results),
        'geo_issues_count': geo_issues_count,
        'geo_results': geo_results[:10],  # Top 10 for response size
        'geo_recommendations': _generate_geo_recommendations(geo_results),
    }


def _generate_geo_recommendations(geo_results: List[Dict]) -> List[Dict]:
    """Generate top GEO recommendations from page analysis."""
    # Aggregate recommendations by type
    rec_counts = defaultdict(int)
    rec_examples = defaultdict(list)
    
    for result in geo_results:
        for rec in result.get('recommendations', []):
            if rec:
                # Extract check type from recommendation
                rec_counts[rec] += 1
                if len(rec_examples[rec]) < 3:
                    rec_examples[rec].append(result['page_url'])
    
    # Sort by frequency
    sorted_recs = sorted(rec_counts.items(), key=lambda x: -x[1])
    
    return [
        {
            'recommendation': rec,
            'affected_pages': count,
            'example_pages': rec_examples[rec],
        }
        for rec, count in sorted_recs[:5]
    ]


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
