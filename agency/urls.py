from django.urls import path
from agency import views

urlpatterns = [
    # Agency profile + branding
    path('profile/',                    views.agency_profile,       name='agency-profile'),

    # Client management
    path('clients/',                    views.client_list,          name='agency-clients'),
    path('clients/invite/',             views.client_invite,        name='agency-client-invite'),
    path('clients/accept-invite/',      views.client_accept_invite, name='agency-accept-invite'),
    path('clients/<int:client_id>/',    views.client_remove,        name='agency-client-remove'),
    path('clients/<int:client_id>/sites/', views.client_sites,     name='agency-client-sites'),

    # Context switching (Agency Pro)
    path('switch-context/<int:client_id>/', views.switch_context,  name='agency-switch-context'),
]
