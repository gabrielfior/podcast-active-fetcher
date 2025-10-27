from strands import Agent, tool

from sqlmodel import create_engine, select, Session
from podcast_fetcher.keys import Config
from podcast_fetcher.models import Episode, Podcast


class DatabaseTools:
    def __init__(self):
        self.engine = create_engine(Config().SQLALCHEMY_DATABASE_URI)   
    

    @tool
    def query_episodes_from_user(self, username: str) -> list[Episode]:
        """Query and retrieve all podcast episodes that a specific user has subscribed to or added.
        
        Use this tool whenever the user asks about:
        - Their podcast episodes
        - Episodes they've saved or subscribed to
        - What podcasts they're following
        - Details about episodes in their collection
        - Searching or filtering their episodes

        Args:
            username: The Telegram username of the user whose episodes to retrieve
            
        Returns:
            A list of Episode objects containing title, description, audio_url, and other metadata
        """
        
        with Session(self.engine) as session:
            episodes = session.exec(
                select(Episode.id, Episode.title, Episode.published, Episode.summary)
                .join(Podcast, Episode.podcast_id == Podcast.id)
                .where(Podcast.username == username)
                #.where(Podcast.title == 'Software Engineering Daily')
            ).all()
            return episodes
