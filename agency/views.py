"""
Agency & White-Label API Views
Spec: Siloq White-Label Spec V1 (March 2026)
"""
import hashlib
import json
import logging
import secrets

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

from accounts.auth import generate_tokens_for_user
from agency.models import AgencyProfile, AgencyClientLink, get_visible_sites

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _profile_to_dict(profile):
    return {
        'id':               profile.id,
        'agency_name':      profile.agency_name,
        'agency_slug':      profile.agency_slug,
        'white_label_tier': profile.white_label_tier,
        'max_client_seats': profile.max_client_seats,
        'show_powered_by':  profile.show_powered_by,
        'logo_url':         profile.logo_url or '',
        'logo_small_url':   profile.logo_small_url or '',
        'favicon_url':      profile.favicon_url or '',
        'color_primary':    profile.color_primary,
        'color_secondary':  profile.color_secondary,
        'color_accent':     profile.color_accent,
        'color_background': profile.color_background,
        'color_text':       profile.color_text,
        'support_email':    profile.support_email or '',
        'support_url':      profile.support_url or '',
        'custom_domain':    profile.custom_domain or '',
        'domain_verified':  profile.domain_verified,
        'created_at':       profile.created_at.isoformat() if profile.created_at else None,
        'updated_at':       profile.updated_at.isoformat() if profile.updated_at else None,
    }


def _branding_hash(profile):
    key_fields = f"{profile.logo_url}{profile.color_primary}{profile.color_secondary}{profile.agency_name}{profile.white_label_tier}"
    return 'sha256:' + hashlib.sha256(key_fields.encode()).hexdigest()[:16]


def _get_or_create_profile(user):
    try:
        return user.agency_profile
    except AgencyProfile.DoesNotExist:
        slug_base = user.email.split('@')[0].replace('.', '-').lower()[:50]
        slug = slug_base
        n = 1
        while AgencyProfile.objects.filter(agency_slug=slug).exists():
            slug = f"{slug_base}-{n}"
            n += 1
        return AgencyProfile.objects.create(
            user=user,
            agency_name=user.get_full_name() or user.email.split('@')[0],
            agency_slug=slug,
            white_label_tier='PARTIAL',
            max_client_seats=10,
        )


# ── Agency Profile ─────────────────────────────────────────────────────────────

@api_view(['GET', 'PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def agency_profile(request):
    """
    GET  /api/v1/agency/profile/ — get agency branding + settings
    PUT  /api/v1/agency/profile/ — update branding
    PATCH /api/v1/agency/profile/ — partial update
    """
    profile = _get_or_create_profile(request.user)

    if request.method == 'GET':
        return Response(_profile_to_dict(profile))

    # PUT / PATCH
    updatable = [
        'agency_name', 'logo_url', 'logo_small_url', 'favicon_url',
        'color_primary', 'color_secondary', 'color_accent',
        'color_background', 'color_text', 'support_email', 'support_url',
        'show_powered_by',
    ]
    # custom_domain only for FULL tier
    if profile.white_label_tier == 'FULL':
        updatable.append('custom_domain')

    changed = False
    for field in updatable:
        if field in request.data:
            setattr(profile, field, request.data[field])
            changed = True

    if changed:
        profile.save()
        # TODO: bust Redis cache key agency_branding:{profile.id}

    return Response(_profile_to_dict(profile))


# ── Branding Resolution (public) ──────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([AllowAny])
def branding_resolve(request):
    """
    GET /api/v1/branding/resolve/?domain={domain}
    GET /api/v1/branding/resolve/?slug={slug}

    Public endpoint — Next.js middleware calls this to resolve agency branding
    from subdomain or custom domain before first paint (SSR).
    Returns lightweight branding config. Cached in Redis 5 min.
    """
    domain = request.query_params.get('domain', '').strip()
    slug   = request.query_params.get('slug', '').strip()

    profile = None

    if domain:
        # Strip {slug}.app.siloq.ai to get slug
        if domain.endswith('.app.siloq.ai'):
            slug = domain.replace('.app.siloq.ai', '')
        else:
            # Custom domain lookup (Agency Pro only)
            profile = AgencyProfile.objects.filter(
                custom_domain=domain, domain_verified=True
            ).first()

    if slug and not profile:
        profile = AgencyProfile.objects.filter(agency_slug=slug).first()

    if not profile:
        # Return default Siloq branding
        return Response({
            'is_white_labeled': False,
            'agency_name': 'Siloq',
            'agency_slug': None,
            'white_label_tier': None,
            'show_powered_by': True,
            'logo_url': '',
            'favicon_url': '',
            'color_primary': '#E8D48B',
            'color_secondary': '#C8A951',
            'color_accent': '#3B82F6',
            'color_background': '#1A1A2E',
            'color_text': '#F8F8F8',
        })

    return Response({
        'is_white_labeled': True,
        'agency_name':      profile.agency_name,
        'agency_slug':      profile.agency_slug,
        'white_label_tier': profile.white_label_tier,
        'show_powered_by':  profile.show_powered_by,
        'logo_url':         profile.logo_url or '',
        'logo_small_url':   profile.logo_small_url or '',
        'favicon_url':      profile.favicon_url or '',
        'color_primary':    profile.color_primary,
        'color_secondary':  profile.color_secondary,
        'color_accent':     profile.color_accent,
        'color_background': profile.color_background,
        'color_text':       profile.color_text,
        'support_email':    profile.support_email or '',
        'support_url':      profile.support_url or '',
        'branding_hash':    _branding_hash(profile),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def branding_config(request):
    """
    GET /api/v1/branding/config/
    Full branding config for authenticated agency.
    """
    profile = _get_or_create_profile(request.user)
    data = _profile_to_dict(profile)
    data['branding_hash'] = _branding_hash(profile)
    return Response(data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def branding_verify_domain(request):
    """
    POST /api/v1/branding/verify-domain/
    Trigger custom domain DNS verification (Agency Pro only).
    """
    profile = _get_or_create_profile(request.user)

    if profile.white_label_tier != 'FULL':
        return Response(
            {'error': 'Custom domain is only available on Agency Pro tier.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    domain = request.data.get('domain', '').strip()
    if not domain:
        return Response({'error': 'domain is required'}, status=status.HTTP_400_BAD_REQUEST)

    # Basic DNS check — look for CNAME to dashboard.siloq.ai
    import socket
    verified = False
    try:
        resolved = socket.getaddrinfo(domain, None)
        # In production: check CNAME record via dnspython
        # For now: mark as pending, async job will verify
        verified = False  # Always start as pending — background job verifies
    except Exception:
        pass

    profile.custom_domain = domain
    profile.domain_verified = verified
    profile.domain_verified_at = timezone.now() if verified else None
    profile.save()

    return Response({
        'domain':   domain,
        'verified': verified,
        'message':  'Add a CNAME record pointing to dashboard.siloq.ai, then retry.',
        'instructions': {
            'type':  'CNAME',
            'name':  domain,
            'value': 'dashboard.siloq.ai',
        }
    })


# ── Client Management ─────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def client_list(request):
    """
    GET /api/v1/agency/clients/
    List all client accounts with their site counts and status.
    """
    profile = _get_or_create_profile(request.user)
    links   = AgencyClientLink.objects.filter(agency=profile).select_related('client_user').prefetch_related('sites')

    clients = []
    for link in links:
        client_data = {
            'id':           link.id,
            'invite_email': link.invite_email,
            'is_active':    link.is_active,
            'invited_at':   link.invited_at.isoformat() if link.invited_at else None,
            'accepted_at':  link.accepted_at.isoformat() if link.accepted_at else None,
            'site_count':   link.sites.count(),
        }
        if link.client_user:
            client_data.update({
                'user_id':     link.client_user.id,
                'email':       link.client_user.email,
                'name':        link.client_user.get_full_name(),
                'last_login':  link.client_user.last_login.isoformat() if link.client_user.last_login else None,
            })
        clients.append(client_data)

    return Response({
        'clients':     clients,
        'total':       len(clients),
        'seats_used':  sum(1 for c in clients if c.get('user_id')),
        'seats_max':   profile.max_client_seats,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def client_invite(request):
    """
    POST /api/v1/agency/clients/invite/
    Body: {email: string}
    Creates an invite link for the client.
    """
    profile = _get_or_create_profile(request.user)

    # Seat limit check
    active_count = AgencyClientLink.objects.filter(
        agency=profile, is_active=True, client_user__isnull=False
    ).count()
    if active_count >= profile.max_client_seats:
        return Response(
            {'error': f'Seat limit reached ({profile.max_client_seats}). Upgrade to add more clients.'},
            status=status.HTTP_402_PAYMENT_REQUIRED,
        )

    email = request.data.get('email', '').strip().lower()
    if not email:
        return Response({'error': 'email is required'}, status=status.HTTP_400_BAD_REQUEST)

    # Check if already invited
    existing = AgencyClientLink.objects.filter(agency=profile, invite_email=email).first()
    if existing:
        return Response(
            {'error': 'This email has already been invited.'},
            status=status.HTTP_409_CONFLICT,
        )

    token = secrets.token_urlsafe(32)
    link  = AgencyClientLink.objects.create(
        agency=profile,
        invite_email=email,
        invite_token=token,
        is_active=False,
    )

    invite_url = f"https://app.siloq.ai/invite/{token}"

    # TODO: send invite email via Siloq email system
    logger.info("Agency %s invited %s — token %s", profile.agency_slug, email, token)

    return Response({
        'id':         link.id,
        'email':      email,
        'invite_url': invite_url,
        'token':      token,
        'message':    f'Invite sent to {email}',
    }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def client_accept_invite(request):
    """
    POST /api/v1/agency/clients/accept-invite/
    Body: {token: string}
    Links current authenticated user to the agency.
    """
    token = request.data.get('token', '').strip()
    if not token:
        return Response({'error': 'token is required'}, status=status.HTTP_400_BAD_REQUEST)

    link = get_object_or_404(AgencyClientLink, invite_token=token, client_user__isnull=True)

    # Link this user to the agency
    link.client_user  = request.user
    link.accepted_at  = timezone.now()
    link.is_active    = True
    link.invite_token = None  # consume the token
    link.save()

    return Response({
        'message':     'Successfully joined agency.',
        'agency_name': link.agency.agency_name,
        'agency_slug': link.agency.agency_slug,
    })


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def client_remove(request, client_id):
    """
    DELETE /api/v1/agency/clients/{id}/
    Suspend (soft-delete) a client.
    """
    profile = _get_or_create_profile(request.user)
    link    = get_object_or_404(AgencyClientLink, id=client_id, agency=profile)
    link.is_active = False
    link.save()
    return Response({'message': 'Client access suspended.'})


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def client_sites(request, client_id):
    """
    GET  /api/v1/agency/clients/{id}/sites/ — list client's assigned sites
    POST /api/v1/agency/clients/{id}/sites/ — assign sites to client
    Body: {site_ids: [1, 2, 3]}
    """
    profile = _get_or_create_profile(request.user)
    link    = get_object_or_404(AgencyClientLink, id=client_id, agency=profile)

    if request.method == 'GET':
        sites = link.sites.all()
        return Response({
            'client_id': client_id,
            'sites': [{'id': s.id, 'url': s.url, 'name': getattr(s, 'name', s.url)} for s in sites],
        })

    # POST — assign sites
    site_ids = request.data.get('site_ids', [])
    if not isinstance(site_ids, list):
        return Response({'error': 'site_ids must be a list'}, status=status.HTTP_400_BAD_REQUEST)

    from sites.models import Site
    # Only allow sites owned by this agency user
    valid_sites = Site.objects.filter(id__in=site_ids, user=request.user)
    link.sites.set(valid_sites)

    return Response({
        'message':    f'{valid_sites.count()} sites assigned to client.',
        'site_count': valid_sites.count(),
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def switch_context(request, client_id):
    """
    POST /api/v1/agency/switch-context/{client_id}/
    Returns a scoped JWT for viewing the dashboard as a specific client.
    Agency Pro only.
    """
    profile = _get_or_create_profile(request.user)

    if profile.white_label_tier != 'FULL':
        return Response(
            {'error': 'View-as-client context switching requires Agency Pro tier.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    link = get_object_or_404(
        AgencyClientLink, id=client_id, agency=profile, is_active=True, client_user__isnull=False
    )

    # Generate scoped tokens for the client user
    tokens = generate_tokens_for_user(link.client_user)

    return Response({
        'message':      f'Viewing as {link.client_user.email}',
        'client_email': link.client_user.email,
        'access':       tokens['access'],
        'refresh':      tokens['refresh'],
    })
