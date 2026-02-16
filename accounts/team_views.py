"""
Team management views.
Handles team member invitations and access control.
"""
import logging
from datetime import timedelta
from django.utils import timezone
from django.db.models import Q
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
    tier = user.subscription_status or 'free'
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
    
    if not site_id:
        return Response({'error': 'Site ID is required'}, status=status.HTTP_400_BAD_REQUEST)
    
    # Check if site exists and user owns it
    try:
        site = Site.objects.get(id=site_id, user=user)
    except Site.DoesNotExist:
        return Response({'error': 'Site not found or access denied'}, status=status.HTTP_404_NOT_FOUND)
    
    # Check subscription limits
    tier = user.subscription_status or 'free'
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
    
    # TODO: Send email notification (implement later)
    logger.info(f"Team invite created: {email} to site {site.name} by {user.email}")
    
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
