"""
schema_graph_builder.py

Pure functions that assemble the JSON-LD @graph array for a site.
Gated on entity profile completeness — null/empty fields are stripped entirely.

GEO differentiator vs Yoast schemamap:
  Yoast aggregates existing page schema. Siloq builds from the entity profile —
  service cities, confirmed FAQs, business type, and verified review data produce
  a graph that AI crawlers can trust, not just aggregate.
"""

from __future__ import annotations

from typing import Any


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _strip_empty(d: dict) -> dict:
    """Recursively remove keys whose value is None, '', [], or {}."""
    result = {}
    for k, v in d.items():
        if v is None or v == '' or v == [] or v == {}:
            continue
        if isinstance(v, dict):
            cleaned = _strip_empty(v)
            if cleaned:
                result[k] = cleaned
        elif isinstance(v, list):
            cleaned_list = [
                _strip_empty(i) if isinstance(i, dict) else i
                for i in v
                if i is not None and i != '' and i != {} and i != []
            ]
            if cleaned_list:
                result[k] = cleaned_list
        else:
            result[k] = v
    return result


def _hours_to_schema(hours: dict) -> list[str]:
    """
    Convert hours dict  {monday: {open: '08:00', close: '17:00'}, ...}
    to schema.org openingHours strings like ['Mo 08:00-17:00', ...].
    """
    day_map = {
        'monday': 'Mo', 'tuesday': 'Tu', 'wednesday': 'We',
        'thursday': 'Th', 'friday': 'Fr', 'saturday': 'Sa', 'sunday': 'Su',
    }
    result = []
    for day, abbr in day_map.items():
        day_data = hours.get(day) or hours.get(day.capitalize())
        if not day_data:
            continue
        if isinstance(day_data, dict):
            open_t  = day_data.get('open') or day_data.get('opens')
            close_t = day_data.get('close') or day_data.get('closes')
            if open_t and close_t:
                result.append(f'{abbr} {open_t}-{close_t}')
        elif isinstance(day_data, str) and day_data.lower() not in ('closed', 'false', 'no'):
            result.append(f'{abbr} {day_data}')
    return result


# ─── LocalBusiness ────────────────────────────────────────────────────────────

def build_local_business(site, profile) -> dict:
    """
    Build the LocalBusiness (or subtype) node from the entity profile.
    All fields come from entity profile only — no inference.
    """
    # Map Siloq business_type to schema.org type
    BUSINESS_TYPE_MAP = {
        'local_service': 'LocalBusiness',
        'restaurant':    'Restaurant',
        'medical':       'MedicalBusiness',
        'legal':         'LegalService',
        'dental':        'Dentist',
        'hvac':          'HomeAndConstructionBusiness',
        'plumbing':      'Plumber',
        'electrical':    'Electrician',
        'roofing':       'RoofingContractor',
        'landscaping':   'LandscapeService',
        'cleaning':      'HouseCleaning',
        'auto':          'AutoRepair',
        'ecommerce':     'Store',
        'saas':          'SoftwareApplication',
    }

    biz_type = getattr(site, 'business_type', None) or 'LocalBusiness'
    schema_type = BUSINESS_TYPE_MAP.get(biz_type, 'LocalBusiness')

    node: dict[str, Any] = {
        '@type': schema_type,
        '@id':   f'{site.url}/#organization',
        'name':  profile.business_name or None,
        'url':   site.url or None,
    }

    # Address
    if any([profile.street_address, profile.city, profile.state]):
        addr: dict[str, Any] = {'@type': 'PostalAddress'}
        if profile.street_address:
            addr['streetAddress'] = profile.street_address
        if profile.city:
            addr['addressLocality'] = profile.city
        if profile.state:
            addr['addressRegion'] = profile.state
        if profile.zip_code:
            addr['postalCode'] = profile.zip_code
        if profile.country:
            addr['addressCountry'] = profile.country
        node['address'] = addr

    # Contact
    if profile.phone:
        node['telephone'] = profile.phone
    if profile.email:
        node['email'] = profile.email

    # Logo
    if profile.logo_url:
        node['logo'] = {
            '@type':      'ImageObject',
            '@id':        f'{site.url}/#logo',
            'url':        profile.logo_url,
            'contentUrl': profile.logo_url,
        }
        node['image'] = node['logo']

    # Hours
    if profile.hours:
        opening_hours = _hours_to_schema(profile.hours)
        if opening_hours:
            node['openingHours'] = opening_hours

    # Founding year
    if profile.founding_year:
        node['foundingDate'] = str(profile.founding_year)

    # Price range
    if profile.price_range:
        node['priceRange'] = profile.price_range

    # areaServed — entity profile service_cities only, never inferred
    if profile.service_cities and isinstance(profile.service_cities, list):
        node['areaServed'] = [
            {'@type': 'City', 'name': city}
            for city in profile.service_cities
            if city
        ]

    # Service Area Business: hide address, add areaServed radius
    if getattr(profile, 'is_service_area_business', False):
        node['@type'] = 'LocalBusiness'  # SAB is always LocalBusiness base
        if profile.service_radius_miles and profile.city:
            node['serviceArea'] = {
                '@type':        'GeoCircle',
                'geoMidpoint':  {
                    '@type':    'GeoCoordinates',
                    'latitude':  profile.latitude,
                    'longitude': profile.longitude,
                },
                'geoRadius': str(profile.service_radius_miles * 1609),  # miles → meters
            } if profile.latitude and profile.longitude else None

    # Social profiles → sameAs
    same_as = []
    for attr in ('url_facebook', 'url_instagram', 'url_linkedin', 'url_twitter',
                 'url_youtube', 'url_tiktok', 'gbp_url', 'url_yelp'):
        val = getattr(profile, attr, None)
        if val:
            same_as.append(val)
    if same_as:
        node['sameAs'] = same_as

    # Description
    if profile.description:
        node['description'] = profile.description

    # Languages
    if profile.languages:
        node['knowsLanguage'] = profile.languages

    # Payment methods
    if profile.payment_methods:
        node['paymentAccepted'] = ', '.join(profile.payment_methods) \
            if isinstance(profile.payment_methods, list) else profile.payment_methods

    # Geo coordinates
    if profile.latitude and profile.longitude:
        node['geo'] = {
            '@type':    'GeoCoordinates',
            'latitude':  profile.latitude,
            'longitude': profile.longitude,
        }

    return _strip_empty(node)


# ─── WebSite ──────────────────────────────────────────────────────────────────

def build_website(site) -> dict:
    node = {
        '@type':  'WebSite',
        '@id':    f'{site.url}/#website',
        'url':    site.url,
        'name':   site.name,
        'publisher': {'@id': f'{site.url}/#organization'},
        'potentialAction': {
            '@type':       'SearchAction',
            'target':      {
                '@type': 'EntryPoint',
                'urlTemplate': f'{site.url}/?s={{search_term_string}}',
            },
            'query-input': 'required name=search_term_string',
        },
    }
    return _strip_empty(node)


# ─── FAQPage ──────────────────────────────────────────────────────────────────

def build_faq_nodes(pages) -> list[dict]:
    """
    Only include FAQPage schema for pages that have confirmed FAQ data
    stored in their PageAnalysis.generated_schema.
    No speculative schema.
    """
    from seo.models import PageAnalysis

    nodes = []
    page_ids = [p.id for p in pages if p.status == 'publish']
    if not page_ids:
        return nodes

    analyses = PageAnalysis.objects.filter(
        page_id__in=[str(pid) for pid in page_ids],
    ).values('page_id', 'page_url', 'page_title', 'generated_schema')

    for analysis in analyses:
        schema = analysis.get('generated_schema') or {}
        if not schema:
            continue

        # Look for FAQPage in generated_schema
        faqs = None
        if isinstance(schema, dict):
            if schema.get('@type') == 'FAQPage':
                faqs = schema.get('mainEntity', [])
            elif isinstance(schema.get('@graph'), list):
                for item in schema['@graph']:
                    if isinstance(item, dict) and item.get('@type') == 'FAQPage':
                        faqs = item.get('mainEntity', [])
                        break

        if not faqs or not isinstance(faqs, list):
            continue

        # Validate FAQ items have actual Q&A content
        valid_faqs = [
            item for item in faqs
            if isinstance(item, dict)
            and item.get('name')           # question
            and item.get('acceptedAnswer', {}).get('text')  # answer
        ]
        if not valid_faqs:
            continue

        node = {
            '@type':      'FAQPage',
            '@id':        f"{analysis['page_url']}#faq",
            'url':        analysis['page_url'],
            'name':       analysis['page_title'],
            'mainEntity': valid_faqs,
        }
        nodes.append(_strip_empty(node))

    return nodes


# ─── Service ─────────────────────────────────────────────────────────────────

def build_service_nodes(site, pages, profile) -> list[dict]:
    """
    Build Service schema nodes for pages classified as money pages (service pages).
    """
    nodes = []
    service_pages = [
        p for p in pages
        if p.status == 'publish'
        and p.page_type_classification == 'money'
        and not p.is_noindex
        and p.title
    ]

    for page in service_pages:
        node: dict[str, Any] = {
            '@type':    'Service',
            '@id':      f'{page.url}#service',
            'name':     page.title,
            'url':      page.url,
            'provider': {'@id': f'{site.url}/#organization'},
        }
        if profile.service_cities:
            node['areaServed'] = [
                {'@type': 'City', 'name': city}
                for city in profile.service_cities
                if city
            ]
        nodes.append(_strip_empty(node))

    return nodes


# ─── AggregateRating ──────────────────────────────────────────────────────────

def build_aggregate_rating(site, profile) -> dict | None:
    """
    Only include AggregateRating if GBP review data is confirmed present.
    Both gbp_star_rating AND gbp_review_count must be non-null/non-zero.
    """
    rating  = profile.gbp_star_rating
    count   = profile.gbp_review_count

    if not rating or not count or count < 1:
        return None

    # Sanity-check bounds
    if not (1.0 <= float(rating) <= 5.0):
        return None

    return _strip_empty({
        '@type':       'AggregateRating',
        'ratingValue': str(round(float(rating), 1)),
        'reviewCount': str(count),
        'bestRating':  '5',
        'worstRating': '1',
    })


# ─── Entity completeness score ────────────────────────────────────────────────

REQUIRED_FIELDS = [
    ('business_name',  'Business name'),
    ('street_address', 'Street address'),
    ('city',           'City'),
    ('state',          'State'),
    ('phone',          'Phone number'),
    ('hours',          'Business hours'),
    ('logo_url',       'Logo URL'),
    ('service_cities', 'Service cities'),
    ('founding_year',  'Founding year'),
]

# business_type lives on Site, not profile
REQUIRED_SITE_FIELDS = [
    ('business_type', 'Business type'),
]


def compute_completeness(site, profile) -> dict:
    """
    Returns {score: int (0-100), missing: [str], present: [str]}.
    """
    present = []
    missing = []

    for attr, label in REQUIRED_FIELDS:
        val = getattr(profile, attr, None)
        if val:
            present.append(label)
        else:
            missing.append(label)

    for attr, label in REQUIRED_SITE_FIELDS:
        val = getattr(site, attr, None)
        if val:
            present.append(label)
        else:
            missing.append(label)

    total = len(REQUIRED_FIELDS) + len(REQUIRED_SITE_FIELDS)
    score = round(len(present) / total * 100) if total else 0

    return {'score': score, 'present': present, 'missing': missing}


# ─── Main graph assembler ─────────────────────────────────────────────────────

def build_schema_graph(site, profile, pages) -> dict:
    """
    Assemble the full JSON-LD schema graph document.
    Returns a dict ready for json.dumps with indent.
    """
    graph = []

    # 1. LocalBusiness
    local_biz = build_local_business(site, profile)

    # Attach AggregateRating directly to LocalBusiness node
    rating_node = build_aggregate_rating(site, profile)
    if rating_node:
        local_biz['aggregateRating'] = rating_node

    graph.append(local_biz)

    # 2. WebSite
    graph.append(build_website(site))

    # 3. Service nodes (money pages)
    graph.extend(build_service_nodes(site, pages, profile))

    # 4. FAQPage nodes (confirmed only)
    graph.extend(build_faq_nodes(pages))

    return {
        '@context': 'https://schema.org',
        '@graph':   graph,
    }
