"""Podcast Fetcher - A tool to fetch and store podcast episodes."""

__version__ = "0.2.0"

# Import main functionality
from .fetch_episodes import main as cli
from .add_podcast import cli as add_podcast_cli
from .models import Podcast, Episode
from .rss_parser import get_latest_episodes, get_episodes_since
from .taddy_search import TaddySearcher, create_taddy_searcher, TaddyPodcast, TaddySearchResult

__all__ = [
    'cli',
    'add_podcast_cli',
    'Podcast',
    'Episode',
    'get_latest_episodes',
    'get_episodes_since',
    'TaddySearcher',
    'create_taddy_searcher',
    'TaddyPodcast',
    'TaddySearchResult',
]
