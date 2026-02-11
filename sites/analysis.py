"""
Intelligence Layer - Cannibalization Detection and Analysis

This module provides the core analysis logic for detecting keyword
cannibalization and generating content recommendations.
"""
import re
from collections import defaultdict
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from django.db.models import Q
from django.utils import timezone


def extract_keywords_from_content(content: str, title: str = '', meta_description: str = '') -> List[str]:
    """
    Extract potential target keywords from page content.
    
    Uses a simple approach:
    1. Extract words from title (high weight)
    2. Extract words from meta description (medium weight)  
    3. Extract repeated phrases from content (low weight)
    
    Returns list of keyword phrases.
    """
    keywords = []
    
    # Clean and normalize text
    def clean_text(text: str) -> str:
        text = text.lower()
        text = re.sub(r'[^\w\s]', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
    
    # Stop words to filter out
    stop_words = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been',
        'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
        'should', 'may', 'might', 'must', 'can', 'this', 'that', 'these', 'those',
        'i', 'you', 'he', 'she', 'it', 'we', 'they', 'what', 'which', 'who',
        'when', 'where', 'why', 'how', 'all', 'each', 'every', 'both', 'few',
        'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only',
        'own', 'same', 'so', 'than', 'too', 'very', 'just', 'also', 'now',
        'your', 'our', 'their', 'its', 'my', 'his', 'her', 'about', 'into',
    }
    
    def extract_phrases(text: str, min_words: int = 2, max_words: int = 4) -> List[str]:
        """Extract meaningful phrases from text."""
        words = clean_text(text).split()
        words = [w for w in words if w not in stop_words and len(w) > 2]
        
        phrases = []
        for n in range(min_words, max_words + 1):
            for i in range(len(words) - n + 1):
                phrase = ' '.join(words[i:i+n])
                phrases.append(phrase)
        
        return phrases
    
    # Extract from title (most important)
    if title:
        title_phrases = extract_phrases(title, 1, 4)
        keywords.extend(title_phrases)
    
    # Extract from meta description
    if meta_description:
        meta_phrases = extract_phrases(meta_description, 2, 4)
        keywords.extend(meta_phrases)
    
    # Extract from H1 if in content
    h1_match = re.search(r'<h1[^>]*>(.*?)</h1>', content, re.IGNORECASE | re.DOTALL)
    if h1_match:
        h1_phrases = extract_phrases(h1_match.group(1), 1, 4)
        keywords.extend(h1_phrases)
    
    # Deduplicate and return
    seen = set()
    unique_keywords = []
    for kw in keywords:
        if kw not in seen and len(kw) > 3:
            seen.add(kw)
            unique_keywords.append(kw)
    
    return unique_keywords[:20]  # Limit to top 20


def calculate_keyword_similarity(kw1: str, kw2: str) -> float:
    """
    Calculate similarity between two keywords using word overlap.
    Returns a score between 0 and 1.
    """
    words1 = set(kw1.lower().split())
    words2 = set(kw2.lower().split())
    
    if not words1 or not words2:
        return 0.0
    
    # Jaccard similarity
    intersection = len(words1 & words2)
    union = len(words1 | words2)
    
    return intersection / union if union > 0 else 0.0


def detect_cannibalization(pages, include_noindex: bool = False) -> List[Dict[str, Any]]:
    """
    Detect keyword cannibalization across pages.
    
    A cannibalization issue occurs when multiple pages target the same
    or very similar keywords, causing them to compete in search results.
    
    Args:
        pages: QuerySet of Page objects with content
        include_noindex: If False (default), exclude noindex pages from analysis
        
    Returns:
        List of cannibalization issues with competing pages
    """
    # Build keyword -> pages mapping
    keyword_pages = defaultdict(list)
    
    for page in pages:
        # Skip noindex pages unless explicitly included
        if not include_noindex and getattr(page, 'is_noindex', False):
            continue
        # Get keywords for this page (seo_data is OneToOneField, not queryset)
        try:
            seo_data = page.seo_data
        except Exception:
            seo_data = None
        meta_title = seo_data.meta_title if seo_data else ''
        meta_description = seo_data.meta_description if seo_data else ''
        
        keywords = extract_keywords_from_content(
            page.content or '',
            page.title or meta_title or '',
            meta_description or page.excerpt or ''
        )
        
        for keyword in keywords:
            keyword_pages[keyword].append({
                'id': page.id,
                'url': page.url,
                'title': page.title,
                'is_money_page': page.is_money_page,
            })
    
    # Find keywords with multiple competing pages
    issues = []
    processed_keywords = set()
    
    for keyword, page_list in keyword_pages.items():
        if len(page_list) < 2:
            continue
            
        # Skip if we've already processed a very similar keyword
        skip = False
        for processed in processed_keywords:
            if calculate_keyword_similarity(keyword, processed) > 0.8:
                skip = True
                break
        
        if skip:
            continue
            
        processed_keywords.add(keyword)
        
        # Calculate severity
        num_pages = len(page_list)
        has_money_page = any(p['is_money_page'] for p in page_list)
        
        if num_pages >= 3:
            severity = 'high'
        elif num_pages == 2 and has_money_page:
            severity = 'high'
        elif num_pages == 2:
            severity = 'medium'
        else:
            severity = 'low'
        
        # Find suggested king (prefer money page, then first page)
        suggested_king = None
        for p in page_list:
            if p['is_money_page']:
                suggested_king = p
                break
        if not suggested_king:
            suggested_king = page_list[0]
        
        # Determine recommendation type
        if num_pages >= 3:
            recommendation = 'consolidate'
        elif has_money_page:
            recommendation = 'differentiate'
        else:
            recommendation = 'consolidate'
        
        issues.append({
            'keyword': keyword,
            'severity': severity,
            'recommendation_type': recommendation,
            'competing_pages': page_list,
            'suggested_king': suggested_king,
            'total_impressions': None,  # Would come from GSC
        })
    
    # Sort by severity (high first) and number of competing pages
    severity_order = {'high': 0, 'medium': 1, 'low': 2}
    issues.sort(key=lambda x: (severity_order[x['severity']], -len(x['competing_pages'])))
    
    return issues[:20]  # Return top 20 issues


def calculate_health_score(site) -> Dict[str, Any]:
    """
    Calculate overall site health score.
    
    Factors:
    - Cannibalization issues (-10 per high, -5 per medium, -2 per low)
    - Missing SEO data (-5 per page without)
    - Content organization bonus (+10 if silos exist)
    - Money pages defined bonus (+5)
    
    Returns dict with score and breakdown.
    """
    pages = site.pages.all()
    total_pages = pages.count()
    
    if total_pages == 0:
        return {
            'health_score': 0,
            'health_score_delta': 0,
            'breakdown': {
                'base_score': 0,
                'cannibalization_penalty': 0,
                'seo_data_penalty': 0,
                'money_page_bonus': 0,
            }
        }
    
    # Start with base score of 75
    score = 75
    
    # Cannibalization penalties
    issues = detect_cannibalization(pages)
    cannibalization_penalty = 0
    for issue in issues:
        if issue['severity'] == 'high':
            cannibalization_penalty += 10
        elif issue['severity'] == 'medium':
            cannibalization_penalty += 5
        else:
            cannibalization_penalty += 2
    
    score -= min(cannibalization_penalty, 40)  # Cap penalty at 40
    
    # SEO data penalty (seo_data is OneToOneField)
    pages_without_seo = 0
    for p in pages:
        try:
            _ = p.seo_data
        except Exception:
            pages_without_seo += 1
    seo_data_penalty = min((pages_without_seo / total_pages) * 20, 20) if total_pages > 0 else 0
    score -= seo_data_penalty
    
    # Money pages bonus
    money_pages = pages.filter(is_money_page=True).count()
    if money_pages > 0:
        score += 5
    
    # Ensure score is between 0 and 100
    score = max(0, min(100, score))
    
    return {
        'health_score': round(score),
        'health_score_delta': 0,  # Would need historical data
        'breakdown': {
            'base_score': 75,
            'cannibalization_penalty': -cannibalization_penalty,
            'seo_data_penalty': -round(seo_data_penalty),
            'money_page_bonus': 5 if money_pages > 0 else 0,
        }
    }


def generate_content_recommendations(pages, issues: List[Dict]) -> List[Dict[str, Any]]:
    """
    Generate content recommendations based on analysis.
    
    Recommendations include:
    - Content gaps (topics money pages should cover)
    - Supporting content ideas
    - Consolidation suggestions
    """
    recommendations = []
    
    money_pages = [p for p in pages if p.is_money_page]
    
    # For each money page, suggest supporting content
    for mp in money_pages[:5]:  # Limit to 5 money pages
        recommendations.append({
            'type': 'supporting_content',
            'priority': 'high',
            'title': f'Create supporting content for "{mp.title}"',
            'description': f'Your money page needs supporting articles to build topical authority.',
            'action': 'generate',
            'target_page_id': mp.id,
            'target_page_url': mp.url,
        })
    
    # For cannibalization issues, suggest fixes
    for issue in issues[:5]:
        if issue['recommendation_type'] == 'consolidate':
            recommendations.append({
                'type': 'consolidation',
                'priority': 'high' if issue['severity'] == 'high' else 'medium',
                'title': f'Consolidate pages targeting "{issue["keyword"]}"',
                'description': f'{len(issue["competing_pages"])} pages are competing for this keyword. Consider merging or differentiating.',
                'action': 'review',
                'competing_pages': issue['competing_pages'],
            })
        elif issue['recommendation_type'] == 'differentiate':
            recommendations.append({
                'type': 'differentiation',
                'priority': 'medium',
                'title': f'Differentiate content for "{issue["keyword"]}"',
                'description': 'Update non-money pages to target related but different keywords.',
                'action': 'edit',
                'competing_pages': issue['competing_pages'],
            })
    
    return recommendations


def analyze_site(site) -> Dict[str, Any]:
    """
    Run full analysis on a site.
    
    Returns comprehensive analysis including:
    - Health score
    - Cannibalization issues
    - Content recommendations
    """
    pages = site.pages.all().prefetch_related('seo_data')
    
    # Calculate health score
    health = calculate_health_score(site)
    
    # Detect cannibalization
    issues = detect_cannibalization(pages)
    
    # Generate recommendations
    recommendations = generate_content_recommendations(pages, issues)
    
    # Count statistics
    money_page_count = pages.filter(is_money_page=True).count()
    total_pages = pages.count()
    
    return {
        'site_id': site.id,
        'analyzed_at': timezone.now().isoformat(),
        'health_score': health['health_score'],
        'health_score_delta': health['health_score_delta'],
        'health_breakdown': health['breakdown'],
        'cannibalization_issues': issues,
        'cannibalization_count': len(issues),
        'recommendations': recommendations,
        'recommendation_count': len(recommendations),
        'page_count': total_pages,
        'money_page_count': money_page_count,
        'silo_count': 0,  # Would come from silo model
        'missing_links_count': 0,  # Would need link analysis
    }
