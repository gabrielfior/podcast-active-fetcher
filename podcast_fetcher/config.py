"""Configuration settings for the podcast fetcher."""
from pathlib import Path
import os

# Base directory
BASE_DIR = Path(__file__).parent.parent

# Database configuration
DB_FILE = "podcast_episodes.db"
DB_PATH = f"sqlite:///{BASE_DIR}/data/{DB_FILE}"

# RSS Feed
RSS_FEED = "https://feeds.captivate.fm/gradient-dissent/"

# Create data directory if it doesn't exist
(BASE_DIR / "data").mkdir(exist_ok=True)
