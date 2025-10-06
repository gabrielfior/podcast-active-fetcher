"""CLI for adding and managing podcast series."""
import click
from datetime import datetime, timezone
from sqlmodel import Session, select
from typing import Optional

from podcast_fetcher.database import init_database
from podcast_fetcher.models import Podcast

@click.group()
def cli():
    """Podcast series management CLI."""
    pass

@cli.command()
@click.option('--title', prompt='Podcast title', help='Title of the podcast')
@click.option('--rss-feed', prompt='RSS feed URL', help='URL of the podcast RSS feed')
@click.option('--username', prompt='Telegram username', help='Telegram username of the user adding this podcast')
def add(title: str, rss_feed: str, username: str):
    """Add a new podcast series.
    
    Args:
        title: Title of the podcast
        rss_feed: URL of the podcast RSS feed
        username: Telegram username of the user adding this podcast
    """
    engine = init_database()
    
    with Session(engine) as session:
        # Check if podcast with this RSS feed already exists
        existing = session.exec(
            select(Podcast).where(Podcast.rss_feed == rss_feed)
        ).first()
        
        if existing:
            click.echo(f"A podcast with RSS feed '{rss_feed}' already exists: {existing.title}")
            return
        
        # Create new podcast
        podcast = Podcast(
            title=title,
            rss_feed=rss_feed,
            username=username,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        
        session.add(podcast)
        session.commit()
        
        click.echo(f"Successfully added podcast: {title} ({rss_feed}) by @{username}")

@cli.command()
@click.option('--limit', default=10, help='Maximum number of podcasts to list')
def list(limit: int):
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
            click.echo("No podcasts found.")
            return
            
        click.echo(f"Found {len(podcasts)} podcast(s):\n")
        for i, podcast in enumerate(podcasts, 1):
            click.echo(f"{i}. {podcast.title}")
            click.echo(f"   RSS Feed: {podcast.rss_feed}")
            click.echo(f"   Added by: @{podcast.username}" if podcast.username else "   Added by: Unknown")
            click.echo(f"   Added: {podcast.created_at.strftime('%Y-%m-%d %H:%M:%S')}\n")

if __name__ == "__main__":
    cli()
