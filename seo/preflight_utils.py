"""
Utility functions for preflight content validation.
Pure Python — no external dependencies beyond stdlib.
"""

STOP_WORDS = frozenset({
    'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
    'of', 'with', 'by', 'from', 'is', 'it', 'as', 'be', 'was', 'are',
    'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
    'would', 'could', 'should', 'may', 'might', 'shall', 'can', 'not',
    'no', 'so', 'if', 'than', 'that', 'this', 'these', 'those', 'then',
    'there', 'their', 'they', 'them', 'we', 'us', 'our', 'you', 'your',
    'he', 'she', 'his', 'her', 'its', 'my', 'me', 'i', 'am', 'up',
    'about', 'into', 'through', 'during', 'before', 'after', 'above',
    'below', 'between', 'out', 'off', 'over', 'under', 'again', 'further',
    'once', 'here', 'when', 'where', 'why', 'how', 'all', 'each', 'every',
    'both', 'few', 'more', 'most', 'other', 'some', 'such', 'only', 'own',
    'same', 'just', 'also', 'very', 'too',
})

SUPERLATIVES = frozenset({
    'best', 'top', 'ultimate', 'leading', 'premier', 'greatest', 'finest',
    'superior', '#1', 'number one',
})

FILLERS = frozenset({
    'guide', 'tips', 'complete', 'comprehensive', 'definitive',
})

# Multi-word fillers handled separately
FILLER_PHRASES = [
    'everything you need', 'how to', 'what is',
]


def extract_keywords(text):
    """Tokenize, lowercase, filter stop words. Returns list of keywords."""
    if not text:
        return []
    import re
    tokens = re.findall(r'[a-z0-9#]+', text.lower())
    return [t for t in tokens if t not in STOP_WORDS and len(t) > 1]


def get_intent_skeleton(title):
    """Strip superlatives + fillers, sort remaining words. Returns sorted list."""
    if not title:
        return []
    text = title.lower()
    # Strip multi-word phrases first
    for phrase in FILLER_PHRASES:
        text = text.replace(phrase, ' ')
    import re
    tokens = re.findall(r'[a-z0-9#]+', text)
    tokens = [t for t in tokens if t not in SUPERLATIVES and t not in FILLERS and t not in STOP_WORDS and len(t) > 1]
    return sorted(tokens)


def levenshtein_distance(a, b):
    """Classic DP Levenshtein distance."""
    if not a:
        return len(b) if b else 0
    if not b:
        return len(a)
    m, n = len(a), len(b)
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        curr = [i] + [0] * n
        for j in range(1, n + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[n]


def levenshtein_similarity(a, b):
    """Returns 0.0–1.0 similarity based on Levenshtein distance."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    a, b = a.lower().strip(), b.lower().strip()
    max_len = max(len(a), len(b))
    if max_len == 0:
        return 1.0
    return 1.0 - (levenshtein_distance(a, b) / max_len)


def calculate_keyword_overlap(words_a, words_b):
    """Intersection / max(len_a, len_b). Returns 0.0–1.0."""
    if not words_a or not words_b:
        return 0.0
    set_a, set_b = set(words_a), set(words_b)
    max_len = max(len(set_a), len(set_b))
    if max_len == 0:
        return 0.0
    return len(set_a & set_b) / max_len
