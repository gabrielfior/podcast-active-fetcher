"""Taddy API search functionality for finding podcasts."""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests


@dataclass
class TaddyPodcast:
    """Data class for Taddy API podcast search results."""
    uuid: str
    name: str
    rss_url: str
    description: str


@dataclass
class TaddySearchResult:
    """Data class for Taddy API search results."""
    search_id: str
    podcasts: List[TaddyPodcast]


class TaddySearchError(Exception):
    """Custom exception for Taddy API errors."""
    pass


class TaddySearcher:
    """Search for podcasts using the Taddy API."""
    
    def __init__(self, api_key: str, user_id: str):
        """Initialize the Taddy searcher.
        
        Args:
            api_key: Taddy API key
            user_id: Taddy user ID
        """
        self.api_key = api_key
        self.user_id = user_id
        self.base_url = "https://api.taddy.org/"
        
    def _get_headers(self) -> Dict[str, str]:
        """Get headers for Taddy API requests."""
        return {
            'accept': 'application/json, multipart/mixed',
            'content-type': 'application/json',
            'x-api-key': self.api_key,
            'x-user-id': self.user_id,
            'user-agent': 'PodcastFetcher/1.0'
        }
    
    def _build_search_query(self, term: str) -> str:
        """Build GraphQL query for podcast search.
        
        Args:
            term: Search term
            
        Returns:
            GraphQL query string
        """
        return f'''{{
  search(term:"{term}", filterForTypes:PODCASTSERIES){{
    searchId
    podcastSeries{{
      uuid
      name
      rssUrl
      description
    }}
  }}
}}'''
    
    def search_podcasts(self, term: str) -> TaddySearchResult:
        """Search for podcasts using the Taddy API.
        
        Args:
            term: Search term for podcasts
            
        Returns:
            TaddySearchResult containing search results
            
        Raises:
            TaddySearchError: If the API request fails
        """
        query = self._build_search_query(term)
        payload = {"query": query}
        
        try:
            response = requests.post(
                self.base_url,
                headers=self._get_headers(),
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            
            data = response.json()
            
            # Check for GraphQL errors
            if 'errors' in data:
                error_messages = [error.get('message', 'Unknown error') for error in data['errors']]
                raise TaddySearchError(f"GraphQL errors: {', '.join(error_messages)}")
            
            # Extract search results
            search_data = data.get('data', {}).get('search', {})
            search_id = search_data.get('searchId', '')
            podcast_series = search_data.get('podcastSeries', [])
            
            # Convert to TaddyPodcast objects
            podcasts = []
            for series in podcast_series:
                podcast = TaddyPodcast(
                    uuid=series.get('uuid', ''),
                    name=series.get('name', ''),
                    rss_url=series.get('rssUrl', ''),
                    description=series.get('description', '')
                )
                podcasts.append(podcast)
            
            return TaddySearchResult(
                search_id=search_id,
                podcasts=podcasts
            )
            
        except requests.exceptions.RequestException as e:
            raise TaddySearchError(f"Request failed: {str(e)}")
        except json.JSONDecodeError as e:
            raise TaddySearchError(f"Failed to parse JSON response: {str(e)}")
        except KeyError as e:
            raise TaddySearchError(f"Unexpected response format: {str(e)}")
    
    def search_podcasts_simple(self, term: str) -> List[Dict[str, str]]:
        """Search for podcasts and return simplified results.
        
        Args:
            term: Search term for podcasts
            
        Returns:
            List of dictionaries with podcast information
            
        Raises:
            TaddySearchError: If the API request fails
        """
        result = self.search_podcasts(term)
        
        return [
            {
                'uuid': podcast.uuid,
                'name': podcast.name,
                'rss_url': podcast.rss_url,
                'description': podcast.description
            }
            for podcast in result.podcasts
        ]


def create_taddy_searcher(api_key: str, user_id: str) -> TaddySearcher:
    """Create a TaddySearcher instance.
    
    Args:
        api_key: Taddy API key
        user_id: Taddy user ID
        
    Returns:
        TaddySearcher instance
    """
    return TaddySearcher(api_key, user_id)


# Example usage
if __name__ == "__main__":
    # Example API credentials (replace with actual values)
    API_KEY = "76b4fe7f57ec3ecdc944802fddf7c2525b3bc29cac355c2392bfb9c5f2de8a1f383547bbbeeb39534b660c4be7b6a17219"
    USER_ID = "891"
    
    try:
        searcher = create_taddy_searcher(API_KEY, USER_ID)
        results = searcher.search_podcasts("mamilos")
        
        print(f"Search ID: {results.search_id}")
        print(f"Found {len(results.podcasts)} podcasts:")
        
        for podcast in results.podcasts:
            print(f"- {podcast.name}")
            print(f"  RSS: {podcast.rss_url}")
            print(f"  Description: {podcast.description[:100]}...")
            print()
            
    except TaddySearchError as e:
        print(f"Search failed: {e}")
