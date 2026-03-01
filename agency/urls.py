from django.urls import path
from . import views

urlpatterns = [
    # Branding
    path('branding/', views.branding, name='agency-branding'),
    path('branding/context/', views.branding_context, name='agency-branding-context'),
    # Clients
    path('clients/', views.client_list, name='agency-client-list'),
    path('clients/invite/', views.client_invite, name='agency-client-invite'),
    path('clients/accept-invite/', views.client_accept_invite, name='agency-client-accept-invite'),
    path('clients/<int:client_id>/', views.client_remove, name='agency-client-remove'),
]
