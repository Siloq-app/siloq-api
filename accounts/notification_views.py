"""
Notification preferences API.

GET  /api/v1/auth/notifications/  — get current preferences
PATCH /api/v1/auth/notifications/ — update preferences
"""
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import UserNotificationPreferences, DEFAULT_EMAIL_PREFS, DEFAULT_APP_PREFS


def _get_prefs(user):
    prefs, _ = UserNotificationPreferences.objects.get_or_create(
        user=user,
        defaults={
            'email_preferences': dict(DEFAULT_EMAIL_PREFS),
            'app_preferences': dict(DEFAULT_APP_PREFS),
        },
    )
    return prefs


def _merged_email(prefs):
    out = dict(DEFAULT_EMAIL_PREFS)
    out.update(prefs.email_preferences or {})
    return out


def _merged_app(prefs):
    out = dict(DEFAULT_APP_PREFS)
    out.update(prefs.app_preferences or {})
    return out


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def notification_preferences(request):
    if request.method == 'GET':
        prefs = _get_prefs(request.user)
        return Response({
            'email_preferences': _merged_email(prefs),
            'app_preferences': _merged_app(prefs),
        })

    # PATCH
    data = request.data
    prefs = _get_prefs(request.user)

    if 'email_preferences' in data and isinstance(data['email_preferences'], dict):
        prefs.email_preferences = {**_merged_email(prefs), **data['email_preferences']}
    if 'app_preferences' in data and isinstance(data['app_preferences'], dict):
        prefs.app_preferences = {**_merged_app(prefs), **data['app_preferences']}

    prefs.save()
    return Response({
        'email_preferences': _merged_email(prefs),
        'app_preferences': _merged_app(prefs),
    }, status=status.HTTP_200_OK)
