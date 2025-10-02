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


class UpdateFrequency(SQLModel, table=True):
    """SQLModel for storing user update frequency preferences."""
    username: str = Field(primary_key=True, description="Telegram username")
    frequency_in_days: int = Field(description="Update frequency in days")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when the preference was created"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when the preference was last updated"
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
