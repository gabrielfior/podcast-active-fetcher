"""Database operations for the podcast fetcher."""
from typing import Dict, List, Tuple, Any, cast, Optional
from sqlalchemy import func, select as sql_select, and_
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy.engine import Engine
from dotenv import load_dotenv
import os
load_dotenv()

from podcast_fetcher.models import Episode, UpdateFrequency
from loguru import logger


def init_database() -> Engine:
    """Initialize the SQLite database with the episodes table if it doesn't exist.
    
    Returns:
        Engine: SQLAlchemy engine instance
    """
    DB_PATH = os.getenv('SQLALCHEMY_DATABASE_URI')
    logger.info(f"Initializing database with path: {DB_PATH}")
    engine = create_engine(DB_PATH)
    SQLModel.metadata.create_all(engine)
    return engine

def save_episode(engine: Engine, episode_data: Dict[str, Any]) -> Tuple[bool, str]:
    """Save episode to the database if it doesn't exist, or update if it does.
    
    Args:
        engine: SQLAlchemy engine
        episode_data: Dictionary containing episode information
        
    Returns:
        Tuple of (success: bool, action: str)
    """
    try:
        with Session(engine) as session:
            # Check if episode exists
            episode = session.get(Episode, episode_data['id'])
            
            if episode:
                # Update existing episode
                for key, value in episode_data.items():
                    setattr(episode, key, value)
                action = "Updated"
            else:
                # Create new episode
                episode = Episode(**episode_data)
                session.add(episode)
                action = "Added"
            
            session.commit()
            return True, action
            
    except Exception as e:
        print(f"Database error: {e}")
        return False, "Error"

def get_episodes_count(engine: Engine) -> int:
    """Get the total number of episodes in the database.
    
    Args:
        engine: SQLAlchemy engine
        
    Returns:
        int: Number of episodes in the database
    """
    with Session(engine) as session:
        # Get all episodes and count them in memory
        # This is less efficient for large datasets but avoids SQLAlchemy type issues
        return len(session.exec(select(Episode)).all())

def episode_exists(engine: Engine, title: str) -> bool:
    """Check if an episode with the given title already exists in the database.
    
    Args:
        engine: SQLAlchemy engine
        title: Episode title to check
        
    Returns:
        bool: True if an episode with the title exists, False otherwise
    """
    with Session(engine) as session:
        statement = select(Episode).where(Episode.title == title)
        result = session.exec(statement).first()
        return result is not None

def get_all_episodes(engine: Engine) -> List[Episode]:
    """Get all episodes from the database.
    
    Args:
        engine: SQLAlchemy engine
        
    Returns:
        List[Episode]: List of all episodes in the database
    """
    with Session(engine) as session:
        statement = select(Episode)
        results = session.exec(statement)
        return list(results.all())


def get_episodes_since(engine: Engine, days_ago: int) -> List[Episode]:
    """Get episodes published within the last N days.
    
    Args:
        engine: SQLAlchemy engine
        days_ago: Number of days ago to look back
        
    Returns:
        List[Episode]: List of episodes published within the last N days
    """
    from datetime import datetime, timedelta, timezone
    
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_ago)
    
    with Session(engine) as session:
        statement = select(Episode).where(Episode.published >= cutoff_date)
        results = session.exec(statement)
        return list(results.all())


def set_user_update_frequency(engine: Engine, username: str, frequency_in_days: int) -> bool:
    """Set or update the update frequency for a user.
    
    Args:
        engine: SQLAlchemy engine
        username: Telegram username
        frequency_in_days: Update frequency in days
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        from datetime import datetime, timezone
        
        with Session(engine) as session:
            # Check if user already has a frequency setting
            existing = session.get(UpdateFrequency, username)
            
            if existing:
                # Update existing frequency
                existing.frequency_in_days = frequency_in_days
                existing.updated_at = datetime.now(timezone.utc)
            else:
                # Create new frequency setting
                frequency = UpdateFrequency(
                    username=username,
                    frequency_in_days=frequency_in_days
                )
                session.add(frequency)
            
            session.commit()
            return True
            
    except Exception as e:
        logger.error(f"Error setting update frequency: {e}")
        return False


def get_user_update_frequency(engine: Engine, username: str) -> Optional[int]:
    """Get the update frequency for a user.
    
    Args:
        engine: SQLAlchemy engine
        username: Telegram username
        
    Returns:
        Optional[int]: Update frequency in days, or None if not set
    """
    try:
        with Session(engine) as session:
            frequency = session.get(UpdateFrequency, username)
            return frequency.frequency_in_days if frequency else None
            
    except Exception as e:
        logger.error(f"Error getting update frequency: {e}")
        return None
