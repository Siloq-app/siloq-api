"""
URL routing for billing app.
These are nested under /sites/{site_id}/billing/
"""
from django.urls import path
from .views import BillingViewSet

billing_viewset = BillingViewSet.as_view({
    'get': 'settings',
    'put': 'settings',
})

urlpatterns = [
    path('settings/', billing_viewset, name='billing-settings'),
    path('usage/', BillingViewSet.as_view({'get': 'usage'}), name='billing-usage'),
    path('estimate/', BillingViewSet.as_view({'post': 'estimate'}), name='billing-estimate'),
    path('increment-trial/', BillingViewSet.as_view({'post': 'increment_trial'}), name='billing-increment-trial'),
]
