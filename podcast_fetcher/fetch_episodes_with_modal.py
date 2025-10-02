import os
import modal
from datetime import datetime, timedelta, timezone
from sqlmodel import Session, select
from dotenv import load_dotenv

load_dotenv()

from podcast_fetcher.database import init_database
from podcast_fetcher.models import Episode, Podcast
from podcast_fetcher.rss_parser import get_episodes_since

app = modal.App("fetch-episodes2")




image = (
    modal.Image.debian_slim(python_version="3.11.9")
    .uv_pip_install("sqlmodel>=0.0.24", "beautifulsoup4>=4.13.4", "feedparser>=6.0.11", "python-dotenv>=1.1.1", "loguru>=0.7.1", "psycopg>=3.2.9", "requests>=2.31.0", "python-dateutil>=2.8.2", "psycopg2-binary>=2.9.10")
    .add_local_python_source("podcast_fetcher")
)


@app.function(schedule=modal.Cron("0 */12 * * *"), image=image,
              secrets=[modal.Secret.from_name("SQLALCHEMY_DATABASE_URI")])
def fetch_podcast_episodes():
    """Fetch episodes from all podcast RSS feeds with 10-day lookback."""
    print("Starting podcast episode fetch on Modal...")
    
    
    
    # Hardcoded parameters
    days = 10
    
    engine = init_database()
    
    with Session(engine) as session:
        # Get all podcasts
        podcasts = session.exec(select(Podcast)).all()
        if not podcasts:
            print("No podcasts found. Add a podcast using 'python -m podcast_fetcher.add_podcast add'")
            return
        
        print(f"Found {len(podcasts)} podcast(s) to process")
        
        # Process each podcast
        total_saved = 0
        for podcast in podcasts:
            print(f"\nProcessing podcast: {podcast.title} (ID: {podcast.id})")
            print("-" * 50)
            
            try:
                # Fetch episodes from the last 10 days
                since_date = datetime.now(timezone.utc) - timedelta(days=days)
                print(f"Fetching episodes from the last {days} days...")
                episodes = get_episodes_since(
                    feed_url=podcast.rss_feed,
                    since_date=since_date,
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
                print(f"Saved {saved_count} new episodes from {podcast.title}")
                total_saved += saved_count
                
            except Exception as e:
                print(f"Error processing podcast {podcast.title}: {str(e)}")
                session.rollback()
        
        print(f"\n🎉 Total episodes saved: {total_saved}")
        return total_saved

if __name__ == "__main__":
   app.deploy()