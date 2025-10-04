#!/usr/bin/env python3
"""CLI script for searching podcasts using the Taddy API."""

import argparse
import sys
from typing import List

from .taddy_search import TaddySearcher, TaddySearchError
from .config import TADDY_API_KEY, TADDY_USER_ID


def format_podcast_output(podcast) -> str:
    """Format a podcast for display."""
    return f"""
Name: {podcast.name}
UUID: {podcast.uuid}
RSS URL: {podcast.rss_url}
Description: {podcast.description[:200]}{'...' if len(podcast.description) > 200 else ''}
---"""


def search_podcasts_cli(term: str, limit: int = 10) -> None:
    """Search for podcasts using the Taddy API.
    
    Args:
        term: Search term
        limit: Maximum number of results to display
    """
    try:
        searcher = TaddySearcher(TADDY_API_KEY, TADDY_USER_ID)
        results = searcher.search_podcasts(term)
        
        print(f"Search ID: {results.search_id}")
        print(f"Found {len(results.podcasts)} podcasts for '{term}':")
        print("=" * 50)
        
        for i, podcast in enumerate(results.podcasts[:limit], 1):
            print(f"{i}. {format_podcast_output(podcast)}")
            
        if len(results.podcasts) > limit:
            print(f"\n... and {len(results.podcasts) - limit} more results")
            
    except TaddySearchError as e:
        print(f"Error searching podcasts: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)



