"""
User account models.
"""
import secrets
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom User model extending Django's AbstractUser.
    Used for dashboard user authentication.
    """
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Subscription fields (columns exist in DB)
    subscription_tier = models.CharField(max_length=50, default='free', blank=True)
    subscription_status = models.CharField(max_length=50, default='free', blank=True)
    stripe_subscription_id = models.CharField(max_length=255, null=True, blank=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    class Meta:
        db_table = 'users'
        ordering = ['-created_at']

    def __str__(self):
        return self.email


class TeamInvite(models.Model):
    """
    Team member invitations.
    Allows users to invite others to access their sites.
    """
    ROLE_CHOICES = [
        ('viewer', 'Viewer'),
        ('editor', 'Editor'),
        ('admin', 'Admin'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('declined', 'Declined'),
        ('expired', 'Expired'),
    ]
    
    email = models.EmailField(db_index=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='viewer')
    invited_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='sent_invites'
    )
    site = models.ForeignKey(
        'sites.Site',
        on_delete=models.CASCADE,
        related_name='team_invites'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    token = models.CharField(max_length=64, unique=True, db_index=True)
    invited_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='received_invites',
        help_text="Set when invite is accepted"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(
        help_text="Invite expiration date (7 days from creation)"
    )
    
    class Meta:
        db_table = 'team_invites'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['email', 'status']),
            models.Index(fields=['site', 'status']),
        ]
    
    def __str__(self):
        return f"{self.email} invited to {self.site.name} ({self.status})"
    
    @classmethod
    def generate_token(cls):
        """Generate a secure random token for invite."""
        return secrets.token_urlsafe(32)


class SiteAccess(models.Model):
    """
    Tracks which users have access to which sites.
    Created when a team invite is accepted.
    """
    ROLE_CHOICES = TeamInvite.ROLE_CHOICES
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='site_access'
    )
    site = models.ForeignKey(
        'sites.Site',
        on_delete=models.CASCADE,
        related_name='access_grants'
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='viewer')
    granted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='granted_access'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'site_access'
        unique_together = ['user', 'site']
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.email} has {self.role} access to {self.site.name}"
