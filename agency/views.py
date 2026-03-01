import secrets
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status

from .models import AgencyProfile, AgencyClientLink


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BRANDING_CONTEXT_FIELDS = [
    'agency_name', 'agency_slug', 'white_label_tier', 'show_powered_by',
    'logo_url', 'color_primary', 'color_secondary', 'color_accent',
    'color_background', 'color_text', 'favicon_url',
]

BRANDING_ALL_FIELDS = BRANDING_CONTEXT_FIELDS + [
    'logo_small_url', 'support_email', 'support_url', 'tagline',
    'custom_domain', 'domain_verified', 'domain_verified_at',
    'created_at', 'updated_at',
]

BRANDING_PATCH_ALLOWED = [
    'agency_name', 'white_label_tier', 'logo_url', 'logo_small_url',
    'favicon_url', 'color_primary', 'color_secondary', 'color_accent',
    'color_background', 'color_text', 'support_email', 'support_url',
    'tagline', 'custom_domain', 'show_powered_by',
]


def _profile_to_dict(profile, fields=None):
    if fields is None:
        fields = BRANDING_ALL_FIELDS
    data = {}
    for f in fields:
        val = getattr(profile, f, None)
        if hasattr(val, 'isoformat'):
            val = val.isoformat()
        data[f] = val
    data['id'] = profile.pk
    return data


def _get_or_create_profile(user):
    try:
        return user.agency_profile
    except AgencyProfile.DoesNotExist:
        slug_base = slugify(user.email.split('@')[0]) or 'agency'
        slug = slug_base
        counter = 1
        while AgencyProfile.objects.filter(agency_slug=slug).exists():
            slug = f"{slug_base}-{counter}"
            counter += 1
        return AgencyProfile.objects.create(
            user=user,
            agency_name=slug_base.replace('-', ' ').title(),
            agency_slug=slug,
        )


# ---------------------------------------------------------------------------
# Branding endpoints
# ---------------------------------------------------------------------------

@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def branding(request):
    """GET/PATCH /api/v1/agency/branding/"""
    profile = _get_or_create_profile(request.user)

    if request.method == 'GET':
        return Response(_profile_to_dict(profile))

    # PATCH
    errors = {}
    for key, value in request.data.items():
        if key not in BRANDING_PATCH_ALLOWED:
            continue
        # Basic hex color validation
        if key.startswith('color_') and value:
            if not (value.startswith('#') and len(value) in (4, 7)):
                errors[key] = 'Must be a valid hex color (e.g. #RGB or #RRGGBB).'
                continue
        setattr(profile, key, value)

    if errors:
        return Response({'errors': errors}, status=status.HTTP_400_BAD_REQUEST)

    profile.save()
    return Response(_profile_to_dict(profile))


@api_view(['GET'])
def branding_context(request):
    """
    GET /api/v1/agency/branding/context/

    Public when ?slug= or ?domain= is provided.
    Authenticated when neither is provided (returns caller's own branding).
    """
    slug = request.query_params.get('slug')
    domain = request.query_params.get('domain')

    if slug:
        try:
            profile = AgencyProfile.objects.get(agency_slug=slug)
        except AgencyProfile.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(_profile_to_dict(profile, BRANDING_CONTEXT_FIELDS))

    if domain:
        try:
            profile = AgencyProfile.objects.get(custom_domain=domain)
        except AgencyProfile.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(_profile_to_dict(profile, BRANDING_CONTEXT_FIELDS))

    # No slug/domain — require auth and return caller's own profile
    if not request.user or not request.user.is_authenticated:
        return Response(
            {'detail': 'Authentication required when no slug or domain is provided.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    profile = _get_or_create_profile(request.user)
    return Response(_profile_to_dict(profile, BRANDING_CONTEXT_FIELDS))


# ---------------------------------------------------------------------------
# Client management endpoints
# ---------------------------------------------------------------------------

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def client_list(request):
    """GET /api/v1/agency/clients/"""
    links = AgencyClientLink.objects.filter(
        agency=request.user,
    ).select_related('client')

    results = []
    for link in links:
        client = link.client
        site_count = 0
        try:
            from sites.models import Site
            site_count = Site.objects.filter(user=client).count()
        except Exception:
            pass

        results.append({
            'id': link.pk,
            'client_id': client.pk,
            'email': client.email,
            'status': link.status,
            'sites_count': site_count,
            'invited_at': link.invited_at.isoformat() if link.invited_at else None,
            'accepted_at': link.accepted_at.isoformat() if link.accepted_at else None,
            'last_login': client.last_login.isoformat() if getattr(client, 'last_login', None) else None,
        })

    return Response(results)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def client_invite(request):
    """POST /api/v1/agency/clients/invite/"""
    email = request.data.get('email', '').strip().lower()
    if not email:
        return Response({'detail': 'email is required.'}, status=status.HTTP_400_BAD_REQUEST)

    # Check for existing active/invited link to same email
    existing = AgencyClientLink.objects.filter(
        agency=request.user,
        invite_email=email,
        status='invited',
    ).first()
    if existing:
        token = existing.invite_token
        return Response({
            'detail': 'Invite already pending.',
            'invite_link': f'https://app.siloq.ai/invite/{token}',
        })

    token = secrets.token_urlsafe(48)[:64]

    link = AgencyClientLink.objects.create(
        agency=request.user,
        client_id=None,  # not registered yet
        status='invited',
        invite_email=email,
        invite_token=token,
    )

    return Response({
        'detail': 'Invite created.',
        'invite_link': f'https://app.siloq.ai/invite/{token}',
    }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def client_accept_invite(request):
    """POST /api/v1/agency/clients/accept-invite/"""
    token = request.data.get('token', '').strip()
    if not token:
        return Response({'detail': 'token is required.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        link = AgencyClientLink.objects.get(invite_token=token, status='invited')
    except AgencyClientLink.DoesNotExist:
        return Response({'detail': 'Invalid or expired invite token.'}, status=status.HTTP_404_NOT_FOUND)

    # Prevent duplicate agency<->client relationship
    if AgencyClientLink.objects.filter(agency=link.agency, client=request.user).exists():
        return Response({'detail': 'You are already linked to this agency.'}, status=status.HTTP_400_BAD_REQUEST)

    link.client = request.user
    link.status = 'active'
    link.accepted_at = timezone.now()
    link.invite_token = None  # consume the token
    link.save()

    return Response({'detail': 'Invite accepted. You are now linked to the agency.'})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def client_remove(request, client_id):
    """DELETE /api/v1/agency/clients/{client_id}/"""
    try:
        link = AgencyClientLink.objects.get(agency=request.user, client_id=client_id)
    except AgencyClientLink.DoesNotExist:
        return Response({'detail': 'Client not found.'}, status=status.HTTP_404_NOT_FOUND)

    link.status = 'suspended'
    link.save()
    return Response({'detail': 'Client suspended.'})
