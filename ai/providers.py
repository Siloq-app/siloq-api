"""
AI provider integration — Claude (primary) with OpenAI fallback.
"""
import json
import logging
import os
import re

logger = logging.getLogger(__name__)

ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
OPENAI_MODEL = "gpt-4o"
TEMPERATURE = 0.3
MAX_TOKENS = 4000


def _clean_json(text: str) -> dict:
    """Strip markdown fences and parse JSON."""
    cleaned = re.sub(r'```(?:json)?\s*', '', text).strip()
    cleaned = cleaned.rstrip('`').strip()
    return json.loads(cleaned)


def _build_user_message(context_payload: dict, action: str) -> str:
    action_label = action.replace('_', ' ')
    return (
        f"<context>\n{json.dumps(context_payload, indent=2)}\n</context>\n\n"
        f"Analyze this cannibalization conflict and generate the {action_label}."
    )


def call_ai(system_prompt: str, context_payload: dict, action: str) -> dict:
    """
    Call AI provider. Try Claude first, fall back to OpenAI.
    Returns tuple: (parsed_response_dict, provider_name, model_name)
    """
    user_message = _build_user_message(context_payload, action)

    # Try Claude first
    anthropic_key = os.getenv('ANTHROPIC_API_KEY')
    if anthropic_key:
        try:
            return _call_claude(anthropic_key, system_prompt, user_message)
        except Exception as e:
            logger.warning(f"Claude call failed, falling back to OpenAI: {e}")

    # Fallback to OpenAI
    openai_key = os.getenv('OPENAI_API_KEY')
    if openai_key:
        try:
            return _call_openai(openai_key, system_prompt, user_message)
        except Exception as e:
            logger.error(f"OpenAI call also failed: {e}")
            raise

    raise RuntimeError("No AI provider configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY.")


def call_ai_with_retry(system_prompt: str, context_payload: dict, action: str,
                        validation_error: str = None) -> dict:
    """
    Call AI with optional retry on validation failure.
    If validation_error is provided, appends feedback to the prompt.
    """
    if validation_error:
        context_payload = {
            **context_payload,
            '_retry_feedback': (
                f"Your previous response was invalid: {validation_error}. "
                "Please regenerate with all required fields."
            )
        }
    return call_ai(system_prompt, context_payload, action)


def _call_claude(api_key: str, system_prompt: str, user_message: str) -> dict:
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    text = "".join(
        block.text for block in message.content if block.type == "text"
    )
    parsed = _clean_json(text)
    return (parsed, "claude", ANTHROPIC_MODEL)


def _call_openai(api_key: str, system_prompt: str, user_message: str) -> dict:
    import openai
    client = openai.OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )
    text = response.choices[0].message.content
    parsed = _clean_json(text)
    return (parsed, "openai", OPENAI_MODEL)
