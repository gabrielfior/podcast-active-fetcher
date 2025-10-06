"""Database models for the podcast fetcher."""
from datetime import datetime, timezone
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship

class Podcast(SQLModel, table=True):
    """SQLModel for podcast series."""
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(index=True)
    rss_feed: str = Field(unique=True, index=True)
    username: Optional[str] = Field(default=None, index=True, description="Telegram username who added this podcast")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    episodes: List["Episode"] = Relationship(back_populates="podcast")


class Episode(SQLModel, table=True):
    """SQLModel for podcast episodes."""
    id: str = Field(default=None, primary_key=True)
    title: str
    published: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    summary: Optional[str] = None
    link: str
    audio_url: Optional[str] = None
    transcript_url: Optional[str] = None
    transcript: Optional[str] = None
    transcript_link: Optional[str] = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    podcast_id: Optional[int] = Field(default=None, foreign_key="podcast.id")
    podcast: Optional[Podcast] = Relationship(back_populates="episodes")

    class Config:
        """Pydantic config."""
        arbitrary_types_allowed = True


class UserSubscription(SQLModel, table=True):
    """SQLModel for user subscriptions to specific podcasts."""
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, description="Telegram username")
    podcast_id: int = Field(foreign_key="podcast.id", index=True)
    subscribed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when the user subscribed"
    )
    is_active: bool = Field(
        default=True,
        description="Whether the subscription is active"
    )
    notification_preferences: str = Field(
        default="immediate",
        description="Notification preference: immediate, daily, weekly"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    class Config:
        """Pydantic config."""
        arbitrary_types_allowed = True


class ProcessedEpisode(SQLModel, table=True):
    """SQLModel for tracking which episodes have been processed and sent to users."""
    id: Optional[int] = Field(default=None, primary_key=True)
    episode_id: str = Field(foreign_key="episode.id", index=True)
    username: str = Field(index=True, description="Telegram username")
    processed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when the episode was processed"
    )
    summary_sent: bool = Field(
        default=False,
        description="Whether the summary was sent to the user"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    class Config:
        """Pydantic config."""
        arbitrary_types_allowed = True


class TranscriptionJob(SQLModel, table=True):
    """SQLModel for tracking transcription jobs.
    
    Attributes:
        job_name: Unique identifier for the transcription job
        audio_url: Original URL of the audio file
        s3_uri: S3 URI where the audio file is stored
        transcript_uri: S3 URI where the transcript will be stored
        status: Current status of the transcription job
        created_at: Timestamp when the job was created
        updated_at: Timestamp when the job was last updated
    """
    job_name: str = Field(primary_key=True)
    audio_url: str = Field(index=True)
    s3_uri: str = Field(description="S3 URI of the uploaded audio file")
    transcript_uri: Optional[str] = Field(
        default=None,
        description="S3 URI where the transcript will be stored"
    )
    status: str = Field(
        default="STARTED",
        description="Current status of the transcription job"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when the job was created"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when the job was last updated"
    )

    class Config:
        """Pydantic config."""
        arbitrary_types_allowed = True
