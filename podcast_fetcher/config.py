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

# Taddy API Configuration
TADDY_API_KEY = os.getenv("TADDY_API_KEY", "76b4fe7f57ec3ecdc944802fddf7c2525b3bc29cac355c2392bfb9c5f2de8a1f383547bbbeeb39534b660c4be7b6a17219")
TADDY_USER_ID = os.getenv("TADDY_USER_ID", "891")
TADDY_BASE_URL = "https://api.taddy.org/"

# Create data directory if it doesn't exist
(BASE_DIR / "data").mkdir(exist_ok=True)
