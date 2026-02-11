"""
URL configuration for billing app.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'subscription', views.SubscriptionViewSet, basename='subscription')
router.register(r'checkout', views.CheckoutViewSet, basename='checkout')
router.register(r'portal', views.CustomerPortalViewSet, basename='portal')

urlpatterns = [
    path('', include(router.urls)),
    path('webhook/', views.stripe_webhook, name='stripe-webhook'),
]
