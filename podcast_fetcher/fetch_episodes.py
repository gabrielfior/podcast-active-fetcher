"""Main entry point for the podcast fetcher package."""
import argparse
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from sqlmodel import Session, select

from podcast_fetcher.database import init_database, save_episode, get_episodes_count, episode_exists
from podcast_fetcher.rss_parser import get_episodes_since, get_latest_episodes
from podcast_fetcher.models import Podcast, Episode

def format_datetime(dt: datetime) -> str:
    """Format a datetime object for display."""
    return dt.strftime('%Y-%m-%d %H:%M:%S %Z')

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Fetch podcast episodes from RSS feeds.')
    
    # Add subparsers for different commands
    subparsers = parser.add_subparsers(dest='command', help='Command to run', required=True)
    
    # Fetch command
    fetch_parser = subparsers.add_parser('fetch', help='Fetch podcast episodes')
    fetch_group = fetch_parser.add_mutually_exclusive_group()
    fetch_group.add_argument('--max-episodes', type=int, default=10, 
                           help='Maximum number of episodes to fetch per podcast (default: 10)')
    fetch_group.add_argument('--days', type=int, 
                           help='Fetch episodes from the last N days')
    fetch_parser.add_argument('--podcast-id', type=int, 
                             help='Fetch episodes for a specific podcast ID')
    fetch_parser.add_argument('--all', action='store_true',
                            help='Fetch episodes for all podcasts')
    
    # List command
    list_parser = subparsers.add_parser('list', help='List podcasts')
    list_parser.add_argument('--limit', type=int, default=10, 
                            help='Maximum number of podcasts to list')
    
    return parser.parse_args()

def list_podcasts(limit: int = 10):
    """List all podcast series.
    
    Args:
        limit: Maximum number of podcasts to display
    """
    engine = init_database()
    
    with Session(engine) as session:
        podcasts = session.exec(
            select(Podcast).order_by(Podcast.title).limit(limit)
        ).all()
        
        if not podcasts:
            print("No podcasts found. Add a podcast using 'python -m podcast_fetcher.add_podcast add'")
            return
            
        print(f"Found {len(podcasts)} podcast(s):\n")
        for i, podcast in enumerate(podcasts, 1):
            print(f"{i}. {podcast.title} (ID: {podcast.id})")
            print(f"   RSS Feed: {podcast.rss_feed}")
            print(f"   Added: {podcast.created_at.strftime('%Y-%m-%d %H:%M:%S')}\n")

def fetch_episodes(days: Optional[int] = None, max_episodes: int = 10, podcast_id: Optional[int] = None, all_podcasts: bool = False):
    """Fetch episodes from podcast RSS feeds.
    
    Args:
        days: Number of days to look back for episodes
        max_episodes: Maximum number of episodes to fetch per podcast
        podcast_id: ID of the podcast to fetch episodes for
        all_podcasts: If True, fetch episodes for all podcasts
    """
    engine = init_database()
    
    with Session(engine) as session:
        # Determine which podcasts to process
        if podcast_id:
            podcasts = [session.get(Podcast, podcast_id)]
            if not podcasts[0]:
                print(f"Error: Podcast with ID {podcast_id} not found")
                return
        elif all_podcasts:
            podcasts = session.exec(select(Podcast)).all()
            if not podcasts:
                print("No podcasts found. Add a podcast using 'python -m podcast_fetcher.add_podcast add'")
                return
        else:
            print("Please specify --podcast-id or --all to select which podcasts to fetch")
            return
        
        # Process each podcast
        for podcast in podcasts:
            print(f"\nProcessing podcast: {podcast.title} (ID: {podcast.id})")
            print("-" * 50)
            
            try:
                # Fetch episodes based on the specified time range
                if days:
                    since_date = datetime.now(timezone.utc) - timedelta(days=days)
                    print(f"Fetching episodes from the last {days} days...")
                    episodes = get_episodes_since(
                        feed_url=podcast.rss_feed,
                        since_date=since_date,
                        max_episodes=max_episodes
                    )
                else:
                    print(f"Fetching the latest {max_episodes} episodes...")
                    episodes = get_latest_episodes(
                        feed_url=podcast.rss_feed,
                        max_episodes=max_episodes
                    )
                
                if not episodes:
                    print("No episodes found in the feed")
                    continue
                
                print(f"Found {len(episodes)} episodes in the feed")
                
                # Save episodes to the database
                saved_count = 0
                for episode_data in episodes:
                    # Add podcast_id to episode data
                    episode_data['podcast_id'] = podcast.id
                    
                    # Check if episode already exists
                    existing = session.get(Episode, episode_data['id'])
                    if existing:
                        print(f"Skipping existing episode: {episode_data['title']}")
                        continue
                    
                    # Save new episode
                    episode = Episode(**episode_data)
                    session.add(episode)
                    saved_count += 1
                    print(f"Added: {episode.title} ({episode.published.strftime('%Y-%m-%d')})")
                
                session.commit()
                print(f"\nSaved {saved_count} new episodes from {podcast.title}")
                
            except Exception as e:
                print(f"Error processing podcast {podcast.title}: {str(e)}")
                session.rollback()

def main():
    """Main function to handle CLI commands."""
    args = parse_args()
    
    try:
        if args.command == 'list':
            list_podcasts(limit=args.limit)
        elif args.command == 'fetch':
            fetch_episodes(
                days=args.days,
                max_episodes=args.max_episodes,
                podcast_id=args.podcast_id,
                all_podcasts=args.all
            )
    except Exception as e:
        print(f"\n❌ An error occurred: {e}")
        if hasattr(e, '__traceback__'):
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
