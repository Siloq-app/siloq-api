"""
Validation for AI-generated plan responses.
"""


class ValidationError(Exception):
    pass


def validate_response(action: str, data: dict) -> None:
    """Validate AI response based on action type. Raises ValidationError."""
    validators = {
        'merge_plan': _validate_merge_plan,
        'spoke_rewrite': _validate_spoke_rewrite,
        'merge_draft': _validate_draft,
        'spoke_draft': _validate_draft,
    }
    validator = validators.get(action)
    if validator:
        validator(data)


def _validate_merge_plan(data: dict) -> None:
    required = ['hub_url', 'new_title', 'h2_structure', 'content_actions',
                 'redirects', 'projected_impact']
    for field in required:
        if not data.get(field):
            raise ValidationError(f"Missing required field: {field}")

    if not isinstance(data['h2_structure'], list) or len(data['h2_structure']) < 3:
        raise ValidationError("Merge plan needs at least 3 H2 sections")


def _validate_spoke_rewrite(data: dict) -> None:
    if not data.get('hub') or not data['hub'].get('url'):
        raise ValidationError("Missing required field: hub.url")

    spokes = data.get('spokes')
    if not isinstance(spokes, list) or len(spokes) < 1:
        raise ValidationError("Spoke rewrite needs at least 1 spoke entry")


def _validate_draft(data: dict) -> None:
    # Drafts return HTML content; minimal validation
    pass
