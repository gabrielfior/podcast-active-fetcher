"""Database operations for the podcast fetcher."""
from typing import Dict, List, Tuple, Any, cast, Optional
from sqlalchemy import func, select as sql_select, and_
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy.engine import Engine
from dotenv import load_dotenv
import os
from datetime import datetime, timezone
load_dotenv()

from podcast_fetcher.models import Episode, UserSubscription, ProcessedEpisode, Podcast
from loguru import logger


def init_database() -> Engine:
    """Initialize the SQLite database with the episodes table if it doesn't exist.
    
    Returns:
        Engine: SQLAlchemy engine instance
    """
    DB_PATH = os.getenv('SQLALCHEMY_DATABASE_URI')
    logger.info(f"Initializing database with path: {DB_PATH}")
    engine = create_engine(DB_PATH)
    
    # Create tables using a proper session context to ensure connection cleanup
    with Session(engine) as session:
        SQLModel.metadata.create_all(engine)
        session.commit()
    
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




# Subscription management functions

def subscribe_user_to_podcast(engine: Engine, username: str, podcast_id: int, notification_preferences: str = "immediate") -> Tuple[bool, str]:
    """Subscribe a user to a podcast.
    
    Args:
        engine: SQLAlchemy engine
        username: Telegram username
        podcast_id: ID of the podcast to subscribe to
        notification_preferences: Notification preference (immediate, daily, weekly)
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        with Session(engine) as session:
            # Check if subscription already exists
            existing = session.exec(
                select(UserSubscription).where(
                    and_(
                        UserSubscription.username == username,
                        UserSubscription.podcast_id == podcast_id
                    )
                )
            ).first()
            
            if existing:
                if existing.is_active:
                    return False, "You're already subscribed to this podcast!"
                else:
                    # Reactivate subscription
                    existing.is_active = True
                    existing.notification_preferences = notification_preferences
                    existing.updated_at = datetime.now(timezone.utc)
                    session.commit()
                    return True, "Subscription reactivated!"
            else:
                # Create new subscription
                subscription = UserSubscription(
                    username=username,
                    podcast_id=podcast_id,
                    notification_preferences=notification_preferences
                )
                session.add(subscription)
                session.commit()
                return True, "Successfully subscribed!"
                
    except Exception as e:
        logger.error(f"Error subscribing user to podcast: {e}")
        return False, f"Error: {str(e)}"


def unsubscribe_user_from_podcast(engine: Engine, username: str, podcast_id: int) -> Tuple[bool, str]:
    """Unsubscribe a user from a podcast.
    
    Args:
        engine: SQLAlchemy engine
        username: Telegram username
        podcast_id: ID of the podcast to unsubscribe from
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        with Session(engine) as session:
            subscription = session.exec(
                select(UserSubscription).where(
                    and_(
                        UserSubscription.username == username,
                        UserSubscription.podcast_id == podcast_id
                    )
                )
            ).first()
            
            if not subscription:
                return False, "You're not subscribed to this podcast."
            
            if not subscription.is_active:
                return False, "You're already unsubscribed from this podcast."
            
            # Deactivate subscription
            subscription.is_active = False
            subscription.updated_at = datetime.now(timezone.utc)
            session.commit()
            return True, "Successfully unsubscribed!"
            
    except Exception as e:
        logger.error(f"Error unsubscribing user from podcast: {e}")
        return False, f"Error: {str(e)}"


def get_user_subscriptions(engine: Engine, username: str) -> List[Tuple[UserSubscription, Podcast]]:
    """Get all active subscriptions for a user.
    
    Args:
        engine: SQLAlchemy engine
        username: Telegram username
        
    Returns:
        List of (UserSubscription, Podcast) tuples
    """
    try:
        with Session(engine) as session:
            statement = select(UserSubscription, Podcast).join(
                Podcast, UserSubscription.podcast_id == Podcast.id
            ).where(
                and_(
                    UserSubscription.username == username,
                    UserSubscription.is_active == True
                )
            )
            results = session.exec(statement)
            return list(results.all())
            
    except Exception as e:
        logger.error(f"Error getting user subscriptions: {e}")
        return []


def get_podcast_subscribers(engine: Engine, podcast_id: int) -> List[str]:
    """Get all active subscribers for a podcast.
    
    Args:
        engine: SQLAlchemy engine
        podcast_id: ID of the podcast
        
    Returns:
        List of usernames
    """
    try:
        with Session(engine) as session:
            statement = select(UserSubscription.username).where(
                and_(
                    UserSubscription.podcast_id == podcast_id,
                    UserSubscription.is_active == True
                )
            )
            results = session.exec(statement)
            return list(results.all())
            
    except Exception as e:
        logger.error(f"Error getting podcast subscribers: {e}")
        return []


def mark_episode_processed(engine: Engine, episode_id: str, username: str, summary_sent: bool = True) -> bool:
    """Mark an episode as processed for a user.
    
    Args:
        engine: SQLAlchemy engine
        episode_id: ID of the episode
        username: Telegram username
        summary_sent: Whether the summary was sent
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        with Session(engine) as session:
            # Check if already processed
            existing = session.exec(
                select(ProcessedEpisode).where(
                    and_(
                        ProcessedEpisode.episode_id == episode_id,
                        ProcessedEpisode.username == username
                    )
                )
            ).first()
            
            if existing:
                # Update existing record
                existing.summary_sent = summary_sent
                existing.processed_at = datetime.now(timezone.utc)
            else:
                # Create new record
                processed = ProcessedEpisode(
                    episode_id=episode_id,
                    username=username,
                    summary_sent=summary_sent
                )
                session.add(processed)
            
            session.commit()
            return True
            
    except Exception as e:
        logger.error(f"Error marking episode as processed: {e}")
        return False


def is_episode_processed_for_user(engine: Engine, episode_id: str, username: str) -> bool:
    """Check if an episode has been processed for a user.
    
    Args:
        engine: SQLAlchemy engine
        episode_id: ID of the episode
        username: Telegram username
        
    Returns:
        bool: True if processed, False otherwise
    """
    try:
        with Session(engine) as session:
            processed = session.exec(
                select(ProcessedEpisode).where(
                    and_(
                        ProcessedEpisode.episode_id == episode_id,
                        ProcessedEpisode.username == username
                    )
                )
            ).first()
            return processed is not None
            
    except Exception as e:
        logger.error(f"Error checking if episode is processed: {e}")
        return False


def update_subscription_preferences(engine: Engine, username: str, podcast_id: int, notification_preferences: str) -> Tuple[bool, str]:
    """Update notification preferences for a subscription.
    
    Args:
        engine: SQLAlchemy engine
        username: Telegram username
        podcast_id: ID of the podcast
        notification_preferences: New notification preference
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        with Session(engine) as session:
            subscription = session.exec(
                select(UserSubscription).where(
                    and_(
                        UserSubscription.username == username,
                        UserSubscription.podcast_id == podcast_id
                    )
                )
            ).first()
            
            if not subscription:
                return False, "Subscription not found."
            
            subscription.notification_preferences = notification_preferences
            subscription.updated_at = datetime.now(timezone.utc)
            session.commit()
            return True, "Preferences updated!"
            
    except Exception as e:
        logger.error(f"Error updating subscription preferences: {e}")
        return False, f"Error: {str(e)}"
