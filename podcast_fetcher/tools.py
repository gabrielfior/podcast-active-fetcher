from sqlmodel import Session, create_engine, select
from strands import Agent, tool

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

    @tool
    def query_episode_by_id(self, episode_id: str) -> str:
        """Query and retrieve the transcript of a specific podcast episode by its ID.
        
        Use this tool whenever the user asks about:
        - Getting the transcript of a specific episode
        - Reading the full content of an episode
        - Analyzing or searching within episode content
        - Getting detailed information from episode transcripts

        Args:
            episode_id: The unique identifier of the episode whose transcript to retrieve
            
        Returns:
            The transcript text of the episode, or an error message if not found
        """
        
        with Session(self.engine) as session:
            transcript = session.exec(
                select(Episode.transcript)
                .where(Episode.id == episode_id)
            ).first()
            
            if transcript:
                return transcript
            else:
                return f"No transcript found for episode ID: {episode_id}"
