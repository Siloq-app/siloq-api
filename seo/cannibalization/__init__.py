"""
Siloq Cannibalization Detection Engine v2.1

A comprehensive 7-phase pipeline for detecting and resolving keyword cannibalization:
- Phase 1: URL normalization, classification, metadata extraction
- Phase 2: Safe filter detection (siblings, parent-child, geographic)
- Phase 3: Static detection (taxonomy clash, legacy, near-duplicate)
- Phase 4: GSC validation (impression share, conflict confirmation)
- Phase 5: Wrong winner detection (intent mismatch)
- Phase 6: Clustering (group by fix, priority scoring)
- Phase 7: Fix recommendations (action codes, redirect CSV)
"""

from .pipeline import run_analysis

__version__ = '2.1.0'
__all__ = ['run_analysis']
