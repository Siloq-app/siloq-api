"""
URL routing for accounts app.
"""
from django.urls import path
from django.views.decorators.csrf import csrf_exempt

# Lazy view imports to avoid AppRegistryNotReady
@csrf_exempt
def login_view(request):
    from .auth import login
    return login(request)

@csrf_exempt
def register_view(request):
    from .auth import register
    return register(request)

@csrf_exempt
def logout_view(request):
    from .auth import logout
    return logout(request)

@csrf_exempt
def me_view(request):
    from .auth import me
    return me(request)

@csrf_exempt
def google_login_view(request):
    from .oauth import google_login
    return google_login(request)

@csrf_exempt
def google_callback_view(request):
    from .oauth import google_callback
    return google_callback(request)

@csrf_exempt
def verify_view(request):
    from .auth import verify
    return verify(request)

urlpatterns = [
    # Core authentication
    path('login/', login_view, name='login'),
    path('register/', register_view, name='register'),
    path('logout/', logout_view, name='logout'),
    path('me/', me_view, name='me'),
    # Google OAuth
    path('google/login/', google_login_view, name='google_login'),
    path('google/callback/', google_callback_view, name='google_callback'),
    # API Key verification (for WordPress plugin)
    path('verify/', verify_view, name='verify'),
]
