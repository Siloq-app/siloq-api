"""
Financial Preflight Guards for AI Execution.
These guards MUST pass before any AI model execution.

Error Codes (Financial Governance):
- AI_TRIAL_LIMIT_REACHED: Trial page limit hit
- AI_TRIAL_EXPIRED: 10-day trial period expired
- AI_PROVIDER_NOT_CONFIGURED: No AI mode set
- AI_API_KEY_MISSING: BYOK key missing
- AI_BYOK_INVALID: Provider rejected key
- AI_BILLING_DISABLED: No card on file (Siloq-Managed)
- AI_BILLING_PREAUTH_FAILED: Pre-authorization failed
- AI_CHARGE_FAILED: Capture failed (post-execution)
"""
from dataclasses import dataclass
from typing import Optional, Tuple
from decimal import Decimal
from django.utils import timezone


@dataclass
class PreflightResult:
    """Result of a preflight check."""
    allowed: bool
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    warning: Optional[str] = None
    
    # Cost estimation (if allowed)
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0
    estimated_provider_cost_usd: Decimal = Decimal('0')
    estimated_siloq_fee_usd: Decimal = Decimal('0')
    estimated_total_cost_usd: Decimal = Decimal('0')


class AIPreflightGuard:
    """
    Validates billing configuration before AI execution.
    
    Usage:
        guard = AIPreflightGuard(site)
        result = guard.check(estimated_tokens=1000, is_bulk=False)
        if not result.allowed:
            raise PreflightError(result.error_code, result.error_message)
    """
    
    # Cost per 1K tokens (approximate, varies by model)
    COST_PER_1K_INPUT = Decimal('0.003')   # ~$3/1M input tokens
    COST_PER_1K_OUTPUT = Decimal('0.015')  # ~$15/1M output tokens
    
    # Siloq fee for managed billing
    SILOQ_FEE_PERCENT = Decimal('0.05')  # 5%
    
    # Pre-auth threshold for bulk jobs
    PREAUTH_THRESHOLD_USD = Decimal('10.00')
    
    def __init__(self, site):
        self.site = site
        self._settings = None
    
    @property
    def settings(self):
        """Lazy load AI settings."""
        if self._settings is None:
            from billing.models import ProjectAISettings
            self._settings, _ = ProjectAISettings.objects.get_or_create(
                site=self.site,
                defaults={'mode': 'trial'}
            )
            # Start trial if new
            if not self._settings.trial_start_date:
                self._settings.start_trial()
        return self._settings
    
    def check(
        self,
        estimated_input_tokens: int = 0,
        estimated_output_tokens: int = 0,
        is_bulk: bool = False
    ) -> PreflightResult:
        """
        Run all preflight checks.
        
        Args:
            estimated_input_tokens: Expected input tokens
            estimated_output_tokens: Expected output tokens
            is_bulk: Whether this is a bulk job requiring pre-auth
            
        Returns:
            PreflightResult with allowed status and cost estimates
        """
        mode = self.settings.mode
        
        # === TRIAL MODE CHECKS ===
        if mode == 'trial':
            return self._check_trial(estimated_input_tokens, estimated_output_tokens)
        
        # === BYOK MODE CHECKS ===
        if mode == 'byok':
            return self._check_byok(estimated_input_tokens, estimated_output_tokens)
        
        # === SILOQ-MANAGED MODE CHECKS ===
        if mode == 'siloq_managed':
            return self._check_siloq_managed(
                estimated_input_tokens, 
                estimated_output_tokens,
                is_bulk
            )
        
        # Unknown mode
        return PreflightResult(
            allowed=False,
            error_code='AI_PROVIDER_NOT_CONFIGURED',
            error_message='AI billing mode not configured. Please set up billing in Settings.'
        )
    
    def _check_trial(
        self, 
        input_tokens: int, 
        output_tokens: int
    ) -> PreflightResult:
        """Check trial mode constraints."""
        
        # Check if trial expired
        if self.settings.trial_end_date and timezone.now() > self.settings.trial_end_date:
            return PreflightResult(
                allowed=False,
                error_code='AI_TRIAL_EXPIRED',
                error_message=(
                    '10-day trial expired. '
                    'Upgrade to Pro ($199/mo) or Builder ($399/mo) to continue generating content.'
                )
            )
        
        # Check if page limit reached
        if self.settings.is_trial_exhausted:
            return PreflightResult(
                allowed=False,
                error_code='AI_TRIAL_LIMIT_REACHED',
                error_message=(
                    f'Trial limit reached ({self.settings.trial_pages_used}/{self.settings.trial_pages_limit} pages). '
                    'Upgrade to Pro ($199/mo) or Builder ($399/mo) to continue.'
                )
            )
        
        # Trial is valid - calculate costs (Siloq absorbs)
        cost = self._estimate_cost(input_tokens, output_tokens, include_fee=False)
        
        return PreflightResult(
            allowed=True,
            estimated_input_tokens=input_tokens,
            estimated_output_tokens=output_tokens,
            estimated_provider_cost_usd=cost,
            estimated_siloq_fee_usd=Decimal('0'),
            estimated_total_cost_usd=Decimal('0'),  # Free for trial
            warning=f'Trial: {self.settings.trial_pages_remaining - 1} pages remaining after this generation'
        )
    
    def _check_byok(
        self, 
        input_tokens: int, 
        output_tokens: int
    ) -> PreflightResult:
        """Check BYOK mode constraints."""
        
        # Check if API key is configured
        if not self.settings.api_key_encrypted:
            return PreflightResult(
                allowed=False,
                error_code='AI_API_KEY_MISSING',
                error_message=(
                    'No API key configured. '
                    'Add your OpenAI or Gemini API key in Settings → AI Billing.'
                )
            )
        
        # BYOK is valid - calculate costs (user pays provider directly)
        cost = self._estimate_cost(input_tokens, output_tokens, include_fee=False)
        
        return PreflightResult(
            allowed=True,
            estimated_input_tokens=input_tokens,
            estimated_output_tokens=output_tokens,
            estimated_provider_cost_usd=cost,
            estimated_siloq_fee_usd=Decimal('0'),
            estimated_total_cost_usd=cost,
        )
    
    def _check_siloq_managed(
        self, 
        input_tokens: int, 
        output_tokens: int,
        is_bulk: bool
    ) -> PreflightResult:
        """Check Siloq-Managed billing constraints."""
        
        # Check if Stripe customer exists
        if not self.settings.stripe_customer_id:
            return PreflightResult(
                allowed=False,
                error_code='AI_BILLING_DISABLED',
                error_message=(
                    'No payment method on file. '
                    'Add a card in Settings → Billing to use Siloq-Managed AI billing.'
                )
            )
        
        # Check if billing is enabled
        if not self.settings.billing_enabled:
            return PreflightResult(
                allowed=False,
                error_code='AI_BILLING_DISABLED',
                error_message='Billing is disabled. Please verify your payment method.'
            )
        
        # Calculate costs with Siloq fee
        provider_cost = self._estimate_cost(input_tokens, output_tokens, include_fee=False)
        siloq_fee = provider_cost * self.SILOQ_FEE_PERCENT
        total_cost = provider_cost + siloq_fee
        
        # Check if bulk job needs pre-auth
        if is_bulk and total_cost > self.PREAUTH_THRESHOLD_USD:
            # In real implementation, this would create a Stripe PaymentIntent
            # For now, we just flag it
            return PreflightResult(
                allowed=True,  # Would be False until pre-auth confirmed
                warning=f'Bulk job requires pre-authorization for ${total_cost:.2f}',
                estimated_input_tokens=input_tokens,
                estimated_output_tokens=output_tokens,
                estimated_provider_cost_usd=provider_cost,
                estimated_siloq_fee_usd=siloq_fee,
                estimated_total_cost_usd=total_cost,
            )
        
        return PreflightResult(
            allowed=True,
            estimated_input_tokens=input_tokens,
            estimated_output_tokens=output_tokens,
            estimated_provider_cost_usd=provider_cost,
            estimated_siloq_fee_usd=siloq_fee,
            estimated_total_cost_usd=total_cost,
        )
    
    def _estimate_cost(
        self, 
        input_tokens: int, 
        output_tokens: int,
        include_fee: bool = True
    ) -> Decimal:
        """Estimate cost based on token counts."""
        input_cost = (Decimal(input_tokens) / 1000) * self.COST_PER_1K_INPUT
        output_cost = (Decimal(output_tokens) / 1000) * self.COST_PER_1K_OUTPUT
        provider_cost = input_cost + output_cost
        
        if include_fee:
            return provider_cost * (1 + self.SILOQ_FEE_PERCENT)
        return provider_cost


class PreflightError(Exception):
    """Raised when preflight check fails."""
    
    def __init__(self, error_code: str, message: str):
        self.error_code = error_code
        self.message = message
        super().__init__(f"{error_code}: {message}")


# Convenience function for views
def check_ai_preflight(site, estimated_tokens: int = 1000, is_bulk: bool = False) -> PreflightResult:
    """
    Quick preflight check for a site.
    
    Usage in views:
        result = check_ai_preflight(site, estimated_tokens=2000)
        if not result.allowed:
            return Response({'error': result.error_code, 'message': result.error_message}, status=402)
    """
    guard = AIPreflightGuard(site)
    # Estimate 70/30 split for input/output tokens
    input_tokens = int(estimated_tokens * 0.7)
    output_tokens = int(estimated_tokens * 0.3)
    return guard.check(input_tokens, output_tokens, is_bulk)
