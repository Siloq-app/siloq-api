"""
Content Generation Engine using OpenAI API.

Generates supporting page content for target/money pages.
Supports: Supporting articles, FAQ pages, How-to guides, Comparison pages.
"""
import os
import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')


def generate_supporting_content(
    target_page_title: str,
    target_page_url: str,
    content_type: str = 'supporting_article',
    topic: str = '',
    business_name: str = '',
    business_type: str = '',
    service_areas: list = None,
) -> Dict[str, Any]:
    """
    Generate a supporting page draft using OpenAI.
    
    Args:
        target_page_title: The money/target page this supports
        target_page_url: URL of the target page
        content_type: Type of content (supporting_article, faq, how_to, comparison)
        topic: Specific topic for the supporting page
        business_name: Business name for entity grounding
        business_type: Type of business (local, ecommerce, saas)
        service_areas: List of service areas for local businesses
    
    Returns:
        Dict with title, content, meta_description, internal_links
    """
    if not OPENAI_API_KEY:
        return {
            'success': False,
            'error': 'OpenAI API key not configured. Set OPENAI_API_KEY in environment.',
        }
    
    try:
        import openai
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
    except ImportError:
        return {
            'success': False,
            'error': 'OpenAI package not installed. Add openai to requirements.txt.',
        }
    
    # Build the prompt based on content type
    system_prompt = _build_system_prompt(business_name, business_type)
    user_prompt = _build_user_prompt(
        target_page_title=target_page_title,
        target_page_url=target_page_url,
        content_type=content_type,
        topic=topic,
        business_name=business_name,
        service_areas=service_areas or [],
    )
    
    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=3000,
            response_format={"type": "json_object"},
        )
        
        result = json.loads(response.choices[0].message.content)
        layers = result.get('layers', [])
        # Build full content from layers (geo + seo + cro) for backward compatibility
        if layers:
            content = ''.join(
                block.get('content', '')
                for block in layers
                if isinstance(block, dict) and block.get('content')
            )
        else:
            content = result.get('content', '')
        
        return {
            'success': True,
            'title': result.get('title', ''),
            'content': content,
            'meta_description': result.get('meta_description', ''),
            'suggested_slug': result.get('slug', ''),
            'internal_links': result.get('internal_links', []),
            'headings': result.get('headings', []),
            'layers': layers,  # each item: {"layer": "geo"|"seo"|"cro", "content": "<html>"}
            'word_count': len(content.split()),
            'model_used': OPENAI_MODEL,
            'tokens_used': response.usage.total_tokens if response.usage else 0,
        }
        
    except Exception as e:
        logger.error(f"Content generation failed: {e}")
        return {
            'success': False,
            'error': str(e),
        }


def _build_system_prompt(business_name: str, business_type: str) -> str:
    """Build system prompt for content generation. Output must include all 3 layers (GEO, SEO, CRO)."""
    return f"""You are an expert SEO content writer specializing in the Reverse Silo architecture and the Three-Layer content model (GEO, SEO, CRO).

Your job is to write supporting pages that:
1. Link UP to their target/money page naturally
2. Are self-contained and extractable by AI engines (GEO-optimized)
3. Use the business name ("{business_name}") in the first paragraph for entity grounding
4. Include question-format H2 headings for AI query matching

You MUST output content in three distinct layers. Each layer is a separate block with a "layer" field and "content" (HTML) field:

**Layer 1 — GEO (Answer Capsule):**
- "layer": "geo"
- "content": A single 40–80 word Answer Capsule in HTML (e.g. one <p>). Dense, specific, data-rich. Written so AI/search can extract it as a direct answer. Must mention "{business_name}" and the page topic. No fluff.

**Layer 2 — SEO (Body):**
- "layer": "seo"
- "content": The main body in HTML. Multiple paragraphs, H2s (use question format where possible), internal links (anchor_text + target_url), lists/tables as needed. Self-contained; no "as mentioned above." Optimized for relevance and crawlability.

**Layer 3 — CRO (Conversion section):**
- "layer": "cro"
- "content": The closing conversion block in HTML. Clear CTA, next steps, or "what to do next" that directs the reader to the target/money page. One or two short paragraphs plus a prominent CTA (e.g. link or button).

Business: {business_name}
Business Type: {business_type}

Output valid JSON with these keys:
- title (string)
- slug (string)
- meta_description (string)
- internal_links (array of {{anchor_text, target_url}})
- headings (array of H2 text strings)
- layers (array of exactly 3 objects, each with "layer" and "content"):
  - {{"layer": "geo", "content": "<p>...</p>"}}
  - {{"layer": "seo", "content": "<p>...</h2>...</p>..."}}
  - {{"layer": "cro", "content": "<p>...</p>"}}

Order of layers must be geo, then seo, then cro. The full page content is the concatenation of the three layer contents."""


def _build_user_prompt(
    target_page_title: str,
    target_page_url: str,
    content_type: str,
    topic: str,
    business_name: str,
    service_areas: list,
) -> str:
    """Build user prompt based on content type."""
    
    areas_str = ', '.join(service_areas[:5]) if service_areas else 'the local area'
    
    type_instructions = {
        'supporting_article': f"""Write a supporting article about "{topic}" that links to the target page "{target_page_title}" ({target_page_url}).
The article should:
- Be 800-1200 words
- Include 4-6 H2 headings in question format
- Naturally mention and link to the target page 2-3 times
- Include specific data points, statistics, or examples
- End with a CTA directing to the target page""",

        'faq': f"""Write an FAQ page about "{topic}" that supports the target page "{target_page_title}" ({target_page_url}).
Include:
- 8-12 frequently asked questions
- Each answer should be 50-100 words (extractable by AI)
- 2-3 answers should naturally link to the target page
- Questions should match real search queries people ask""",

        'how_to': f"""Write a how-to guide about "{topic}" that supports the target page "{target_page_title}" ({target_page_url}).
Include:
- Step-by-step instructions (5-8 steps)
- Each step as an H2 heading
- Practical, actionable advice
- Link to the target page for the main product/service
- Include a "What You'll Need" section and estimated time""",

        'comparison': f"""Write a comparison page about "{topic}" that supports the target page "{target_page_title}" ({target_page_url}).
Include:
- Comparison of 3-5 options
- Pros and cons for each
- Clear recommendation pointing to the target page's offering
- A comparison table (in HTML)
- 800-1200 words""",
    }
    
    instruction = type_instructions.get(content_type, type_instructions['supporting_article'])
    
    return f"""{instruction}

Business: {business_name}
Service Areas: {areas_str}

Remember:
- Use "{business_name}" in the first paragraph
- Lead with an Answer Capsule (40-80 words, specific data)
- H2 headings as questions when possible
- Each paragraph should be self-contained (no "as mentioned above")
- Include schema-friendly structured data where appropriate"""
