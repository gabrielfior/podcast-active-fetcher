"""RSS feed parsing functionality for the podcast fetcher."""
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, cast
import feedparser
import html
import requests
import hashlib
from urllib.parse import urlparse
from dateutil import parser as date_parser

try:
    from bs4 import BeautifulSoup
    BEAUTIFUL_SOUP_AVAILABLE = True
except ImportError:  # pragma: no cover
    BEAUTIFUL_SOUP_AVAILABLE = False

from typing import Optional, List, Dict, Any
from datetime import datetime

from .config import RSS_FEED

def extract_episode_id(entry: Dict[str, Any]) -> str:
    """Generate a unique ID for the episode using multiple fields."""
    # Create a hash of the title and published date to ensure uniqueness
    unique_str = f"{entry.get('title', '')}-{entry.get('published', '')}"
    return hashlib.md5(unique_str.encode('utf-8')).hexdigest()

def extract_audio_url(entry: Any) -> Optional[str]:
    """Extract audio URL from the feed entry."""
    if hasattr(entry, 'links'):
        for link in entry.links:
            if link.get('type', '').startswith('audio/'):
                return link.href
    return None

def extract_transcript_url(entry: Any) -> Optional[str]:
    """Extract transcript URL from the feed entry or content.
    
    Args:
        entry: Feed entry from feedparser
        
    Returns:
        str: URL of the transcript if found, None otherwise
    """
    if not BEAUTIFUL_SOUP_AVAILABLE:
        return None
        
    # First check for direct transcript links
    if hasattr(entry, 'links'):
        for link in entry.links:
            if 'transcript' in link.get('type', '').lower() or 'transcript' in link.get('title', '').lower():
                return str(link.href) if link.href else None
    
    # Then check the content for transcript links
    content = getattr(entry, 'content', [{}])[0].get('value', '') if hasattr(entry, 'content') else ''
    soup = BeautifulSoup(content, 'html.parser')
    for a in soup.find_all('a', href=True, string=lambda t: t and 'transcript' in t.lower()):
        return str(a['href'])
    
    return None

def fetch_transcript(transcript_url: str) -> Optional[str]:
    """Attempt to fetch and extract transcript from a URL.
    
    Args:
        transcript_url: URL of the transcript
        
    Returns:
        str: Extracted transcript text if successful, None otherwise
    """
    if not BEAUTIFUL_SOUP_AVAILABLE or not transcript_url:
        return None
        
    try:
        response = requests.get(transcript_url, timeout=10)
        response.raise_for_status()
        
        # Simple extraction - this might need adjustment based on the actual transcript format
        soup = BeautifulSoup(response.text, 'html.parser')
        # Try to find the main content area
        content = soup.find('article') or soup.find('main') or soup.find('div', class_='content') or soup
        # Remove script and style elements
        for script in content.find_all(['script', 'style']):  # type: ignore
            script.decompose()
        return ' '.join(content.stripped_strings)  # type: ignore
    except Exception as e:
        print(f"Error fetching transcript from {transcript_url}: {e}")
        return None

def parse_published_date(published_str: str) -> datetime:
    """Parse a date string from the RSS feed into a datetime object.
    
    Args:
        published_str: Date string from the RSS feed
        
    Returns:
        datetime: Parsed datetime object in UTC
    """
    try:
        # Try to parse with dateutil.parser which handles most date formats
        dt = date_parser.parse(published_str)
        # Ensure the datetime is timezone-aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, OverflowError) as e:
        # Fallback to current time if parsing fails
        return datetime.now(timezone.utc)

def get_latest_episodes(feed_url: str = RSS_FEED, max_episodes: int = 10) -> List[Dict[str, Any]]:
    """Fetch and return the latest episodes from the podcast RSS feed.
    
    Args:
        feed_url: URL of the podcast RSS feed
        max_episodes: Maximum number of episodes to return
        
    Returns:
        List of dictionaries containing episode information with datetime objects for dates
    """
    return get_episodes_since(feed_url=feed_url, max_episodes=max_episodes)

def get_episodes_since(
    feed_url: str = RSS_FEED, 
    since_date: Optional[datetime] = None, 
    max_episodes: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Fetch episodes from the podcast RSS feed that were published after a specific date.
    
    Args:
        feed_url: URL of the podcast RSS feed
        since_date: Only return episodes published after this date. If None, returns all episodes.
        max_episodes: Maximum number of episodes to return. If None, returns all matching episodes.
        
    Returns:
        List of dictionaries containing episode information with datetime objects for dates
    """
    feed = feedparser.parse(feed_url)
    episodes = []
    
    for entry in feed.entries:
        # Parse the published date
        published_str = entry.get('published', '')
        published_dt = parse_published_date(published_str)
        
        # Skip if the episode is older than the cutoff date
        if since_date and published_dt <= since_date:
            continue
            
        audio_url = extract_audio_url(entry)
        transcript_url = extract_transcript_url(entry)
        transcript = None
        
        # Only fetch transcript if URL is available and not too long to process
        if transcript_url and len(transcript_url) < 1000:  # Basic URL length check
            transcript = fetch_transcript(transcript_url)
        
        # Create episode data with all fields
        episode_data = {
            'title': html.unescape(entry.get('title', 'No title')),
            'published': published_dt,
            'summary': html.unescape(entry.get('summary', 'No summary available')),
            'link': entry.get('link', ''),
            'audio_url': audio_url,
            'transcript_url': transcript_url,
            'transcript': transcript
        }
        
        # Generate a unique ID based on the episode data
        episode_data['id'] = extract_episode_id(episode_data)
        
        episodes.append(episode_data)
        
        # Stop if we've reached the maximum number of episodes
        if max_episodes and len(episodes) >= max_episodes:
            break
    
    return episodes
