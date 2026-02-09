"""
URL routing for billing endpoints.
"""
from django.urls import path
from . import views

urlpatterns = [
    path('checkout/', views.create_checkout_session, name='create_checkout'),
    path('portal/', views.create_portal_session, name='customer_portal'),
    path('status/', views.get_subscription_status, name='subscription_status'),
    path('webhook/', views.stripe_webhook, name='stripe_webhook'),
]
