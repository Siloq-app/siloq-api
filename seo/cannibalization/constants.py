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
    'shop': ['shop'],
    'product_rentals': ['product-rentals'],
    'service': ['service', 'services', 'residential', 'commercial', 'solutions'],
    'location': ['location', 'locations', 'service-area', 'service-areas', 'city', 'cities'],
    'portfolio': ['portfolio', 'work', 'projects', 'gallery'],
    'utility': ['cart', 'checkout', 'account', 'my-account', 'wp-admin', 'wp-content', 'wp-includes'],
}

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
    # HOMEPAGE_CANNIBALIZATION: Homepage competes with dedicated service/product pages.
    # ABSOLUTE RULE — homepage NEVER wins a service/product keyword conflict.
    # Emitted during Phase 4 GSC analysis when homepage impressions compete
    # with service/product pages for the same queries.
    # Two sub-patterns (captured via metadata):
    #   - hoarding: homepage outranks the service page (homepage IS the primary)
    #   - over-targeting: homepage splits impressions with service page
    'HOMEPAGE_CANNIBALIZATION': {
        'bucket': 'SEARCH_CONFLICT',
        'badge': 'CONFIRMED',
        'description': (
            'Homepage is cannibalizing dedicated service/product pages. '
            'Homepage ranks for (or splits impressions with) service/product keywords '
            'that a dedicated page should own exclusively.'
        ),
        'action_code': 'DE_OPTIMIZE_HOMEPAGE',
    },

    # BLOG_OVERLAP bucket (phase_blog_service detection)
    'BLOG_SERVICE_OVERLAP': {
        'bucket': 'BLOG_OVERLAP',
        'badge': 'POTENTIAL',
        'description': 'Blog post targeting the same keyword as a service page',
        'action_code': 'REWRITE_AS_SPOKE',
        'risk_badge': 'Content Change',
        'risk_badge_color': 'blue',
    },
    'BLOG_CONSOLIDATION': {
        'bucket': 'BLOG_OVERLAP',
        'badge': 'POTENTIAL',
        'description': '3+ blog posts targeting similar keywords — consolidate into a pillar post',
        'action_code': 'REWRITE_AS_SPOKE',
        'risk_badge': 'Content Change',
        'risk_badge_color': 'blue',
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
    'BLOG_OVERLAP': 12,  # Lower than WRONG_WINNER — supportive conflicts, not destructive
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
    # DE_OPTIMIZE_HOMEPAGE is the canonical action code for HOMEPAGE_CANNIBALIZATION conflicts.
    # It covers both "homepage hoarding" (homepage outranks service page) and
    # "homepage over-targeting" (homepage splits impressions with service page).
    'DE_OPTIMIZE_HOMEPAGE': {
        'label': 'De-optimize Homepage for Service Keywords',
        'description': (
            'Homepage is ranking for service/product keywords that a dedicated page should own. '
            'Action required:\n'
            '1. Strip the conflicting keyword(s) from the homepage title tag, H1, meta description, '
            'and body copy.\n'
            '2. Homepage should target ONLY [Brand Name] + broad category (e.g., "Acme Plumbing — '
            'Professional Plumbing Services").\n'
            '3. Strengthen the correct service/product page: improve its title, meta, H1, and body '
            'to clearly own the keyword.\n'
            '4. Add a prominent internal link from the homepage to each de-optimized service page.\n'
            'ABSOLUTE RULE: Homepage NEVER wins a service/product keyword conflict.'
        ),
        'requires_user_input': False,
    },
    'SLUG_PIVOT': {
        'label': 'Slug Pivot + Differentiate',
        'description': 'Competing pages have high slug similarity (Jaccard > 0.6). Differentiate content AND recommend URL slug change to reinforce the new keyword angle. Old slug gets 301 to new slug.',
        'requires_user_input': True,
    },
    'REWRITE_AS_SPOKE': {
        'label': 'Rewrite as Supporting Spoke',
        'description': (
            'Blog post targets the same keyword as a service page. '
            'Rewrite the blog post as a supporting spoke that links prominently to the service hub. '
            'Shift the blog\'s angle to informational ("How to…", "What is…") and add a clear CTA '
            'linking to the service page. Do NOT redirect the blog post.'
        ),
        'requires_user_input': False,
        'risk_badge': 'Content Change',
        'risk_badge_color': 'blue',
        'is_destructive': False,
    },
    'ADD_INTERNAL_LINKS': {
        'label': 'Add Internal Links to Service Page',
        'description': (
            'Blog post covers a topic closely related to a service page. '
            'Keep the existing blog content but add a prominent internal link to the service page '
            '(inline contextual link + sidebar/CTA block). '
            'This passes authority to the service page without altering the blog.'
        ),
        'requires_user_input': False,
        'risk_badge': 'Content Change',
        'risk_badge_color': 'blue',
        'is_destructive': False,
    },
    'MERGE_INTO_SERVICE': {
        'label': 'Merge Thin Blog into Service Page',
        'description': (
            'Blog post is thin (<300 words) and targets a keyword owned by a service page. '
            'Migrate any unique content into the service page, then 301-redirect the blog URL '
            'to the service page. Net result: one stronger page instead of two weak ones.'
        ),
        'requires_user_input': True,
        'risk_badge': 'Content Change',
        'risk_badge_color': 'blue',
        'is_destructive': False,
    },
}

# =============================================================================
# INTENT CLASSIFICATION
# =============================================================================

# Page types that signal informational intent (for blog/service overlap detection)
INFORMATIONAL_PAGE_TYPES = {
    'blog',
    'portfolio',  # Portfolio posts are informational (not transactional landing pages)
}

# Page types that signal transactional intent
TRANSACTIONAL_PAGE_TYPES = {
    'service_hub',
    'service_spoke',
    'product',
    'category_woo',
    'category_shop',
    'category_custom',
    'shop_root',
}

# WordPress post_type signals
# post_type='post' → informational (standard WP blog post)
# post_type='page' → could be either; fall back to classified_type
WP_INFORMATIONAL_POST_TYPES = {'post'}

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

# =============================================================================
# BLOG SERVICE OVERLAP THRESHOLDS
# =============================================================================

# Blog posts below this word count are candidates for MERGE_INTO_SERVICE
THIN_BLOG_WORD_COUNT = 300

# Minimum slug token overlap to consider blog/service conflict
BLOG_SERVICE_MIN_TOKEN_OVERLAP = 1

# Minimum number of blog posts targeting similar keywords to flag BLOG_CONSOLIDATION
BLOG_CONSOLIDATION_MIN_COUNT = 3

# Minimum slug token Jaccard similarity to group blogs for consolidation
BLOG_CONSOLIDATION_JACCARD_THRESHOLD = 0.4
