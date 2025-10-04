#!/usr/bin/env python3
"""Example script demonstrating Taddy API search functionality."""

from podcast_fetcher.taddy_search import create_taddy_searcher, TaddySearchError
from podcast_fetcher.config import TADDY_API_KEY, TADDY_USER_ID


def main():
    """Demonstrate Taddy search functionality."""
    print("Taddy API Podcast Search Example")
    print("=" * 40)
    
    try:
        # Create searcher instance
        searcher = create_taddy_searcher(TADDY_API_KEY, TADDY_USER_ID)
        
        # Search for podcasts
        search_term = "mamilos"
        print(f"Searching for podcasts with term: '{search_term}'")
        
        results = searcher.search_podcasts(search_term)
        
        print(f"\nSearch ID: {results.search_id}")
        print(f"Found {len(results.podcasts)} podcasts:")
        print("-" * 40)
        
        for i, podcast in enumerate(results.podcasts, 1):
            print(f"{i}. {podcast.name}")
            print(f"   RSS: {podcast.rss_url}")
            print(f"   Description: {podcast.description[:100]}...")
            print()
            
        # Demonstrate simplified search
        print("\nSimplified search results:")
        simple_results = searcher.search_podcasts_simple(search_term)
        for result in simple_results[:3]:  # Show first 3 results
            print(f"- {result['name']}: {result['rss_url']}")
            
    except TaddySearchError as e:
        print(f"Search failed: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")


if __name__ == "__main__":
    main()
