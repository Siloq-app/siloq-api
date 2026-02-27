"""
Business Profile validation helpers.

Returns missing required/recommended fields and which features are blocked,
so the API and dashboard can show clear "complete your profile" warnings
instead of generating broken placeholder outputs.
"""


def get_profile_completeness(profile, site=None):
    """
    Assess how complete a SiteEntityProfile is.

    Returns:
        {
          'missing_required':    [field_name, ...]
          'missing_recommended': [field_name, ...]
          'blocked_features':    ['schema_generation', 'content_topic_generation', ...]
          'completion_pct':      int 0-100
          'banner_message':      str | None
          'schema_blocked':      bool
          'content_blocked':     bool
        }
    """
    missing_required = []
    missing_recommended = []
    blocked_features = []

    # ── Required fields ───────────────────────────────────────────────────────
    if not getattr(profile, 'business_name', None):
        missing_required.append('business_name')

    if not getattr(profile, 'phone', None):
        missing_required.append('phone')

    if not getattr(profile, 'logo_url', None):
        missing_required.append('logo_url')

    # Address OR service area required (SABs hide their address — that's fine)
    has_address = bool(
        getattr(profile, 'street_address', None) and
        getattr(profile, 'city', None)
    )
    service_cities = getattr(profile, 'service_cities', None) or []
    service_zips = getattr(profile, 'service_zips', None) or []
    service_radius = getattr(profile, 'service_radius_miles', None)
    has_service_area = bool(service_cities or service_zips or service_radius)

    if not has_address and not has_service_area:
        missing_required.append('address_or_service_area')

    # ── Recommended fields ────────────────────────────────────────────────────
    brands_used = getattr(profile, 'brands_used', None) or []
    if not brands_used:
        missing_recommended.append('brands_used')

    categories = getattr(profile, 'categories', None) or []
    if not categories:
        missing_recommended.append('services_or_categories')

    has_social = any([
        getattr(profile, 'url_facebook', None),
        getattr(profile, 'url_instagram', None),
        getattr(profile, 'url_linkedin', None),
    ])
    if not has_social:
        missing_recommended.append('social_profiles')

    if not getattr(profile, 'url_yelp', None):
        missing_recommended.append('yelp_profile')

    team_members = getattr(profile, 'team_members', None) or []
    if not team_members:
        missing_recommended.append('team_members')

    # ── Feature blocking ──────────────────────────────────────────────────────

    # Schema generation: blocked if business_name, phone, logo_url, OR location missing
    schema_blocked = bool(
        'business_name' in missing_required or
        'phone' in missing_required or
        'logo_url' in missing_required or
        'address_or_service_area' in missing_required
    )
    if schema_blocked:
        blocked_features.append('schema_generation')

    # Content topic generation: blocked if no services AND no location
    content_blocked = bool(not categories and not has_service_area)
    if content_blocked:
        blocked_features.append('content_topic_generation')

    # About Us analysis: blocked if no business name
    if 'business_name' in missing_required:
        blocked_features.append('about_us_analysis')

    # CRO phone check: blocked if no phone
    if 'phone' in missing_required:
        blocked_features.append('cro_phone_check')

    # ── Completion percentage ─────────────────────────────────────────────────
    # 8 key fields: business_name, phone, logo_url, address/service_area,
    #               categories, social, yelp, team_members
    total_key_fields = 8
    missing_count = len(missing_required) + min(len(missing_recommended), 4)
    filled = max(0, total_key_fields - missing_count)
    completion_pct = min(100, int(filled / total_key_fields * 100))

    # ── Banner message ────────────────────────────────────────────────────────
    banner_message = None
    if missing_required:
        req_count = len(missing_required)
        feature_names = {
            'schema_generation': 'Schema generation',
            'content_topic_generation': 'Content topic generation',
            'about_us_analysis': 'About Us analysis',
            'cro_phone_check': 'CRO phone check',
        }
        blocked_labels = [feature_names.get(f, f) for f in blocked_features[:2]]
        features_str = ' and '.join(blocked_labels) if blocked_labels else 'Some features'
        banner_message = (
            f"Your Business Profile is incomplete — {req_count} required field(s) missing. "
            f"{features_str} {'is' if len(blocked_features) == 1 else 'are'} limited. "
            f"Go to Settings → Business Profile to complete it."
        )

    return {
        'missing_required':    missing_required,
        'missing_recommended': missing_recommended,
        'blocked_features':    blocked_features,
        'completion_pct':      completion_pct,
        'banner_message':      banner_message,
        'schema_blocked':      schema_blocked,
        'content_blocked':     content_blocked,
    }
