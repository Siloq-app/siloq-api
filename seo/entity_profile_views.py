"""
Site Entity Profile API — business data for schema generation.

GET  /api/v1/sites/{site_id}/entity-profile/      — get or create profile
PATCH /api/v1/sites/{site_id}/entity-profile/     — update profile fields
POST /api/v1/sites/{site_id}/entity-profile/sync-gbp/  — sync from Google Places
"""
import json
import logging
import os
import re
import urllib.parse
from urllib.parse import parse_qs, urlparse

import requests
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from sites.models import Site
from seo.models import SiteEntityProfile

logger = logging.getLogger(__name__)
GOOGLE_PLACES_API_KEY = os.environ.get('GOOGLE_PLACES_API_KEY', '')


def _get_or_create_profile(site):
    profile, _ = SiteEntityProfile.objects.get_or_create(site=site)
    return profile


def _serialize_profile(profile):
    """Build full JSON-serializable dict for entity profile. Safe for None datetimes."""
    def _dt_iso(dt):
        return dt.isoformat() if dt is not None else None
    return {
        'id': profile.id,
        'business_name': profile.business_name or '',
        'description': profile.description or '',
        'phone': profile.phone or '',
        'email': profile.email or '',
        'founding_year': profile.founding_year,
        'founder_name': profile.founder_name or '',
        'num_employees': profile.num_employees or '',
        'price_range': profile.price_range or '',
        'languages': profile.languages if profile.languages is not None else [],
        'payment_methods': profile.payment_methods if profile.payment_methods is not None else [],
        'street_address': profile.street_address or '',
        'city': profile.city or '',
        'state': profile.state or '',
        'zip_code': profile.zip_code or '',
        'country': profile.country or '',
        'latitude': profile.latitude,
        'longitude': profile.longitude,
        'service_cities': profile.service_cities if profile.service_cities is not None else [],
        'service_zips': profile.service_zips if profile.service_zips is not None else [],
        'service_radius_miles': profile.service_radius_miles,
        'hours': profile.hours if profile.hours is not None else {},
        'categories': profile.categories if profile.categories is not None else [],
        'certifications': profile.certifications if profile.certifications is not None else [],
        'license_numbers': profile.license_numbers if profile.license_numbers is not None else [],
        'social_profiles': {
            'facebook': profile.url_facebook or '',
            'instagram': profile.url_instagram or '',
            'linkedin': profile.url_linkedin or '',
            'twitter': profile.url_twitter or '',
            'youtube': profile.url_youtube or '',
            'tiktok': profile.url_tiktok or '',
        },
        'gbp_url': profile.gbp_url or '',
        'google_place_id': profile.google_place_id or '',
        'gbp_star_rating': profile.gbp_star_rating,
        'gbp_review_count': profile.gbp_review_count,
        'gbp_reviews': profile.gbp_reviews if profile.gbp_reviews is not None else [],
        'gbp_last_synced': _dt_iso(getattr(profile, 'gbp_last_synced', None)),
        'updated_at': _dt_iso(getattr(profile, 'updated_at', None)) or '',
        # V1 fields
        'logo_url': getattr(profile, 'logo_url', '') or '',
        'brands_used': getattr(profile, 'brands_used', None) if getattr(profile, 'brands_used', None) is not None else [],
        'url_yelp': getattr(profile, 'url_yelp', '') or '',
        'team_members': getattr(profile, 'team_members', None) if getattr(profile, 'team_members', None) is not None else [],
        'is_service_area_business': getattr(profile, 'is_service_area_business', False),
        'brand_voice': profile.brand_voice if profile.brand_voice else {},
    }


UPDATABLE_FIELDS = [
    'business_name', 'description', 'phone', 'email', 'founding_year', 'founder_name',
    'num_employees', 'price_range', 'languages', 'payment_methods',
    'street_address', 'city', 'state', 'zip_code', 'country',
    'service_cities', 'service_zips', 'service_radius_miles', 'hours',
    'categories', 'certifications', 'license_numbers',
    'gbp_url', 'google_place_id',
    'gbp_star_rating', 'gbp_review_count', 'gbp_reviews',
    # V1 additions
    'logo_url', 'brands_used', 'url_yelp', 'team_members', 'is_service_area_business',
]
SOCIAL_FIELD_MAP = {
    'facebook': 'url_facebook', 'instagram': 'url_instagram', 'linkedin': 'url_linkedin',
    'twitter': 'url_twitter', 'youtube': 'url_youtube', 'tiktok': 'url_tiktok',
    'yelp': 'url_yelp',
}


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def entity_profile(request, site_id):
    site = get_object_or_404(Site, id=site_id, user=request.user)
    profile = _get_or_create_profile(site)

    if request.method == 'GET':
        from seo.profile_validators import get_profile_completeness
        serialized = _serialize_profile(profile)
        serialized['completeness'] = get_profile_completeness(profile)
        return Response(serialized)

    # PATCH
    data = request.data
    for field in UPDATABLE_FIELDS:
        if field in data:
            setattr(profile, field, data[field])

    social = data.get('social_profiles', {})
    for key, model_field in SOCIAL_FIELD_MAP.items():
        if key in social:
            setattr(profile, model_field, social[key])

    # brand_voice — validated separately
    if 'brand_voice' in data:
        brand_voice = data['brand_voice']
        if not isinstance(brand_voice, dict):
            return Response({'error': 'brand_voice must be a JSON object'}, status=status.HTTP_400_BAD_REQUEST)
        VALID_TONES = {'confident_expert', 'warm_advisor', 'no_bs_truth_teller', 'sage_strategist', 'tech_translator', 'rebellious_challenger'}
        errors = []
        if 'primary_tone' in brand_voice and brand_voice['primary_tone'] not in VALID_TONES:
            errors.append(f"primary_tone must be one of: {', '.join(sorted(VALID_TONES))}")
        if 'secondary_tone' in brand_voice and brand_voice['secondary_tone'] != '' and brand_voice['secondary_tone'] not in VALID_TONES:
            errors.append(f"secondary_tone must be one of: {', '.join(sorted(VALID_TONES))} or empty string")
        for str_field in ('industry', 'admired_brands', 'tagline'):
            if str_field in brand_voice and isinstance(brand_voice[str_field], str) and len(brand_voice[str_field]) > 500:
                errors.append(f"{str_field} must be 500 characters or fewer")
        if 'using_smart_default' in brand_voice and not isinstance(brand_voice['using_smart_default'], bool):
            errors.append("using_smart_default must be a boolean")
        if errors:
            return Response({'error': 'brand_voice validation failed', 'details': errors}, status=status.HTTP_400_BAD_REQUEST)
        profile.brand_voice = brand_voice

    profile.save()
    profile.refresh_from_db()
    serialized = _serialize_profile(profile)
    body_bytes = len(json.dumps(serialized))
    logger.info(
        '[PATCH entity-profile] site=%s response_bytes=%d business_name=%r',
        site_id, body_bytes, serialized.get('business_name')
    )
    return Response(serialized, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def sync_gbp(request, site_id):
    """Sync business data from Google Places API using place_id or GBP URL."""
    site = get_object_or_404(Site, id=site_id, user=request.user)
    profile = _get_or_create_profile(site)

    if not GOOGLE_PLACES_API_KEY:
        return Response({'error': 'GOOGLE_PLACES_API_KEY not configured'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    raw_input = (request.data.get('place_id') or request.data.get('gbp_url') or '').strip()
    gbp_url = raw_input if raw_input.startswith('http') else (profile.gbp_url or '')
    place_id = None
    text_search_query = None  # set by share.google so Strategy 3/4 can use it

    # ── Strategy 0: share.google redirect URL (kgmid + q in final URL) ────────
    if raw_input.startswith('https://share.google/'):
        try:
            resolved = requests.get(raw_input, allow_redirects=True, timeout=10)
            params = parse_qs(urlparse(resolved.url).query)
            kgmid = (params.get('kgmid') or [None])[0]
            biz_name = urllib.parse.unquote_plus((params.get('q') or [''])[0])
            logger.info('Resolved share.google: kgmid=%s, name=%s', kgmid, biz_name)
            if biz_name:
                text_search_query = biz_name
                if profile.city or profile.state:
                    text_search_query = f"{biz_name}, {profile.city or ''} {profile.state or ''}".strip(', ')
                gbp_url = resolved.url  # so downstream strategies see the resolved URL if needed
        except Exception as e:
            logger.warning('share.google resolve failed: %s', e)

    # ── Strategy 1: bare Place ID (ChIJ... or similar) provided directly ──────
    if raw_input and not raw_input.startswith('http'):
        place_id = raw_input
        logger.info('Using provided Place ID: %s', place_id)

    # ── Strategy 2: extract Place ID from URL data parameter ─────────────────
    # Google Maps URLs encode the Place ID in the data= segment as !1sChIJ...
    if not place_id and gbp_url:
        pid_match = re.search(r'!1s(ChIJ[^!&]+)', gbp_url)
        if pid_match:
            place_id = urllib.parse.unquote(pid_match.group(1))
            logger.info('Extracted Place ID from URL data param: %s', place_id)

    # ── Strategy 2b: CID lookup from ?cid= URL ───────────────────────────────
    if not place_id and gbp_url:
        cid_match = re.search(r'[?&]cid=(\d+)', gbp_url)
        if cid_match:
            cid = cid_match.group(1)
            try:
                # Use findplacefromtext with CID as input — Google supports this
                cid_resp = requests.get(
                    'https://maps.googleapis.com/maps/api/place/findplacefromtext/json',
                    params={'input': f'cid:{cid}', 'inputtype': 'textquery', 'fields': 'place_id', 'key': GOOGLE_PLACES_API_KEY},
                    timeout=10,
                )
                cid_data = cid_resp.json()
                candidates = cid_data.get('candidates', [])
                if candidates:
                    place_id = candidates[0].get('place_id')
                    logger.info('Found via CID %s: %s', cid, place_id)
            except Exception as e:
                logger.warning('CID lookup failed: %s', e)

    # ── Strategy 2c: phone number lookup (best for Service Area Businesses) ──
    phone_input = (request.data.get('phone') or '').strip()
    if not place_id and phone_input:
        try:
            phone_resp = requests.get(
                'https://maps.googleapis.com/maps/api/place/findplacefromtext/json',
                params={'input': phone_input, 'inputtype': 'phonenumber', 'fields': 'place_id,name', 'key': GOOGLE_PLACES_API_KEY},
                timeout=10,
            )
            phone_data = phone_resp.json()
            logger.info('Phone lookup status: %s', phone_data.get('status'))
            candidates = phone_data.get('candidates', [])
            if candidates:
                place_id = candidates[0].get('place_id')
                logger.info('Found via phone %s: %s — %s', phone_input, place_id, candidates[0].get('name'))
        except Exception as e:
            logger.warning('Phone lookup failed: %s', e)

    # ── Strategy 3: New Places API v2 (textQuery) ────────────────────────────
    # Better NLP, finds small/new local businesses that the old API misses
    if not place_id and (text_search_query or gbp_url):
        try:
            search_query = text_search_query
            if not search_query and gbp_url:
                name_match = re.search(r'/maps/place/([^/@?]+)', gbp_url)
                search_query = urllib.parse.unquote_plus(name_match.group(1)) if name_match else gbp_url
            if not search_query:
                raise ValueError('No search query')
            coord_match = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', gbp_url) if gbp_url else None

            v2_body: dict = {'textQuery': search_query}
            if coord_match:
                v2_body['locationBias'] = {
                    'circle': {
                        'center': {'latitude': float(coord_match.group(1)), 'longitude': float(coord_match.group(2))},
                        'radius': 50000.0,
                    }
                }

            logger.info('Places API v2 search: %s', search_query)
            v2_resp = requests.post(
                'https://places.googleapis.com/v1/places:searchText',
                json=v2_body,
                headers={
                    'X-Goog-Api-Key': GOOGLE_PLACES_API_KEY,
                    'X-Goog-FieldMask': 'places.id,places.displayName',
                    'Content-Type': 'application/json',
                },
                timeout=10,
            )
            v2_data = v2_resp.json()
            logger.info('Places API v2 status: %s, places: %d', v2_resp.status_code, len(v2_data.get('places', [])))
            places = v2_data.get('places', [])
            if places:
                # v2 returns id as 'places/ChIJxxx' or just 'ChIJxxx' depending on field mask
                raw_id = places[0].get('id', '')
                place_id = raw_id.replace('places/', '') if raw_id.startswith('places/') else raw_id
                logger.info('Found via v2: %s — %s', place_id, places[0].get('displayName', {}).get('text', ''))
        except Exception as e:
            logger.warning('Places API v2 lookup failed: %s', e)

    # ── Strategy 4: Old textsearch fallback ──────────────────────────────────
    if not place_id and (text_search_query or gbp_url):
        try:
            search_query = text_search_query
            if not search_query and gbp_url:
                name_match = re.search(r'/maps/place/([^/@?]+)', gbp_url)
                search_query = urllib.parse.unquote_plus(name_match.group(1)) if name_match else gbp_url
            if not search_query:
                raise ValueError('No search query')
            coord_match = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', gbp_url) if gbp_url else None

            text_params: dict = {'query': search_query, 'key': GOOGLE_PLACES_API_KEY}
            if coord_match:
                text_params['location'] = f"{coord_match.group(1)},{coord_match.group(2)}"
                text_params['radius'] = '50000'

            old_resp = requests.get(
                'https://maps.googleapis.com/maps/api/place/textsearch/json',
                params=text_params,
                timeout=10,
            )
            old_data = old_resp.json()
            logger.info('textsearch (old) status: %s, results: %d', old_data.get('status'), len(old_data.get('results', [])))
            results = old_data.get('results', [])
            if results:
                place_id = results[0].get('place_id')
        except Exception as e:
            logger.warning('textsearch fallback failed: %s', e)

    # ── Last fallback: text search by business_name + city/state (SABs, toll-free) ──
    last_fallback_query = None
    if not place_id:
        search_name = request.data.get('business_name') or profile.business_name or ''
        search_city = profile.city or ''
        search_state = profile.state or ''
        if search_name:
            query = f"{search_name} {search_city} {search_state}".strip()
            last_fallback_query = query
            try:
                ts_resp = requests.get(
                    'https://maps.googleapis.com/maps/api/place/textsearch/json',
                    params={
                        'query': query,
                        'key': GOOGLE_PLACES_API_KEY,
                    },
                    timeout=10,
                )
                ts_data = ts_resp.json()
                results = ts_data.get('results', [])
                if results:
                    place_id = results[0].get('place_id')
                    logger.info('Found via text search "%s": %s', query, place_id)
            except Exception as e:
                logger.warning('Text search failed: %s', e)

    if not place_id:
        name_hint = ''
        if last_fallback_query:
            name_hint = f' for "{last_fallback_query}"'
        elif text_search_query:
            name_hint = f' for "{text_search_query}"'
        elif gbp_url:
            m = re.search(r'/maps/place/([^/@?]+)', gbp_url)
            if m:
                name_hint = f' for "{urllib.parse.unquote_plus(m.group(1))}"'
        return Response({
            'error': (
                f"Couldn't find this business on Google Maps{name_hint}. "
                "Try pasting your Place ID directly instead — find it at: "
                "https://developers.google.com/maps/documentation/javascript/examples/places-placeid-finder"
            ),
            'hint': 'place_id',
        }, status=status.HTTP_404_NOT_FOUND)

    # Fetch place details
    fields = 'name,formatted_address,address_components,formatted_phone_number,opening_hours,rating,user_ratings_total,reviews,types,website,geometry'
    try:
        resp = requests.get(
            'https://maps.googleapis.com/maps/api/place/details/json',
            params={'place_id': place_id, 'fields': fields, 'key': GOOGLE_PLACES_API_KEY},
            timeout=15
        )
        result = resp.json().get('result', {})
    except Exception as e:
        return Response({'error': f'Google Places API error: {e}'}, status=status.HTTP_502_BAD_GATEWAY)

    if not result:
        return Response({'error': 'Place not found'}, status=status.HTTP_404_NOT_FOUND)

    # Map to profile fields
    profile.google_place_id = place_id
    if gbp_url:
        profile.gbp_url = gbp_url
    if result.get('name'):
        profile.business_name = result['name']
    if result.get('formatted_phone_number'):
        profile.phone = result['formatted_phone_number']
    if result.get('rating') is not None:
        profile.gbp_star_rating = result['rating']
    if result.get('user_ratings_total') is not None:
        profile.gbp_review_count = result['user_ratings_total']
    if result.get('types'):
        profile.categories = [t for t in result['types'] if t not in ('point_of_interest', 'establishment')]

    # Parse structured address components
    addr_comps = result.get('address_components', [])
    def _get_comp(types_list, short=False):
        for comp in addr_comps:
            if any(t in comp.get('types', []) for t in types_list):
                return comp.get('short_name' if short else 'long_name', '')
        return ''

    if addr_comps:
        street_num = _get_comp(['street_number'])
        street_name = _get_comp(['route'])
        if street_num and street_name:
            profile.street_address = f"{street_num} {street_name}"
        elif street_name:
            profile.street_address = street_name
        city = _get_comp(['locality']) or _get_comp(['sublocality'])
        if city:
            profile.city = city
        state = _get_comp(['administrative_area_level_1'], short=True)
        if state:
            profile.state = state
        zip_code = _get_comp(['postal_code'])
        if zip_code:
            profile.zip_code = zip_code
        country = _get_comp(['country'], short=True)
        if country:
            profile.country = country
    if result.get('opening_hours', {}).get('weekday_text'):
        hours_dict = {}
        days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        for i, text in enumerate(result['opening_hours']['weekday_text'][:7]):
            hours_dict[days[i]] = text
        profile.hours = hours_dict
    if result.get('geometry', {}).get('location'):
        loc = result['geometry']['location']
        profile.latitude = loc.get('lat')
        profile.longitude = loc.get('lng')

    # SAB detection: if GBP returned no address components, the business hides
    # their address. Mark as service-area business so schema/UI handles correctly.
    if not addr_comps and not getattr(profile, 'street_address', None):
        try:
            profile.is_service_area_business = True
        except AttributeError:
            pass  # column not yet migrated on this environment

    # Reviews — only store 4★ & 5★ (used for CRO recommendations — low-star reviews
    # should never appear in schema or AI-generated content)
    raw_reviews = result.get('reviews', [])
    profile.gbp_reviews = [
        {
            'text': r.get('text', ''),
            'author': r.get('author_name', ''),
            'rating': r.get('rating', 0),
            'date': r.get('relative_time_description', ''),
            'time': r.get('time', 0),
        }
        for r in raw_reviews
        if r.get('rating', 0) >= 4
    ][:20]  # Up to 20 high-quality reviews
    profile.gbp_last_synced = timezone.now()
    profile.save()

    return Response({
        'success': True,
        'place_id': place_id,
        'synced': _serialize_profile(profile),
    })
