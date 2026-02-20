"""
DALL-E 3 image generation for content pipeline.

Generates professional featured images for blog/supporting content.
Cost: $0.080 per image (DALL-E 3, standard quality, 1792x1024).
"""
import logging
import os
import re

logger = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    slug = text.lower().strip()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s-]+', '-', slug)
    return slug.strip('-')[:80]


def generate_content_image(
    topic: str,
    business_name: str,
    content_type: str = 'supporting_article',
) -> dict:
    """
    Generate a featured image for content using DALL-E 3.

    Returns dict with:
        success (bool), image_url (str), alt_text (str),
        caption (str), seo_filename (str)
    """
    fail = {
        'success': False,
        'image_url': '',
        'alt_text': '',
        'caption': '',
        'seo_filename': '',
    }

    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        logger.warning("OPENAI_API_KEY not set — skipping image generation")
        return fail

    prompt = (
        f"Professional, high-quality photograph for a business website article "
        f"about {topic}. Clean, modern style suitable for {business_name}. "
        f"No text overlays, no watermarks, no logos."
    )

    try:
        import openai
        client = openai.OpenAI(api_key=api_key)

        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1792x1024",
            quality="standard",
            n=1,
        )

        image_url = response.data[0].url
        slug = _slugify(topic)

        return {
            'success': True,
            'image_url': image_url,
            'alt_text': f"Professional {topic}",
            'caption': f"{topic} — {business_name}",
            'seo_filename': f"{slug}.png",
        }

    except Exception as e:
        logger.error(f"DALL-E image generation failed: {e}")
        return fail
