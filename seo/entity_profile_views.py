"""
Site Entity Profile API — business data for schema generation.

GET  /api/v1/sites/{site_id}/entity-profile/      — get or create profile
PATCH /api/v1/sites/{site_id}/entity-profile/     — update profile fields
POST /api/v1/sites/{site_id}/entity-profile/sync-gbp/  — sync from Google Places
"""
import logging
import os
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
    return {
        'id': profile.id,
        'business_name': profile.business_name,
        'description': profile.description,
        'phone': profile.phone,
        'email': profile.email,
        'founding_year': profile.founding_year,
        'founder_name': profile.founder_name,
        'num_employees': profile.num_employees,
        'price_range': profile.price_range,
        'languages': profile.languages,
        'payment_methods': profile.payment_methods,
        'street_address': profile.street_address,
        'city': profile.city,
        'state': profile.state,
        'zip_code': profile.zip_code,
        'country': profile.country,
        'latitude': profile.latitude,
        'longitude': profile.longitude,
        'service_cities': profile.service_cities,
        'service_zips': profile.service_zips,
        'service_radius_miles': profile.service_radius_miles,
        'hours': profile.hours,
        'categories': profile.categories,
        'certifications': profile.certifications,
        'license_numbers': profile.license_numbers,
        'social_profiles': {
            'facebook': profile.url_facebook,
            'instagram': profile.url_instagram,
            'linkedin': profile.url_linkedin,
            'twitter': profile.url_twitter,
            'youtube': profile.url_youtube,
            'tiktok': profile.url_tiktok,
        },
        'gbp_url': profile.gbp_url,
        'google_place_id': profile.google_place_id,
        'gbp_star_rating': profile.gbp_star_rating,
        'gbp_review_count': profile.gbp_review_count,
        'gbp_reviews': profile.gbp_reviews,
        'gbp_last_synced': profile.gbp_last_synced.isoformat() if profile.gbp_last_synced else None,
        'updated_at': profile.updated_at.isoformat(),
    }


UPDATABLE_FIELDS = [
    'business_name', 'description', 'phone', 'email', 'founding_year', 'founder_name',
    'num_employees', 'price_range', 'languages', 'payment_methods',
    'street_address', 'city', 'state', 'zip_code', 'country',
    'service_cities', 'service_zips', 'service_radius_miles', 'hours',
    'categories', 'certifications', 'license_numbers',
    'gbp_url', 'google_place_id',
]
SOCIAL_FIELD_MAP = {
    'facebook': 'url_facebook', 'instagram': 'url_instagram', 'linkedin': 'url_linkedin',
    'twitter': 'url_twitter', 'youtube': 'url_youtube', 'tiktok': 'url_tiktok',
}


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def entity_profile(request, site_id):
    site = get_object_or_404(Site, id=site_id, user=request.user)
    profile = _get_or_create_profile(site)

    if request.method == 'GET':
        return Response(_serialize_profile(profile))

    # PATCH
    data = request.data
    for field in UPDATABLE_FIELDS:
        if field in data:
            setattr(profile, field, data[field])

    social = data.get('social_profiles', {})
    for key, model_field in SOCIAL_FIELD_MAP.items():
        if key in social:
            setattr(profile, model_field, social[key])

    profile.save()
    return Response(_serialize_profile(profile))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def sync_gbp(request, site_id):
    """Sync business data from Google Places API using place_id or GBP URL."""
    site = get_object_or_404(Site, id=site_id, user=request.user)
    profile = _get_or_create_profile(site)

    if not GOOGLE_PLACES_API_KEY:
        return Response({'error': 'GOOGLE_PLACES_API_KEY not configured'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    place_id = request.data.get('place_id') or profile.google_place_id
    gbp_url = request.data.get('gbp_url') or profile.gbp_url

    # Resolve place_id from URL if needed
    if not place_id and gbp_url:
        try:
            find_resp = requests.get(
                'https://maps.googleapis.com/maps/api/place/findplacefromtext/json',
                params={'input': gbp_url, 'inputtype': 'textquery', 'fields': 'place_id', 'key': GOOGLE_PLACES_API_KEY},
                timeout=10
            )
            candidates = find_resp.json().get('candidates', [])
            if candidates:
                place_id = candidates[0].get('place_id')
        except Exception as e:
            logger.warning('Place ID lookup failed: %s', e)

    if not place_id:
        return Response({'error': 'Provide place_id or gbp_url'}, status=status.HTTP_400_BAD_REQUEST)

    # Fetch place details
    fields = 'name,formatted_address,formatted_phone_number,opening_hours,rating,user_ratings_total,reviews,types,website,geometry'
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
        profile.categories = result['types']
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

    # Reviews — store up to 20 most recent
    raw_reviews = result.get('reviews', [])
    profile.gbp_reviews = [
        {
            'text': r.get('text', ''),
            'author': r.get('author_name', ''),
            'rating': r.get('rating', 0),
            'date': r.get('relative_time_description', ''),
            'time': r.get('time', 0),
        }
        for r in raw_reviews[:20]
    ]
    profile.gbp_last_synced = timezone.now()
    profile.save()

    return Response({
        'success': True,
        'place_id': place_id,
        'synced': _serialize_profile(profile),
    })
