import json
import anthropic
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from sites.models import Site
from seo.models import Page, SiteIntelligence


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_site_intelligence(request, site_id):
    """
    Generate AI-powered site intelligence for a given site.
    Calls Claude Sonnet with page inventory, returns structured analysis.
    Caches result in SiteIntelligence model.
    """
    try:
        site = Site.objects.get(id=site_id, user=request.user)
    except Site.DoesNotExist:
        return Response({'error': 'Site not found'}, status=404)

    pages = Page.objects.filter(site=site, status='publish').values(
        'id', 'title', 'url', 'yoast_title', 'yoast_description',
        'page_type_classification', 'post_type'
    )[:200]

    if not pages:
        return Response({'error': 'No synced pages found. Run Sync All first.'}, status=400)

    page_inventory = []
    for p in pages:
        page_inventory.append({
            'id': p['id'],
            'title': p['title'] or '(no title)',
            'url': p['url'],
            'meta_title': p['yoast_title'] or '',
            'meta_description': p['yoast_description'] or '',
            'page_type': p['page_type_classification'] or 'unknown',
            'post_type': p['post_type'] or 'page',
        })

    # Inject owner goals if set
    goals_context = ""
    try:
        goals = site.goals
        if goals.primary_goal:
            goal_labels = {
                'local_leads': 'Get more local leads / phone calls',
                'ecommerce_sales': 'Drive more e-commerce sales',
                'topic_authority': 'Build authority on a specific topic',
                'multi_location': 'Rank in multiple cities / expand service areas',
                'geo_citations': 'Be cited by AI assistants (ChatGPT, Perplexity, Google AI)',
                'organic_growth': 'Grow overall organic traffic',
            }
            goals_context = f"""
[OWNER GOALS — weight these heavily in your analysis]
Primary goal: {goal_labels.get(goals.primary_goal, goals.primary_goal)}
Priority services: {', '.join(goals.priority_services) if goals.priority_services else 'Not set'}
Priority locations: {', '.join([f"{l.get('city','')}, {l.get('state','')}" for l in goals.priority_locations]) if goals.priority_locations else 'Not set'}

When identifying architecture problems, prioritize issues affecting these services and locations.
When suggesting content gaps, focus on supporting these priorities first.
Label content gaps for non-priority areas as priority: low.
"""
    except Exception:
        pass  # No goals set — proceed without

    system_prompt = (
        "You are an expert SEO architect analyzing website structure for a platform called Siloq. "
        "You understand Hub & Spoke architecture, keyword cannibalization, local vs national SEO strategy, "
        "e-commerce category structure, and event/service business content architecture.\n"
        "Always respond with valid JSON only. No markdown, no explanation outside the JSON."
    )

    user_prompt = f"""Analyze this website and return a JSON object with the following structure.

Site URL: {site.url}
Business name: {site.name}
Total pages provided: {len(page_inventory)}
{goals_context}

Page inventory:
{json.dumps(page_inventory, indent=2)}

Return ONLY this JSON structure (no markdown):
{{
  "business_type": "one of: local_service, local_service_multi, ecommerce, event_venue, medical_practice, restaurant, content_publisher, general",
  "primary_goal": "one sentence describing what this site is trying to rank for",
  "hub_pages": [
    {{"page_id": 123, "title": "page title", "url": "/url/", "reason": "why this is a hub"}}
  ],
  "spoke_pages": [
    {{"page_id": 456, "title": "page title", "url": "/url/", "hub_page_id": 123}}
  ],
  "orphan_pages": [
    {{"page_id": 789, "title": "page title", "url": "/url/"}}
  ],
  "architecture_problems": [
    {{"severity": "high|medium|low", "description": "specific problem", "page_ids": [123, 456]}}
  ],
  "content_gaps": [
    {{"title": "suggested page title", "type": "hub|spoke|supporting", "priority": "high|medium|low", "parent_hub_id": 123}}
  ],
  "cannibalization_risks": [
    {{"page_id_1": 123, "page_id_2": 456, "competing_intent": "what keyword they both target"}}
  ]
}}"""

    api_key = getattr(settings, 'ANTHROPIC_API_KEY', None)
    if not api_key:
        return Response({'error': 'Anthropic API key not configured'}, status=500)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        )
        raw_response = message.content[0].text
        analysis = json.loads(raw_response)
    except json.JSONDecodeError as e:
        return Response({'error': f'Claude returned invalid JSON: {str(e)}'}, status=500)
    except Exception as e:
        return Response({'error': f'Claude API error: {str(e)}'}, status=500)

    intelligence, _ = SiteIntelligence.objects.update_or_create(
        site=site,
        defaults={
            'business_type': analysis.get('business_type', 'general'),
            'primary_goal': analysis.get('primary_goal', ''),
            'raw_analysis': analysis,
            'hub_pages': analysis.get('hub_pages', []),
            'spoke_pages': analysis.get('spoke_pages', []),
            'orphan_pages': analysis.get('orphan_pages', []),
            'architecture_problems': analysis.get('architecture_problems', []),
            'content_gaps': analysis.get('content_gaps', []),
            'cannibalization_risks': analysis.get('cannibalization_risks', []),
            'generation_error': '',
        }
    )

    return Response({
        'success': True,
        'business_type': intelligence.business_type,
        'primary_goal': intelligence.primary_goal,
        'hub_count': len(intelligence.hub_pages),
        'spoke_count': len(intelligence.spoke_pages),
        'orphan_count': len(intelligence.orphan_pages),
        'problem_count': len(intelligence.architecture_problems),
        'gap_count': len(intelligence.content_gaps),
        'cannibalization_count': len(intelligence.cannibalization_risks),
        'generated_at': intelligence.generated_at.isoformat(),
        'intelligence': {
            'business_type': intelligence.business_type,
            'primary_goal': intelligence.primary_goal,
            'hub_pages': intelligence.hub_pages,
            'spoke_pages': intelligence.spoke_pages,
            'orphan_pages': intelligence.orphan_pages,
            'architecture_problems': intelligence.architecture_problems,
            'content_gaps': intelligence.content_gaps,
            'cannibalization_risks': intelligence.cannibalization_risks,
        }
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def get_site_intelligence(request, site_id):
    """Return cached site intelligence."""
    try:
        site = Site.objects.get(id=site_id, user=request.user)
    except Site.DoesNotExist:
        return Response({'error': 'Site not found'}, status=404)

    try:
        intel = SiteIntelligence.objects.get(site=site)
        return Response({
            'success': True,
            'business_type': intel.business_type,
            'primary_goal': intel.primary_goal,
            'hub_pages': intel.hub_pages,
            'spoke_pages': intel.spoke_pages,
            'orphan_pages': intel.orphan_pages,
            'architecture_problems': intel.architecture_problems,
            'content_gaps': intel.content_gaps,
            'cannibalization_risks': intel.cannibalization_risks,
            'generated_at': intel.generated_at.isoformat(),
        })
    except SiteIntelligence.DoesNotExist:
        return Response({
            'success': False,
            'message': 'No intelligence generated yet. Call POST to generate.',
        }, status=200)
