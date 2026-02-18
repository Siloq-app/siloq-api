"""
Constants for cannibalization detection.
All keyword lists, folder root patterns, legacy suffixes, and severity scoring.
"""

# =============================================================================
# PAGE TYPE CLASSIFICATION
# =============================================================================

# Folder roots for taxonomy classification (order matters - first match wins)
FOLDER_ROOTS = {
    'blog': ['blog', 'news', 'articles', 'post', 'posts'],
    'product': ['product', 'products', 'item', 'p'],
    'category_woo': ['product-category'],
    'product_tag': ['product-tag'],
    'shop': ['shop'],
    'product_rentals': ['product-rentals'],
    'service': ['service', 'services', 'residential', 'commercial', 'solutions'],
    'location': ['location', 'locations', 'service-area', 'service-areas', 'city', 'cities'],
    'portfolio': ['portfolio', 'work', 'projects', 'gallery'],
    'utility': ['cart', 'checkout', 'account', 'my-account', 'wp-admin', 'wp-content', 'wp-includes'],
}

# E-commerce specific patterns
ECOMMERCE_PAGINATION_PATTERN = r'/page/\d+/?$'
ECOMMERCE_PRODUCT_VARIANT_INDICATORS = ['color', 'size', 'variant', 'option']

# Legacy suffix patterns
LEGACY_SUFFIXES = [
    '-old', '-backup', '-copy', '-duplicate', '-temp', '-test',
    '-v2', '-v3', '-new', '-draft', '-archive', '-prev', '-previous',
    '-2', '-3', '-4', '-5'  # Numbered variants like /obstacle-course-2/
]

# Stop words for slug comparison
SLUG_STOP_WORDS = {
    'page', 'pages', 'post', 'posts', 'product', 'products',
    'category', 'categories', 'tag', 'tags', 'shop', 'store',
    'blog', 'news', 'article', 'articles', 'index', 'home',
    'www', 'http', 'https', 'html', 'php', 'aspx', 'htm',
    'the', 'and', 'for', 'with', 'our', 'your', 'about',
    'a', 'an', 'in', 'on', 'at', 'to', 'of', 'by',
}

# =============================================================================
# CONFLICT TYPE DEFINITIONS
# =============================================================================

CONFLICT_TYPES = {
    # SITE_DUPLICATION bucket (Phase 3 - static detection)
    'TAXONOMY_CLASH': {
        'bucket': 'SITE_DUPLICATION',
        'badge': 'POTENTIAL',
        'description': 'Same slug exists in different folder structures',
        'action_code': 'REDIRECT_TO_CANONICAL',
    },
    'LEGACY_CLEANUP': {
        'bucket': 'SITE_DUPLICATION',
        'badge': 'POTENTIAL',
        'description': 'Legacy variant page detected with clean version available',
        'action_code': 'REDIRECT_TO_CANONICAL',
    },
    'LEGACY_ORPHAN': {
        'bucket': 'SITE_DUPLICATION',
        'badge': 'POTENTIAL',
        'description': 'Legacy variant page with no clean version',
        'action_code': 'REVIEW_AND_REDIRECT',
    },
    'NEAR_DUPLICATE_CONTENT': {
        'bucket': 'SITE_DUPLICATION',
        'badge': 'POTENTIAL',
        'description': 'URLs with >80% slug token similarity',
        'action_code': 'REDIRECT_TO_CANONICAL',
    },
    'CONTEXT_DUPLICATE': {
        'bucket': 'SITE_DUPLICATION',
        'badge': 'POTENTIAL',
        'description': 'Same service slug under different parent paths',
        'action_code': 'REDIRECT_OR_DIFFERENTIATE',
    },
    'LOCATION_BOILERPLATE': {
        'bucket': 'SITE_DUPLICATION',
        'badge': 'POTENTIAL',
        'description': '3+ location pages with identical title template',
        'action_code': 'REWRITE_LOCAL_EVIDENCE',
    },
    
    # SEARCH_CONFLICT bucket (Phase 4 - GSC validated)
    'GSC_CONFIRMED': {
        'bucket': 'SEARCH_CONFLICT',
        'badge': 'CONFIRMED',
        'description': 'Multiple pages ranking for same query (GSC data)',
        'action_code': 'REDIRECT_TO_CANONICAL',
    },
    'GSC_BLOG_VS_CATEGORY': {
        'bucket': 'SEARCH_CONFLICT',
        'badge': 'CONFIRMED',
        'description': 'Blog competing with category for commercial query',
        'action_code': 'STRENGTHEN_CORRECT_PAGE',
    },
    'GSC_HOMEPAGE_HOARDING': {
        'bucket': 'SEARCH_CONFLICT',
        'badge': 'CONFIRMED',
        'description': 'Homepage ranking instead of dedicated page',
        'action_code': 'HOMEPAGE_DEOPTIMIZE',
    },
    'GSC_HOMEPAGE_SPLIT': {
        'bucket': 'SEARCH_CONFLICT',
        'badge': 'CONFIRMED',
        'description': 'Homepage splitting impressions with service/product page',
        'action_code': 'HOMEPAGE_DEOPTIMIZE',
    },
    'HOMEPAGE_STEALING_SERVICE_KW': {
        'bucket': 'SEARCH_CONFLICT',
        'badge': 'CONFIRMED',
        'description': 'Homepage ranking for service/product keyword instead of dedicated page',
        'action_code': 'HOMEPAGE_DEOPTIMIZE',
    },
    
    # WRONG_WINNER bucket (Phase 5)
    'INTENT_MISMATCH': {
        'bucket': 'WRONG_WINNER',
        'badge': 'WRONG_WINNER',
        'description': 'Page type does not match query intent',
        'action_code': 'STRENGTHEN_CORRECT_PAGE',
    },
    'GEOGRAPHIC_MISMATCH': {
        'bucket': 'WRONG_WINNER',
        'badge': 'WRONG_WINNER',
        'description': 'Wrong location page ranking for query',
        'action_code': 'REWRITE_LOCAL_EVIDENCE',
    },
    'PAGE_TYPE_MISMATCH': {
        'bucket': 'WRONG_WINNER',
        'badge': 'WRONG_WINNER',
        'description': 'Product ranking for plural (category) query',
        'action_code': 'STRENGTHEN_CORRECT_PAGE',
    },
    'HOMEPAGE_HOARDING': {
        'bucket': 'WRONG_WINNER',
        'badge': 'WRONG_WINNER',
        'description': 'Homepage ranking for specific service query',
        'action_code': 'HOMEPAGE_DEOPTIMIZE',
    },
    'HOMEPAGE_TOO_MANY_KEYWORDS': {
        'bucket': 'WRONG_WINNER',
        'badge': 'WRONG_WINNER',
        'description': 'Homepage targeting too many non-brand keywords (>5)',
        'action_code': 'HOMEPAGE_DEOPTIMIZE_MULTI',
    },
    
    # BLOG vs SERVICE conflicts
    'BLOG_SERVICE_OVERLAP': {
        'bucket': 'WRONG_WINNER',
        'badge': 'WRONG_WINNER',
        'description': 'Blog post competing with service page for transactional keyword',
        'action_code': 'REWRITE_AS_SPOKE',
    },
    'BLOG_CONSOLIDATION': {
        'bucket': 'SITE_DUPLICATION',
        'badge': 'POTENTIAL',
        'description': 'Multiple blog posts targeting similar keywords',
        'action_code': 'CONSOLIDATE_BLOGS',
    },
    
    # E-COMMERCE bucket (safe pairs - informational only)
    'ECOMMERCE_PRODUCT_VARIANT': {
        'bucket': 'SITE_DUPLICATION',
        'badge': 'INFO',
        'description': 'Product variants (color/size) of same product',
        'action_code': 'CANONICAL_TAG_RECOMMENDATION',
    },
    'ECOMMERCE_TAG_ARCHIVE': {
        'bucket': 'SITE_DUPLICATION',
        'badge': 'LOW',
        'description': 'Product tag archive page (structural)',
        'action_code': 'REVIEW_NOINDEX',
    },
}

# =============================================================================
# SEVERITY SCORING
# =============================================================================

# Bucket priority (for sorting)
BUCKET_SCORES = {
    'SEARCH_CONFLICT': 50,
    'SITE_DUPLICATION': 25,
    'WRONG_WINNER': 15,
}

# Severity priority
SEVERITY_SCORES = {
    'SEVERE': 30,
    'HIGH': 20,
    'MEDIUM': 10,
    'LOW': 5,
}

# Impression scoring (for Phase 6)
# Max 20 points for high impression count
IMPRESSION_THRESHOLD_HIGH = 1000
IMPRESSION_THRESHOLD_MEDIUM = 100

# =============================================================================
# ACTION CODES
# =============================================================================

ACTION_CODES = {
    'REDIRECT_TO_CANONICAL': {
        'label': 'Redirect to Canonical',
        'description': 'Clear winner exists. Redirect duplicates via 301.',
        'requires_user_input': False,
    },
    'REVIEW_AND_REDIRECT': {
        'label': 'Review and Redirect',
        'description': 'No clear canonical. User must choose winner.',
        'requires_user_input': True,
    },
    'REWRITE_LOCAL_EVIDENCE': {
        'label': 'Rewrite with Local Evidence',
        'description': 'Location pages need unique local content.',
        'requires_user_input': False,
    },
    'STRENGTHEN_CORRECT_PAGE': {
        'label': 'Strengthen Correct Page',
        'description': 'Wrong page winning. Boost correct page authority.',
        'requires_user_input': False,
    },
    'REDIRECT_OR_DIFFERENTIATE': {
        'label': 'Redirect or Differentiate',
        'description': 'Either merge pages or add unique differentiating content.',
        'requires_user_input': True,
    },
    'HOMEPAGE_DEOPTIMIZE': {
        'label': 'De-optimize Homepage',
        'description': 'Homepage is cannibalizing a service/product page. De-optimize homepage for the service keyword (strip from title, H1, meta, body). Homepage should only target [Brand] + [broad category]. Then strengthen the correct service page.',
        'requires_user_input': False,
    },
    'HOMEPAGE_DEOPTIMIZE_MULTI': {
        'label': 'De-optimize Homepage (Multiple Keywords)',
        'description': 'Homepage is hoarding too many service/product keywords (>5 non-brand terms). Strip all specific keywords from homepage. Create dedicated pages for each service/product. Homepage should only target brand and broad category terms.',
        'requires_user_input': False,
    },
    'SLUG_PIVOT': {
        'label': 'Slug Pivot + Differentiate',
        'description': 'Competing pages have high slug similarity (Jaccard > 0.6). Differentiate content AND recommend URL slug change to reinforce the new keyword angle. Old slug gets 301 to new slug.',
        'requires_user_input': True,
    },
    'CANONICAL_TAG_RECOMMENDATION': {
        'label': 'Add Canonical Tag',
        'description': 'Product variants should use canonical tag pointing to main product. This preserves all variant URLs while consolidating SEO authority.',
        'requires_user_input': False,
    },
    'REVIEW_NOINDEX': {
        'label': 'Review for Noindex',
        'description': 'Tag archives and pagination pages should typically be noindexed to prevent thin content issues.',
        'requires_user_input': True,
    },
    'REWRITE_AS_SPOKE': {
        'label': 'Rewrite Blog as Spoke Article',
        'description': 'Blog post should support the service page, not compete. Rewrite with informational angle and add prominent internal links to the service page.',
        'requires_user_input': False,
    },
    'ADD_INTERNAL_LINKS': {
        'label': 'Add Internal Links to Service Page',
        'description': 'Blog keeps its content but adds prominent links to the service page early in the article. Differentiate the blog angle (informational vs transactional).',
        'requires_user_input': False,
    },
    'MERGE': {
        'label': 'Merge into Service Page',
        'description': 'Blog post is thin (<300 words). Merge its content into the service page and redirect.',
        'requires_user_input': False,
    },
    'CONSOLIDATE_BLOGS': {
        'label': 'Consolidate Blog Posts',
        'description': 'Multiple blog posts targeting similar keywords. Consolidate into one comprehensive article and redirect others.',
        'requires_user_input': True,
    },
}

# =============================================================================
# INTENT CLASSIFICATION
# =============================================================================

INTENT_MARKERS = {
    'transactional': [
        'buy', 'purchase', 'order', 'book', 'hire', 'get', 'request',
        'near me', 'in', 'service', 'company', 'companies', 'business',
        'price', 'cost', 'quote', 'estimate', 'pricing',
    ],
    'informational': [
        'how', 'what', 'why', 'when', 'where', 'who', 'which',
        'guide', 'tips', 'ideas', 'tutorial', 'learn', 'understand',
        'meaning', 'definition', 'explain', 'difference',
    ],
    'listicle': [
        'best', 'top', 'review', 'reviews', 'vs', 'versus',
        'compare', 'comparison', 'ranking', 'rated',
    ],
    'navigational': [
        'login', 'contact', 'about', 'hours', 'location',
        'address', 'phone', 'directions', 'map',
    ],
}

# Geographic modifiers
GEO_MODIFIERS = [
    'near me', 'nearby', 'local', 'in', 'at',
    'city', 'cities', 'town', 'area', 'county',
    'brooklyn', 'manhattan', 'queens', 'bronx', 'staten island',  # Common examples
]

# =============================================================================
# GSC VALIDATION
# =============================================================================

# Minimum impressions to consider a query
MIN_IMPRESSIONS_THRESHOLD = 20

# Primary share threshold (above this = NOT cannibalization)
PRIMARY_SHARE_THRESHOLD = 0.85

# Secondary share threshold (above this = CONFIRMED cannibalization)
SECONDARY_SHARE_THRESHOLD = 0.15

# Noise filter (pages below this with 0 clicks are filtered)
NOISE_FILTER_SHARE = 0.05

# Severity thresholds based on impression distribution
SEVERITY_THRESHOLDS = {
    'SEVERE': {
        'description': '3+ pages each with 10%+ share',
        'condition': lambda pages: sum(1 for p in pages if p['share'] >= 0.10) >= 3,
    },
    'HIGH': {
        'description': 'Secondary page has 35%+ share',
        'condition': lambda pages: len(pages) >= 2 and pages[1]['share'] >= 0.35,
    },
    'MEDIUM': {
        'description': 'Secondary page has 15-35% share',
        'condition': lambda pages: len(pages) >= 2 and 0.15 <= pages[1]['share'] < 0.35,
    },
    'LOW': {
        'description': 'Minor impression split',
        'condition': lambda pages: True,  # Default
    },
}

# Branded query detection (these are excluded from cannibalization)
BRANDED_QUERY_INDICATORS = [
    'llc', 'inc', 'corp', 'ltd', 'company', 'co.',
]

# =============================================================================
# CLUSTERING
# =============================================================================

# Max pages per cluster (hard cap to prevent massive groups)
MAX_CLUSTER_SIZE = 15

# =============================================================================
# PAGE CLASSIFICATION KEYWORDS
# =============================================================================

# Service-related keywords for CONTEXT_DUPLICATE detection
SERVICE_KEYWORDS = [
    'service', 'services', 'repair', 'install', 'installation',
    'maintenance', 'cleaning', 'restoration', 'consultation',
    'design', 'build', 'remodel', 'renovation',
]
