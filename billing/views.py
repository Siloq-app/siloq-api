"""
Billing and subscription views with Stripe integration.
Handles checkout, customer portal, and webhooks.
"""
import stripe
from django.conf import settings
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import Subscription, Payment
from .serializers import (
    SubscriptionSerializer,
    PaymentSerializer,
    CheckoutSessionSerializer,
    PortalSessionSerializer
)

# Initialize Stripe with API key
stripe.api_key = getattr(settings, 'STRIPE_SECRET_KEY', '')

# Price IDs for each tier (should match your Stripe dashboard)
STRIPE_PRICE_IDS = {
    'pro': getattr(settings, 'STRIPE_PRICE_PRO', ''),
    'builder_plus': getattr(settings, 'STRIPE_PRICE_BUILDER_PLUS', ''),
    'architect': getattr(settings, 'STRIPE_PRICE_ARCHITECT', ''),
    'empire': getattr(settings, 'STRIPE_PRICE_EMPIRE', ''),
}


class SubscriptionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing user subscriptions.
    """
    serializer_class = SubscriptionSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Return the current user's subscription."""
        return Subscription.objects.filter(user=self.request.user)
    
    @action(detail=False, methods=['get'])
    def current(self, request):
        """Get or create the current user's subscription."""
        subscription, created = Subscription.objects.get_or_create(
            user=request.user,
            defaults={
                'tier': 'free_trial',
                'status': 'trialing',
                'trial_started_at': timezone.now(),
                'trial_ends_at': timezone.now() + timezone.timedelta(days=10),
                'trial_pages_limit': 10,
                'trial_pages_used': 0,
            }
        )
        serializer = self.get_serializer(subscription)
        return Response(serializer.data)


class CheckoutViewSet(viewsets.ViewSet):
    """
    ViewSet for creating Stripe checkout sessions.
    """
    permission_classes = [IsAuthenticated]
    
    @action(detail=False, methods=['post'])
    def create_session(self, request):
        """Create a Stripe checkout session for subscription."""
        serializer = CheckoutSessionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        tier = serializer.validated_data['tier']
        success_url = serializer.validated_data['success_url']
        cancel_url = serializer.validated_data['cancel_url']
        
        price_id = STRIPE_PRICE_IDS.get(tier)
        if not price_id:
            return Response(
                {'error': f'Invalid tier: {tier}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Get or create Stripe customer
            subscription, _ = Subscription.objects.get_or_create(
                user=request.user,
                defaults={
                    'tier': 'free_trial',
                    'status': 'trialing',
                }
            )
            
            if not subscription.stripe_customer_id:
                customer = stripe.Customer.create(
                    email=request.user.email,
                    name=request.user.get_full_name() or request.user.username,
                )
                subscription.stripe_customer_id = customer.id
                subscription.save()
            
            # Create checkout session
            session = stripe.checkout.Session.create(
                customer=subscription.stripe_customer_id,
                payment_method_types=['card'],
                line_items=[{
                    'price': price_id,
                    'quantity': 1,
                }],
                mode='subscription',
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    'user_id': request.user.id,
                    'tier': tier,
                },
            )
            
            return Response({
                'session_id': session.id,
                'url': session.url,
            })
            
        except stripe.error.StripeError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class CustomerPortalViewSet(viewsets.ViewSet):
    """
    ViewSet for Stripe customer portal.
    """
    permission_classes = [IsAuthenticated]
    
    @action(detail=False, methods=['post'])
    def create_session(self, request):
        """Create a Stripe customer portal session."""
        serializer = PortalSessionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        return_url = serializer.validated_data['return_url']
        
        try:
            subscription = Subscription.objects.get(user=request.user)
            
            if not subscription.stripe_customer_id:
                return Response(
                    {'error': 'No Stripe customer found. Please subscribe first.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            session = stripe.billing_portal.Session.create(
                customer=subscription.stripe_customer_id,
                return_url=return_url,
            )
            
            return Response({'url': session.url})
            
        except Subscription.DoesNotExist:
            return Response(
                {'error': 'No subscription found.'},
                status=status.HTTP_404_NOT_FOUND
            )
        except stripe.error.StripeError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


@api_view(['POST'])
@permission_classes([])  # Webhook doesn't use standard auth
def stripe_webhook(request):
    """
    Handle Stripe webhooks for subscription events.
    """
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    webhook_secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', '')
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
    except ValueError:
        return Response({'error': 'Invalid payload'}, status=status.HTTP_400_BAD_REQUEST)
    except stripe.error.SignatureVerificationError:
        return Response({'error': 'Invalid signature'}, status=status.HTTP_400_BAD_REQUEST)
    
    # Handle the event
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        _handle_checkout_completed(session)
    
    elif event['type'] == 'invoice.payment_succeeded':
        invoice = event['data']['object']
        _handle_payment_succeeded(invoice)
    
    elif event['type'] == 'invoice.payment_failed':
        invoice = event['data']['object']
        _handle_payment_failed(invoice)
    
    elif event['type'] == 'customer.subscription.deleted':
        subscription = event['data']['object']
        _handle_subscription_canceled(subscription)
    
    return Response({'status': 'success'})


def _handle_checkout_completed(session):
    """Handle checkout.session.completed event."""
    user_id = session.get('metadata', {}).get('user_id')
    tier = session.get('metadata', {}).get('tier')
    
    if not user_id:
        return
    
    try:
        from django.contrib.auth.models import User
        user = User.objects.get(id=user_id)
        subscription, _ = Subscription.objects.get_or_create(user=user)
        
        subscription.stripe_subscription_id = session.get('subscription')
        subscription.tier = tier
        subscription.status = 'active'
        subscription.save()
        
    except User.DoesNotExist:
        pass


def _handle_payment_succeeded(invoice):
    """Handle invoice.payment_succeeded event."""
    customer_id = invoice.get('customer')
    
    try:
        subscription = Subscription.objects.get(stripe_customer_id=customer_id)
        subscription.status = 'active'
        subscription.current_period_start = timezone.datetime.fromtimestamp(
            invoice.get('period_start'), tz=timezone.utc
        )
        subscription.current_period_end = timezone.datetime.fromtimestamp(
            invoice.get('period_end'), tz=timezone.utc
        )
        subscription.save()
        
        # Record the payment
        Payment.objects.create(
            user=subscription.user,
            stripe_payment_intent_id=invoice.get('payment_intent', ''),
            stripe_invoice_id=invoice.get('id'),
            amount=invoice.get('amount_paid', 0) / 100,  # Convert from cents
            currency=invoice.get('currency', 'usd'),
            status='succeeded',
        )
    except Subscription.DoesNotExist:
        pass


def _handle_payment_failed(invoice):
    """Handle invoice.payment_failed event."""
    customer_id = invoice.get('customer')
    
    try:
        subscription = Subscription.objects.get(stripe_customer_id=customer_id)
        subscription.status = 'past_due'
        subscription.save()
    except Subscription.DoesNotExist:
        pass


def _handle_subscription_canceled(stripe_subscription):
    """Handle customer.subscription.deleted event."""
    subscription_id = stripe_subscription.get('id')
    
    try:
        subscription = Subscription.objects.get(stripe_subscription_id=subscription_id)
        subscription.status = 'canceled'
        subscription.save()
    except Subscription.DoesNotExist:
        pass
