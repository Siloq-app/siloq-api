"""
Agency & White-Label API Views
Spec: Siloq White-Label Spec V1 (March 2026) — $1,499 / $2,499
"""
import hashlib
import logging
import secrets

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

from agency.models import AgencyProfile, AgencyClientSite, get_visible_sites, can_add_site

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _profile_to_dict(profile):
    return {
        'id':               profile.id,
        'agency_name':      profile.agency_name,
        'agency_slug':      profile.agency_slug,
        'white_label_tier': profile.white_label_tier,
        'max_sites':        profile.max_sites,
        'sites_used':       profile.sites_used,
        'sites_remaining':  profile.sites_remaining,
        'show_powered_by':  profile.show_powered_by,
        'logo_url':         profile.logo_url or '',
        'logo_small_url':   profile.logo_small_url or '',
        'favicon_url':      profile.favicon_url or '',
        'color_primary':    profile.color_primary,
        'color_secondary':  profile.color_secondary,
        'color_accent':     profile.color_accent,
        'support_email':    profile.support_email or '',
        'support_url':      profile.support_url or '',
        'custom_domain':    profile.custom_domain or '',
        'domain_verified':  profile.domain_verified,
        'updated_at':       profile.updated_at.isoformat() if profile.updated_at else None,
    }


def _branding_hash(profile):
    key = f"{profile.logo_url}{profile.color_primary}{profile.color_secondary}{profile.agency_name}{profile.white_label_tier}"
    return 'sha256:' + hashlib.sha256(key.encode()).hexdigest()[:16]


def _get_or_create_profile(user):
    try:
        return user.agency_profile
    except AgencyProfile.DoesNotExist:
        slug_base = user.email.split('@')[0].replace('.', '-').lower()[:50]
        slug, n = slug_base, 1
        while AgencyProfile.objects.filter(agency_slug=slug).exists():
            slug = f"{slug_base}-{n}"; n += 1
        return AgencyProfile.objects.create(
            user=user,
            agency_name=user.get_full_name() or user.email.split('@')[0],
            agency_slug=slug,
            white_label_tier='PARTIAL',
            max_sites=10,
        )


def _site_to_dict(link):
    return {
        'id':            link.id,
        'site_id':       link.site_id,
        'site_url':      link.site.url,
        'site_name':     getattr(link.site, 'name', link.site.url),
        'is_active':     link.is_active,
        'added_at':      link.added_at.isoformat() if link.added_at else None,
        'client_user_id':    link.client_user_id,
        'client_email':  link.client_user.email if link.client_user else None,
    }


# ── Agency Profile ─────────────────────────────────────────────────────────────

@api_view(['GET', 'PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def agency_profile(request):
    """GET/PUT/PATCH /api/v1/agency/profile/"""
    profile = _get_or_create_profile(request.user)

    if request.method == 'GET':
        return Response(_profile_to_dict(profile))

    updatable = [
        'agency_name', 'logo_url', 'logo_small_url', 'favicon_url',
        'color_primary', 'color_secondary', 'color_accent',
        'support_email', 'support_url',
    ]
    if profile.white_label_tier == 'FULL':
        updatable.append('custom_domain')

    for field in updatable:
        if field in request.data:
            setattr(profile, field, request.data[field])
    profile.save()

    # TODO: bust Redis cache agency_branding:{profile.id}
    return Response(_profile_to_dict(profile))


# ── Site Management ────────────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def agency_sites(request):
    """
    GET  /api/v1/agency/sites/ — list all client sites
    POST /api/v1/agency/sites/ — add a site to agency (enforces max_sites)
    Body: {site_id: int}
    """
    profile = _get_or_create_profile(request.user)

    if request.method == 'GET':
        links = AgencyClientSite.objects.filter(agency=profile).select_related('site', 'client_user')
        return Response({
            'sites':           [_site_to_dict(l) for l in links],
            'total':           links.count(),
            'max_sites':       profile.max_sites,
            'sites_used':      profile.sites_used,
            'sites_remaining': profile.sites_remaining,
        })

    # POST — add site
    if not can_add_site(profile):
        return Response(
            {'error': f'Site limit reached ({profile.max_sites} sites). Upgrade to Agency Pro to add more.'},
            status=status.HTTP_402_PAYMENT_REQUIRED,
        )

    site_id = request.data.get('site_id')
    if not site_id:
        return Response({'error': 'site_id is required'}, status=status.HTTP_400_BAD_REQUEST)

    from sites.models import Site
    site = get_object_or_404(Site, id=site_id, user=request.user)

    link, created = AgencyClientSite.objects.get_or_create(
        agency=profile, site=site,
        defaults={'is_active': True},
    )
    if not created:
        link.is_active = True
        link.save()

    return Response(_site_to_dict(link), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def agency_site_remove(request, site_id):
    """DELETE /api/v1/agency/sites/{site_id}/"""
    profile = _get_or_create_profile(request.user)
    link = get_object_or_404(AgencyClientSite, site_id=site_id, agency=profile)
    link.is_active = False
    link.save()
    return Response({'message': 'Site removed from agency management.'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def agency_site_assign_client(request, site_id):
    """
    POST /api/v1/agency/sites/{site_id}/assign-client/
    Body: {client_user_id: int}  — assigns a client user to view this site
    """
    profile = _get_or_create_profile(request.user)
    link = get_object_or_404(AgencyClientSite, site_id=site_id, agency=profile)

    from accounts.models import User
    client_user_id = request.data.get('client_user_id')
    if client_user_id:
        client = get_object_or_404(User, id=client_user_id)
        link.client_user = client
    else:
        link.client_user = None  # unassign
    link.save()

    return Response(_site_to_dict(link))


# ── Client Management ─────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def client_list(request):
    """GET /api/v1/agency/clients/ — list all client users under this agency"""
    profile = _get_or_create_profile(request.user)
    links = AgencyClientSite.objects.filter(
        agency=profile, client_user__isnull=False
    ).select_related('client_user', 'site').distinct('client_user')

    seen, clients = set(), []
    for link in AgencyClientSite.objects.filter(agency=profile, client_user__isnull=False).select_related('client_user'):
        uid = link.client_user_id
        if uid in seen:
            continue
        seen.add(uid)
        u = link.client_user
        clients.append({
            'user_id':    u.id,
            'email':      u.email,
            'name':       u.get_full_name(),
            'last_login': u.last_login.isoformat() if u.last_login else None,
            'sites':      list(AgencyClientSite.objects.filter(agency=profile, client_user=u).values_list('site__url', flat=True)),
        })

    return Response({'clients': clients, 'total': len(clients)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def client_invite(request):
    """
    POST /api/v1/agency/clients/invite/
    Body: {email: str, site_id: int (optional)}
    Creates an invite; optionally pre-assigns to a site.
    """
    profile = _get_or_create_profile(request.user)
    email = request.data.get('email', '').strip().lower()
    if not email:
        return Response({'error': 'email is required'}, status=status.HTTP_400_BAD_REQUEST)

    token = secrets.token_urlsafe(32)

    # Store invite token on AgencyProfile (simple approach for V1)
    # The client clicks the link, registers/logs in, then we assign them
    # For now: return the invite URL; email delivery is a Day 4 task
    invite_url = f"https://app.siloq.ai/invite/{token}"

    # Optionally pre-link to a site
    site_id = request.data.get('site_id')
    if site_id:
        link = AgencyClientSite.objects.filter(agency=profile, site_id=site_id).first()
        if link:
            link.client_user = None  # will be set when client accepts
            link.save()

    logger.info("Agency %s invited %s (token %s)", profile.agency_slug, email, token)

    return Response({
        'email':      email,
        'invite_url': invite_url,
        'token':      token,
        'message':    f'Share this link with {email} to give them access.',
    }, status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def client_remove(request, user_id):
    """DELETE /api/v1/agency/clients/{user_id}/ — remove client user access"""
    profile = _get_or_create_profile(request.user)
    AgencyClientSite.objects.filter(agency=profile, client_user_id=user_id).update(client_user=None)
    return Response({'message': 'Client access removed.'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def switch_context(request, user_id):
    """
    POST /api/v1/agency/switch-context/{user_id}/
    Returns scoped JWT for view-as-client. Agency Pro only.
    """
    profile = _get_or_create_profile(request.user)
    if profile.white_label_tier != 'FULL':
        return Response(
            {'error': 'View-as-client requires Agency Pro ($2,499/mo).'},
            status=status.HTTP_403_FORBIDDEN,
        )

    from accounts.models import User
    client = get_object_or_404(User, id=user_id)

    # Verify this client has at least one site under this agency
    if not AgencyClientSite.objects.filter(agency=profile, client_user=client, is_active=True).exists():
        return Response({'error': 'User is not a client of this agency.'}, status=status.HTTP_404_NOT_FOUND)

    from accounts.auth import generate_tokens_for_user
    tokens = generate_tokens_for_user(client)

    return Response({
        'message':      f'Viewing dashboard as {client.email}',
        'client_email': client.email,
        'access':       tokens['access'],
        'refresh':      tokens['refresh'],
    })


# ── Branding Resolution (public + authenticated) ───────────────────────────────

@api_view(['GET'])
@permission_classes([AllowAny])
def branding_resolve(request):
    """
    GET /api/v1/branding/resolve/?domain={domain}
    GET /api/v1/branding/resolve/?slug={slug}
    Public endpoint — Next.js middleware calls this for SSR before first paint.
    """
    domain = request.query_params.get('domain', '').strip()
    slug   = request.query_params.get('slug', '').strip()
    profile = None

    if domain:
        if domain.endswith('.app.siloq.ai'):
            slug = domain.replace('.app.siloq.ai', '')
        else:
            profile = AgencyProfile.objects.filter(custom_domain=domain, domain_verified=True).first()

    if slug and not profile:
        profile = AgencyProfile.objects.filter(agency_slug=slug).first()

    if not profile:
        return Response({
            'is_white_labeled': False,
            'agency_name':      'Siloq',
            'agency_slug':      None,
            'white_label_tier': None,
            'show_powered_by':  True,
            'logo_url':         '',
            'favicon_url':      '',
            'color_primary':    '#E8D48B',
            'color_secondary':  '#C8A951',
            'color_accent':     '#3B82F6',
            'color_background': '#1A1A2E',
            'color_text':       '#F8F8F8',
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
        'support_email':    profile.support_email or '',
        'support_url':      profile.support_url or '',
        'branding_hash':    _branding_hash(profile),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def branding_plugin_config(request):
    """
    GET /api/v1/branding/plugin-config/
    Returns plugin display config for the site's agency (if any).
    Called by WP plugin on each admin page load to apply Layer 2 branding.
    """
    site_id = request.query_params.get('site_id')
    profile = None

    if site_id:
        link = AgencyClientSite.objects.filter(site_id=site_id, is_active=True).select_related('agency').first()
        if link:
            profile = link.agency

    if not profile:
        return Response({
            'display_name':    'Siloq',
            'settings_title':  'Siloq SEO Settings',
            'admin_menu_label':'Siloq',
            'admin_menu_icon': '',
            'color_primary':   '#E8D48B',
            'support_email':   'support@siloq.ai',
            'support_url':     'https://siloq.ai/support',
            'show_powered_by': True,
        })

    return Response({
        'display_name':    f"{profile.agency_name} SEO Platform",
        'settings_title':  f"{profile.agency_name} SEO Settings",
        'admin_menu_label': profile.agency_name,
        'admin_menu_icon': profile.logo_small_url or '',
        'color_primary':   profile.color_primary,
        'support_email':   profile.support_email or 'support@siloq.ai',
        'support_url':     profile.support_url or 'https://siloq.ai/support',
        'show_powered_by': profile.show_powered_by,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def branding_verify_domain(request):
    """POST /api/v1/branding/verify-domain/ — Agency Pro only"""
    profile = _get_or_create_profile(request.user)
    if profile.white_label_tier != 'FULL':
        return Response(
            {'error': 'Custom domain requires Agency Pro ($2,499/mo).'},
            status=status.HTTP_403_FORBIDDEN,
        )

    domain = request.data.get('domain', '').strip()
    if not domain:
        return Response({'error': 'domain is required'}, status=status.HTTP_400_BAD_REQUEST)

    profile.custom_domain = domain
    profile.domain_verified = False
    profile.domain_verified_at = None
    profile.save()

    # Background job will verify DNS CNAME → dashboard.siloq.ai
    return Response({
        'domain':   domain,
        'verified': False,
        'message':  'Add the CNAME record below, then call this endpoint again to check.',
        'instructions': {
            'type':  'CNAME',
            'name':  domain,
            'value': 'dashboard.siloq.ai',
        }
    })
