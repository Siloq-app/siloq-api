from django.urls import path
from agency import views

urlpatterns = [
    # Profile
    path('profile/',                                views.agency_profile,            name='agency-profile'),

    # Site management
    path('sites/',                                  views.agency_sites,              name='agency-sites'),
    path('sites/<int:site_id>/',                    views.agency_site_remove,        name='agency-site-remove'),
    path('sites/<int:site_id>/assign-client/',      views.agency_site_assign_client, name='agency-site-assign-client'),

    # Client users
    path('clients/',                                views.client_list,               name='agency-clients'),
    path('clients/invite/',                         views.client_invite,             name='agency-client-invite'),
    path('clients/<int:user_id>/',                  views.client_remove,             name='agency-client-remove'),

    # Context switching (Agency Pro)
    path('switch-context/<int:user_id>/',           views.switch_context,            name='agency-switch-context'),
]
