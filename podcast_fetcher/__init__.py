"""Podcast Fetcher - A tool to fetch and store podcast episodes."""

__version__ = "0.2.0"

from .add_podcast import cli as add_podcast_cli

# Import main functionality
from .fetch_episodes import main as cli
from .models import Episode, Podcast
from .rss_parser import get_episodes_since, get_latest_episodes
from .taddy_search import (
                           TaddyPodcast,
                           TaddySearcher,
                           TaddySearchResult,
                           create_taddy_searcher,
)

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
