"""
Team management views.
Handles team member invitations and access control.
"""
import logging
from datetime import timedelta
from django.utils import timezone
from django.db.models import Q
import resend
from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import TeamInvite, SiteAccess, User
from sites.models import Site

logger = logging.getLogger(__name__)

# Subscription tier limits for team members
TIER_LIMITS = {
    'free': 0,
    'free_trial': 1,
    'pro': 1,
    'builder': 3,
    'builder_plus': 3,
    'architect': 5,
    'empire': 10,
}


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def team_list(request):
    """
    List all team members across user's sites.
    
    GET /api/v1/team/
    Returns: { "team_members": [...], "invites": [...], "limits": {...} }
    """
    user = request.user
    
    # Get all sites owned by the user
    owned_sites = user.sites.all()
    
    # Get team members (users with access to owned sites)
    team_members = []
    for site in owned_sites:
        accesses = SiteAccess.objects.filter(site=site).select_related('user', 'site')
        for access in accesses:
            team_members.append({
                'id': access.id,
                'user_id': access.user.id,
                'email': access.user.email,
                'name': f"{access.user.first_name} {access.user.last_name}".strip() or access.user.email,
                'role': access.role,
                'site_id': site.id,
                'site_name': site.name,
                'granted_at': access.created_at.isoformat(),
            })
    
    # Get pending invites
    pending_invites = TeamInvite.objects.filter(
        invited_by=user,
        status='pending',
        expires_at__gt=timezone.now()
    ).select_related('site')
    
    invites = [{
        'id': invite.id,
        'email': invite.email,
        'role': invite.role,
        'site_id': invite.site.id,
        'site_name': invite.site.name,
        'status': invite.status,
        'created_at': invite.created_at.isoformat(),
        'expires_at': invite.expires_at.isoformat(),
    } for invite in pending_invites]
    
    # Get subscription tier and limits
    tier = user.subscription_tier or 'free'
    max_team_members = TIER_LIMITS.get(tier, 0)
    current_count = SiteAccess.objects.filter(site__user=user).count()
    
    return Response({
        'team_members': team_members,
        'invites': invites,
        'limits': {
            'tier': tier,
            'max_members': max_team_members,
            'current_count': current_count,
            'can_invite': current_count < max_team_members,
        }
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def team_invite(request):
    """
    Invite a team member by email.
    
    POST /api/v1/team/invite/
    Body: { "email": "...", "role": "viewer|editor|admin", "site_id": 123 }
    Returns: { "invite": {...}, "message": "..." }
    """
    user = request.user
    data = request.data
    
    # Validate input
    email = data.get('email', '').strip().lower()
    role = data.get('role', 'viewer')
    site_id = data.get('site_id')
    
    if not email:
        return Response({'error': 'Email is required'}, status=status.HTTP_400_BAD_REQUEST)
    
    if role not in ['viewer', 'editor', 'admin']:
        return Response({'error': 'Invalid role'}, status=status.HTTP_400_BAD_REQUEST)
    
    # If no site_id provided, use the first owned site (dashboard invites without site context)
    if not site_id:
        site = Site.objects.filter(user=user).first()
        if not site:
            return Response({'error': 'No sites found. Create a site first.'}, status=status.HTTP_400_BAD_REQUEST)
    else:
        # Check if site exists and user owns it
        try:
            site = Site.objects.get(id=site_id, user=user)
        except Site.DoesNotExist:
            return Response({'error': 'Site not found or access denied'}, status=status.HTTP_404_NOT_FOUND)
    
    # Check subscription limits
    tier = user.subscription_tier or 'free'
    max_team_members = TIER_LIMITS.get(tier, 0)
    current_count = SiteAccess.objects.filter(site__user=user).count()
    
    if current_count >= max_team_members:
        return Response({
            'error': f'Team member limit reached. Your {tier} plan allows {max_team_members} team members.',
            'upgrade_required': True
        }, status=status.HTTP_403_FORBIDDEN)
    
    # Check if user is trying to invite themselves
    if email == user.email:
        return Response({'error': 'Cannot invite yourself'}, status=status.HTTP_400_BAD_REQUEST)
    
    # Check if there's already an active invite
    existing_invite = TeamInvite.objects.filter(
        email=email,
        site=site,
        status='pending',
        expires_at__gt=timezone.now()
    ).first()
    
    if existing_invite:
        return Response({
            'error': 'An active invitation already exists for this email',
            'invite': {
                'id': existing_invite.id,
                'created_at': existing_invite.created_at.isoformat(),
                'expires_at': existing_invite.expires_at.isoformat(),
            }
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # Check if user already has access
    invited_user = User.objects.filter(email=email).first()
    if invited_user:
        existing_access = SiteAccess.objects.filter(user=invited_user, site=site).first()
        if existing_access:
            return Response({
                'error': 'This user already has access to the site',
                'access': {
                    'role': existing_access.role,
                    'granted_at': existing_access.created_at.isoformat(),
                }
            }, status=status.HTTP_400_BAD_REQUEST)
    
    # Create the invite
    token = TeamInvite.generate_token()
    expires_at = timezone.now() + timedelta(days=7)
    
    invite = TeamInvite.objects.create(
        email=email,
        role=role,
        invited_by=user,
        site=site,
        token=token,
        expires_at=expires_at
    )
    
    # Send invite email via Resend
    try:
        invite_url = f"{settings.FRONTEND_URL}/invite?token={token}"
        inviter_name = f"{user.first_name} {user.last_name}".strip() or user.email

        resend.api_key = settings.RESEND_API_KEY

        html_message = f"""<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
  <div style="text-align: center; margin-bottom: 30px;">
    <h1 style="color: #6C5CE7; font-size: 28px; margin: 0;">Siloq</h1>
  </div>
  <h2 style="color: #1a1a2e;">You've been invited!</h2>
  <p style="color: #555; line-height: 1.6;">
    <strong>{inviter_name}</strong> has invited you to join <strong>{site.name}</strong> on Siloq as a <strong>{role}</strong>.
  </p>
  <div style="text-align: center; margin: 30px 0;">
    <a href="{invite_url}" style="background: #6C5CE7; color: white; padding: 14px 28px; border-radius: 8px; text-decoration: none; font-weight: bold; font-size: 16px;">
      Accept Invitation
    </a>
  </div>
  <p style="color: #999; font-size: 13px;">
    This invitation expires in 7 days. If you don't have a Siloq account yet, you'll be prompted to create one when you accept.
  </p>
  <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
  <p style="color: #999; font-size: 12px; text-align: center;">
    Siloq &middot; <a href="https://app.siloq.ai" style="color: #6C5CE7;">app.siloq.ai</a>
  </p>
</div>"""

        params = {
            "from": "Siloq <support@updates.siloq.ai>",
            "to": [email],
            "subject": f"{inviter_name} invited you to join {site.name} on Siloq",
            "html": html_message,
            "text": f"{inviter_name} has invited you to join {site.name} on Siloq as a {role}.\n\nAccept your invitation here (expires in 7 days):\n{invite_url}\n\n— The Siloq Team"
        }
        resend.Emails.send(params)
        logger.info(f"Team invite email sent via Resend: {email} to site {site.name} by {user.email}")
    except Exception as e:
        logger.error(f"Failed to send invite email to {email}: {e}")
        # Don't fail the whole request if email fails — invite is still created in DB
    
    return Response({
        'invite': {
            'id': invite.id,
            'email': invite.email,
            'role': invite.role,
            'site_id': site.id,
            'site_name': site.name,
            'token': token,  # Include token for now (remove in production)
            'expires_at': expires_at.isoformat(),
        },
        'message': 'Invitation sent successfully'
    }, status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def team_remove(request, access_id):
    """
    Remove a team member's access.
    
    DELETE /api/v1/team/{access_id}/
    Returns: { "message": "..." }
    """
    user = request.user
    
    try:
        # Find the access grant
        access = SiteAccess.objects.select_related('site').get(id=access_id)
        
        # Check if the requesting user owns the site
        if access.site.user != user:
            return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
        
        # Delete the access
        team_member_email = access.user.email
        site_name = access.site.name
        access.delete()
        
        logger.info(f"Team access removed: {team_member_email} from {site_name} by {user.email}")
        
        return Response({
            'message': f'Team member {team_member_email} removed successfully'
        })
    
    except SiteAccess.DoesNotExist:
        return Response({'error': 'Team member not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
def accept_invite(request):
    """
    Accept a team invitation via token.
    No auth required — the token IS the auth mechanism.

    POST /api/v1/team/invite/accept/
    Body: { "token": "..." }

    Returns:
      200 { "accepted": true, "site": {...}, "role": "..." }       — already-registered user, access granted
      202 { "action": "register", "email": "...", "token": "..." } — user needs to register first
      400/404 — invalid or expired token
    """
    token = request.data.get('token', '').strip()
    if not token:
        return Response({'error': 'Token is required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        invite = TeamInvite.objects.select_related('site', 'invited_by').get(token=token)
    except TeamInvite.DoesNotExist:
        return Response({'error': 'Invalid invitation link'}, status=status.HTTP_404_NOT_FOUND)

    if invite.status != 'pending':
        return Response({
            'error': 'This invitation has already been used or cancelled',
            'status': invite.status,
        }, status=status.HTTP_400_BAD_REQUEST)

    if invite.expires_at < timezone.now():
        invite.status = 'expired'
        invite.save(update_fields=['status'])
        return Response({'error': 'This invitation has expired'}, status=status.HTTP_400_BAD_REQUEST)

    # Check if the invited user has an account
    invited_user = User.objects.filter(email=invite.email).first()

    if not invited_user:
        # User needs to register — return enough info for frontend to handle signup
        return Response({
            'action': 'register',
            'email': invite.email,
            'token': token,
            'site_name': invite.site.name,
            'role': invite.role,
            'invited_by': f"{invite.invited_by.first_name} {invite.invited_by.last_name}".strip() or invite.invited_by.email,
        }, status=status.HTTP_202_ACCEPTED)

    # Check if already has access
    existing = SiteAccess.objects.filter(user=invited_user, site=invite.site).first()
    if existing:
        invite.status = 'accepted'
        invite.save(update_fields=['status'])
        return Response({
            'accepted': True,
            'already_had_access': True,
            'site': {'id': invite.site.id, 'name': invite.site.name, 'url': invite.site.url},
            'role': existing.role,
        })

    # Grant access
    SiteAccess.objects.create(user=invited_user, site=invite.site, role=invite.role)
    invite.status = 'accepted'
    invite.accepted_at = timezone.now()
    invite.save(update_fields=['status', 'accepted_at'])

    logger.info('Team invite accepted: %s → %s (role: %s)', invite.email, invite.site.name, invite.role)

    return Response({
        'accepted': True,
        'site': {'id': invite.site.id, 'name': invite.site.name, 'url': invite.site.url},
        'role': invite.role,
    })


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def update_member_role(request, access_id):
    """
    Update a team member's role.

    PATCH /api/v1/team/{access_id}/role/
    Body: { "role": "admin|editor|viewer" }
    Returns: { "id": ..., "role": "...", "email": "..." }
    """
    user = request.user
    new_role = request.data.get('role', '').strip()

    if new_role not in ['viewer', 'editor', 'admin']:
        return Response({'error': 'Invalid role. Must be viewer, editor, or admin'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        access = SiteAccess.objects.select_related('site', 'user').get(id=access_id)
    except SiteAccess.DoesNotExist:
        return Response({'error': 'Team member not found'}, status=status.HTTP_404_NOT_FOUND)

    if access.site.user != user:
        return Response({'error': 'Access denied — you do not own this site'}, status=status.HTTP_403_FORBIDDEN)

    old_role = access.role
    access.role = new_role
    access.save(update_fields=['role'])

    logger.info('Team role updated: %s on %s: %s → %s by %s', access.user.email, access.site.name, old_role, new_role, user.email)

    return Response({
        'id': access.id,
        'user_id': access.user.id,
        'email': access.user.email,
        'name': f"{access.user.first_name} {access.user.last_name}".strip() or access.user.email,
        'role': access.role,
        'site_id': access.site.id,
        'site_name': access.site.name,
    })


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def team_cancel_invite(request, invite_id):
    """
    Cancel a pending invitation.
    
    DELETE /api/v1/team/invite/{invite_id}/
    Returns: { "message": "..." }
    """
    user = request.user
    
    try:
        invite = TeamInvite.objects.get(id=invite_id, invited_by=user)
        
        if invite.status != 'pending':
            return Response({'error': 'Only pending invitations can be cancelled'}, status=status.HTTP_400_BAD_REQUEST)
        
        invite.status = 'declined'
        invite.save()
        
        return Response({
            'message': 'Invitation cancelled successfully'
        })
    
    except TeamInvite.DoesNotExist:
        return Response({'error': 'Invitation not found'}, status=status.HTTP_404_NOT_FOUND)
