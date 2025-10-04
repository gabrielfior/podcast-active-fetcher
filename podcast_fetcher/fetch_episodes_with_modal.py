import os
import uuid
import tempfile
import requests
import boto3
import json
from urllib.parse import urlparse
from typing import List, Optional, Tuple, Dict, Any
import modal
from datetime import datetime, timedelta, timezone
from sqlmodel import Session, select
from sqlalchemy import and_
from dotenv import load_dotenv

load_dotenv()

from podcast_fetcher.database import (
    init_database, get_user_subscriptions, get_podcast_subscribers,
    is_episode_processed_for_user, mark_episode_processed
)
from podcast_fetcher.models import Episode, Podcast, TranscriptionJob, UserSubscription
from podcast_fetcher.rss_parser import get_episodes_since
from podcast_fetcher.analyze_transcripts import generate_episode_summary, send_telegram_message

app = modal.App("podcast-fetcher")




image = (
    modal.Image.debian_slim(python_version="3.11.9")
    .uv_pip_install("sqlmodel>=0.0.24", "beautifulsoup4>=4.13.4", "feedparser>=6.0.11", "python-dotenv>=1.1.1", "loguru>=0.7.1", "psycopg>=3.2.9", "requests>=2.31.0", "python-dateutil>=2.8.2", "psycopg2-binary>=2.9.10", "boto3>=1.34.0", "telethon>=1.35.0", "llama-index>=0.13.2", "llama-index-llms-bedrock-converse>=0.8.2")
    .add_local_python_source("podcast_fetcher")
)


@app.function(schedule=modal.Cron("0 */12 * * *"), image=image,
              secrets=[modal.Secret.from_name("podcast-fetcher-secrets")])
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


def get_s3_client():
    """Initialize and return an S3 client."""
    return boto3.client(
        's3',
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        region_name='us-east-1'
    )

def download_audio(audio_url: str) -> Optional[Tuple[str, str]]:
    """
    Download an audio file from a URL to a temporary file.
    
    Args:
        audio_url: URL of the audio file to download
        
    Returns:
        Tuple of (temp_file_path, file_extension) if successful, None otherwise
    """
    try:
        # Get the file extension from the URL
        parsed_url = urlparse(audio_url)
        file_ext = os.path.splitext(parsed_url.path)[1].lstrip('.')
        if not file_ext:
            file_ext = 'mp3'  # Default extension if not in URL
            
        # Create a temporary file
        with tempfile.NamedTemporaryFile(suffix=f".{file_ext}", delete=False) as temp_file:
            # Download the file
            response = requests.get(audio_url, stream=True)
            response.raise_for_status()
            
            # Write the content to the temporary file
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    temp_file.write(chunk)
            
            return temp_file.name, file_ext
            
    except Exception as e:
        print(f"Error downloading audio from {audio_url}: {e}")
        return None

def upload_to_s3(file_path: str, bucket_name: str, object_name: str) -> Optional[str]:
    """
    Upload a file to an S3 bucket.
    
    Args:
        file_path: Path to the file to upload
        bucket_name: Name of the S3 bucket
        object_name: S3 object name (key)
        
    Returns:
        S3 URI if successful, None otherwise
    """
    try:
        s3_client = get_s3_client()
        s3_client.upload_file(file_path, bucket_name, object_name)
        return f"s3://{bucket_name}/{object_name}"
    except Exception as e:
        print(f"Error uploading to S3: {e}")
        return None

def transcribe_episode(audio_uri: str, output_bucket_name: str, output_key: str, region_name: str = 'us-east-1') -> Optional[str]:
    """
    Start a transcription job for the given S3 audio URI.
    
    Args:
        audio_uri: S3 URI of the audio file to transcribe (e.g., 's3://bucket-name/object-key')
        output_bucket_name: S3 bucket to store the transcript
        output_key: S3 key where the transcript will be stored (e.g., 'transcripts/123.json')
        region_name: AWS region to use
        
    Returns:
        Job name if successful, None otherwise
    """
    try:
        # Initialize the Transcribe client
        transcribe_client = boto3.client(
            'transcribe',
            region_name=region_name,
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
        )
        
        # Generate a unique job name
        job_name = f"transcription-{uuid.uuid4()}"
        
        # Extract the media format from the URI
        media_format = audio_uri.split('.')[-1].lower()
        if media_format not in ['mp3', 'mp4', 'wav', 'flac', 'ogg', 'amr', 'webm']:
            print(f"Unsupported media format: {media_format}")
            return None

        print(f"Starting transcription job: {job_name} for {audio_uri}")
        
        # Start the transcription job
        transcribe_client.start_transcription_job(
            TranscriptionJobName=job_name,
            Media={'MediaFileUri': audio_uri},
            MediaFormat=media_format,
            LanguageCode='en-US',
            OutputBucketName=output_bucket_name,
            OutputKey=output_key,
            Settings={
                'ShowSpeakerLabels': True,
                'MaxSpeakerLabels': 2,
                'ChannelIdentification': False
            }
        )
        
        return job_name
        
    except Exception as e:
        print(f"Error starting transcription job: {e}")
        return None

def get_episodes_needing_transcripts() -> List[Episode]:
    """
    Get all episodes that need transcripts.
    
    Returns:
        List of Episode objects that don't have transcripts
    """
    engine = init_database()    
    with Session(engine) as session:
        statement = select(Episode).where(Episode.transcript.is_(None))
        return session.exec(statement).all()


@app.function(schedule=modal.Cron("5 */12 * * *"), image=image,
              secrets=[modal.Secret.from_name("podcast-fetcher-secrets")])
def fetch_transcripts():
    """Fetch transcripts for podcast episodes using AWS Transcribe."""
    print("Starting transcript fetch on Modal...")
    
    # Get S3 bucket name from environment variable
    output_bucket = os.getenv('TRANSCRIPT_S3_BUCKET')
    if not output_bucket:
        print("Error: TRANSCRIPT_S3_BUCKET environment variable not set")
        return
    
    # Get episodes that need transcripts
    episodes = get_episodes_needing_transcripts()
    print(f"Found {len(episodes)} episodes needing transcripts")
    
    if not episodes:
        print("No episodes need transcription.")
        return
    
    # Process each episode
    engine = init_database()    
    with Session(engine) as session:
        for episode in episodes:
            if not episode.audio_url:
                print(f"Skipping episode {episode.id}: No audio URL")
                continue
                
            print(f"Processing episode: {episode.title}")
            print(f"  Audio URL: {episode.audio_url}")
            
            # Download the audio file
            download_result = download_audio(episode.audio_url)
            if not download_result:
                print(f"  Failed to download audio from {episode.audio_url}")
                continue
                
            temp_file_path, file_ext = download_result
            
            try:
                # Generate a unique S3 object key
                object_key = f"episodes/{episode.id}.{file_ext}"
                
                # Upload to S3
                s3_uri = upload_to_s3(
                    file_path=temp_file_path,
                    bucket_name=os.getenv('EPISODE_S3_BUCKET'),
                    object_name=object_key
                )
                
                if not s3_uri:
                    print(f"  Failed to upload audio to S3")
                    continue
                    
                print(f"  Uploaded audio to {s3_uri}")
                
                # Generate the transcript URI
                transcript_uri = f"s3://{output_bucket}/transcripts/{episode.id}.json"
                
                # Start transcription job with S3 URI
                job_name = transcribe_episode(
                    audio_uri=s3_uri,
                    output_bucket_name=output_bucket,
                    output_key=f"transcripts/{episode.id}.json"
                )
                
                if job_name:
                    # Create a new transcription job record
                    job = TranscriptionJob(
                        job_name=job_name,
                        audio_url=episode.audio_url,
                        s3_uri=s3_uri,
                        transcript_uri=transcript_uri,
                        status="STARTED"
                    )
                    session.add(job)
                    session.commit()
                    print(f"  Started transcription job: {job_name}")
                else:
                    print(f"  Failed to start transcription job")
                    
            except Exception as e:
                print(f"  Error processing episode: {e}")
                
            finally:
                # Clean up the temporary file
                try:
                    os.unlink(temp_file_path)
                except Exception as e:
                    print(f"  Warning: Could not delete temporary file {temp_file_path}: {e}")
    
    print("\nAll transcription jobs have been started.")


def extract_transcript_text(transcript_data: Dict[str, Any]) -> str:
    """Extract the transcript text from the AWS Transcribe JSON output.
    
    Args:
        transcript_data: The parsed JSON from the transcript file
        
    Returns:
        The full transcript as a single string
    """
    try:
        # Extract all the transcript segments
        items = transcript_data.get('results', {}).get('transcripts', [])
        if not items:
            return ""
        
        # Join all transcript segments with spaces
        return " ".join([item.get('transcript', '') for item in items])
    except Exception as e:
        print(f"Error extracting transcript: {e}")
        return ""


@app.function(schedule=modal.Cron("20 */12 * * *"), image=image,
              secrets=[modal.Secret.from_name("podcast-fetcher-secrets")])
def process_completed_transcripts():
    """Process all transcription jobs that are marked as STARTED but not COMPLETED."""
    print("Starting transcript processing on Modal...")
    
    # Initialize database and S3 client
    engine = init_database()
    s3_client = get_s3_client()
    
    # Get the S3 bucket name from environment variable
    bucket_name = os.getenv('TRANSCRIPT_S3_BUCKET')
    if not bucket_name:
        print("Error: TRANSCRIPT_S3_BUCKET environment variable not set")
        return
    
    with Session(engine) as session:
        # Find all jobs that are not COMPLETED
        statement = select(TranscriptionJob).where(
            TranscriptionJob.status != "COMPLETED"
        )
        jobs = session.exec(statement).all()
        
        if not jobs:
            print("No completed jobs to process.")
            return
        
        print(f"Found {len(jobs)} completed jobs to process.")
        
        for job in jobs:
            try:
                if not job.transcript_uri:
                    print(f"No transcript URI for job {job.job_name}")
                    continue
                
                # Extract the S3 key from the transcript_uri
                # Format: s3://bucket-name/key
                s3_key = job.transcript_uri.split('/', 3)[-1]
                
                # Download the transcript file
                try:
                    response = s3_client.get_object(Bucket=bucket_name, Key=s3_key)
                    transcript_data = json.loads(response['Body'].read().decode('utf-8'))
                except Exception as e:
                    print(f"Error downloading transcript for job {job.job_name}: {e}")
                    continue
                
                # Extract the transcript text
                transcript_text = extract_transcript_text(transcript_data)
                
                if not transcript_text:
                    print(f"No transcript text found for job {job.job_name}")
                    continue
                
                # Find the episode by audio URL
                episode = session.exec(
                    select(Episode).where(Episode.audio_url == job.audio_url)
                ).first()
                
                if not episode:
                    print(f"No episode found for audio URL: {job.audio_url}")
                    continue
                
                # Update the episode with transcript and transcript URL
                episode.transcript = transcript_text
                episode.transcript_url = job.transcript_uri
                
                # Mark the job as COMPLETED
                job.status = "COMPLETED"
                
                # Commit the changes
                session.add(episode)
                session.add(job)
                session.commit()
                
                print(f"Updated episode {episode.id} with transcript from job {job.job_name}")
                
            except Exception as e:
                print(f"Error processing job {job.job_name}: {e}")
                session.rollback()
    
    print("Transcript processing complete.")


# Additional Modal functions for different scheduling scenarios

@app.function(schedule=modal.Cron("25 */6 * * *"), image=image,
              secrets=[modal.Secret.from_name("podcast-fetcher-secrets")])
def process_all_notifications():
    """Process all types of notifications: immediate, daily, and weekly."""
    print("Starting unified notification processing on Modal...")
    
    engine = init_database()
    
    with Session(engine) as session:
        # Process immediate notifications
        print("Processing immediate notifications...")
        process_immediate_notifications_logic(engine, session)
        
        # Process daily digest (only if it's 9 AM)
        current_hour = datetime.now(timezone.utc).hour
        if current_hour == 9:
            print("Processing daily digest...")
            process_daily_digest_logic(engine, session)
        
        # Process weekly digest (only if it's Monday 9 AM)
        current_weekday = datetime.now(timezone.utc).weekday()  # 0 = Monday
        if current_weekday == 0 and current_hour == 9:
            print("Processing weekly digest...")
            process_weekly_digest_logic(engine, session)
    
    print("Unified notification processing complete.")


def process_immediate_notifications_logic(engine, session):
    """Process immediate notifications for users with 'immediate' preference."""
    # Get users with immediate notification preference
    statement = select(UserSubscription).where(
        and_(
            UserSubscription.is_active == True,
            UserSubscription.notification_preferences == "immediate"
        )
    )
    immediate_subscriptions = session.exec(statement).all()
    
    if not immediate_subscriptions:
        print("No users with immediate notification preference found.")
        return
    
    print(f"Found {len(immediate_subscriptions)} immediate notification subscriptions")
    
    # Group by podcast
    podcast_subscriptions = {}
    for subscription in immediate_subscriptions:
        if subscription.podcast_id not in podcast_subscriptions:
            podcast_subscriptions[subscription.podcast_id] = []
        podcast_subscriptions[subscription.podcast_id].append(subscription.username)
    
    total_processed = 0
    total_notifications = 0
    total_errors = 0
    
    # Process each podcast
    for podcast_id, usernames in podcast_subscriptions.items():
        try:
            # Get podcast info
            podcast = session.get(Podcast, podcast_id)
            if not podcast:
                continue
            
            print(f"Processing immediate notifications for: {podcast.title}")
            
            # Get episodes from database that have transcripts and haven't been processed
            since_date = datetime.now(timezone.utc) - timedelta(days=2)
            episodes = session.exec(
                select(Episode).where(
                    and_(
                        Episode.podcast_id == podcast_id,
                        Episode.published >= since_date,
                        Episode.transcript.isnot(None)
                    )
                )
            ).all()
            
            if not episodes:
                print(f"  No episodes with transcripts found for {podcast.title}")
                continue
            
            print(f"  Found {len(episodes)} episodes with transcripts")
            
            # Process each episode
            for episode in episodes:
                try:
                    # Process for each subscriber
                    for username in usernames:
                        if not is_episode_processed_for_user(engine, episode.id, username):
                            success = process_episode_for_user(engine, episode, username)
                            if success:
                                mark_episode_processed(engine, episode.id, username, True)
                                total_notifications += 1
                                print(f"    Sent immediate notification to {username} for: {episode.title}")
                            else:
                                total_errors += 1
                                print(f"    Failed to send immediate notification to {username} for: {episode.title}")
                    
                    total_processed += 1
                    
                except Exception as e:
                    print(f"  Error processing episode {episode.title}: {e}")
                    total_errors += 1
                    
        except Exception as e:
            print(f"Error processing podcast {podcast.title}: {e}")
            total_errors += 1
    
    print(f"Immediate notifications: {total_processed} processed, {total_notifications} sent, {total_errors} errors")


def process_daily_digest_logic(engine, session):
    """Process daily digest for users with 'daily' notification preference."""
    # Get users with daily notification preference
    statement = select(UserSubscription).where(
        and_(
            UserSubscription.is_active == True,
            UserSubscription.notification_preferences == "daily"
        )
    )
    daily_subscriptions = session.exec(statement).all()
    
    if not daily_subscriptions:
        print("No users with daily notification preference found.")
        return
    
    print(f"Found {len(daily_subscriptions)} daily digest subscriptions")
    
    # Group by username
    user_episodes = {}
    for subscription in daily_subscriptions:
        username = subscription.username
        if username not in user_episodes:
            user_episodes[username] = []
        
        # Get episodes from the last 24 hours for this podcast
        since_date = datetime.now(timezone.utc) - timedelta(days=1)
        episodes = session.exec(
            select(Episode).where(
                and_(
                    Episode.podcast_id == subscription.podcast_id,
                    Episode.published >= since_date,
                    Episode.transcript.isnot(None)
                )
            )
        ).all()
        
        for episode in episodes:
            if not is_episode_processed_for_user(engine, episode.id, username):
                user_episodes[username].append(episode)
    
    # Send digest to each user
    total_sent = 0
    for username, episodes in user_episodes.items():
        if episodes:
            digest_message = format_daily_digest(username, episodes)
            success = send_telegram_notification_sync(username, digest_message)
            if success:
                # Mark episodes as processed
                for episode in episodes:
                    mark_episode_processed(engine, episode.id, username, True)
                total_sent += 1
                print(f"  Sent daily digest to {username} with {len(episodes)} episodes")
    
    print(f"Daily digest complete: {total_sent} digests sent")


def process_weekly_digest_logic(engine, session):
    """Process weekly digest for users with 'weekly' notification preference."""
    # Get users with weekly notification preference
    statement = select(UserSubscription).where(
        and_(
            UserSubscription.is_active == True,
            UserSubscription.notification_preferences == "weekly"
        )
    )
    weekly_subscriptions = session.exec(statement).all()
    
    if not weekly_subscriptions:
        print("No users with weekly notification preference found.")
        return
    
    print(f"Found {len(weekly_subscriptions)} weekly digest subscriptions")
    
    # Group by username
    user_episodes = {}
    for subscription in weekly_subscriptions:
        username = subscription.username
        if username not in user_episodes:
            user_episodes[username] = []
        
        # Get episodes from the last 7 days for this podcast
        since_date = datetime.now(timezone.utc) - timedelta(days=7)
        episodes = session.exec(
            select(Episode).where(
                and_(
                    Episode.podcast_id == subscription.podcast_id,
                    Episode.published >= since_date,
                    Episode.transcript.isnot(None)
                )
            )
        ).all()
        
        for episode in episodes:
            if not is_episode_processed_for_user(engine, episode.id, username):
                user_episodes[username].append(episode)
    
    # Send digest to each user
    total_sent = 0
    for username, episodes in user_episodes.items():
        if episodes:
            digest_message = format_weekly_digest(username, episodes)
            success = send_telegram_notification_sync(username, digest_message)
            if success:
                # Mark episodes as processed
                for episode in episodes:
                    mark_episode_processed(engine, episode.id, username, True)
                total_sent += 1
                print(f"  Sent weekly digest to {username} with {len(episodes)} episodes")
    
    print(f"Weekly digest complete: {total_sent} digests sent")


def process_episode_for_user(engine, episode: Episode, username: str) -> bool:
    """Process an episode for a specific user and send notification.
    
    Args:
        engine: Database engine
        episode: Episode to process
        username: Username to send notification to
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Only process if episode has transcript
        if not episode.transcript:
            print(f"    No transcript available for episode: {episode.title}")
            return False
        
        # Initialize LLM for summary generation
        from llama_index.llms.bedrock_converse import BedrockConverse
        
        llm = BedrockConverse(
            model="us.amazon.nova-lite-v1:0",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
            region_name=os.getenv("AWS_REGION"),
        )
        
        # Generate summary
        summary = generate_episode_summary(llm, episode)
        
        # Format notification message
        message = format_episode_notification(episode, summary)
        
        # Send notification via Telegram
        success = send_telegram_notification_sync(username, message)
        if success:
            print(f"    Sent notification to {username} for: {episode.title}")
        else:
            print(f"    Failed to send notification to {username}")
        
        return success
        
    except Exception as e:
        print(f"    Error processing episode for user {username}: {e}")
        return False


def format_episode_notification(episode: Episode, summary: str) -> str:
    """Format episode notification message.
    
    Args:
        episode: Episode to format
        summary: Generated summary
        
    Returns:
        Formatted message string
    """
    message = f"🎧 *New Episode Available!*\n\n"
    message += f"📻 **{episode.podcast.title if episode.podcast else 'Unknown Podcast'}**\n"
    message += f"📺 **{episode.title}**\n"
    message += f"📅 {episode.published.strftime('%Y-%m-%d')}\n"
    message += f"🔗 {episode.link}\n\n"
    message += f"**Summary:**\n{summary}\n\n"
    message += f"---\n"
    message += f"*You're receiving this because you're subscribed to this podcast.*"
    
    return message


def send_telegram_notification_sync(username: str, message: str) -> bool:
    """Send a Telegram notification synchronously (for use in Modal).
    
    Args:
        username: Telegram username to send to
        message: Message to send
        
    Returns:
        True if successful, False otherwise
    """
    try:
        import asyncio
        from telethon import TelegramClient
        
        # Initialize the client
        client = TelegramClient(
            'podcast_bot',
            int(os.getenv('TELEGRAM_APP_API_ID')),
            os.getenv('TELEGRAM_APP_API_HASH')
        )
        
        # Run the async function
        async def send_message():
            await client.start(bot_token=os.getenv('TELEGRAM_BOT_TOKEN'))
            await client.send_message(f"@{username}", message, parse_mode='markdown')
            await client.disconnect()
        
        # Execute the async function
        asyncio.run(send_message())
        return True
        
    except Exception as e:
        print(f"Error sending Telegram notification to {username}: {e}")
        return False


def format_daily_digest(username: str, episodes: List[Episode]) -> str:
    """Format daily digest message.
    
    Args:
        username: Username to send digest to
        episodes: List of episodes to include in digest
        
    Returns:
        Formatted digest message
    """
    message = f"📰 *Daily Podcast Digest*\n\n"
    message += f"Hello @{username}! Here are the new episodes from your subscribed podcasts:\n\n"
    
    # Group episodes by podcast
    podcast_episodes = {}
    for episode in episodes:
        podcast_title = episode.podcast.title if episode.podcast else "Unknown Podcast"
        if podcast_title not in podcast_episodes:
            podcast_episodes[podcast_title] = []
        podcast_episodes[podcast_title].append(episode)
    
    for podcast_title, podcast_episodes_list in podcast_episodes.items():
        message += f"📻 **{podcast_title}**\n"
        for episode in podcast_episodes_list:
            message += f"  • {episode.title} ({episode.published.strftime('%Y-%m-%d')})\n"
            message += f"    🔗 {episode.link}\n"
        message += "\n"
    
    message += f"---\n"
    message += f"*You're receiving this daily digest because you're subscribed to these podcasts.*"
    
    return message


def format_weekly_digest(username: str, episodes: List[Episode]) -> str:
    """Format weekly digest message.
    
    Args:
        username: Username to send digest to
        episodes: List of episodes to include in digest
        
    Returns:
        Formatted digest message
    """
    message = f"📰 *Weekly Podcast Digest*\n\n"
    message += f"Hello @{username}! Here's your weekly roundup of new episodes:\n\n"
    
    # Group episodes by podcast
    podcast_episodes = {}
    for episode in episodes:
        podcast_title = episode.podcast.title if episode.podcast else "Unknown Podcast"
        if podcast_title not in podcast_episodes:
            podcast_episodes[podcast_title] = []
        podcast_episodes[podcast_title].append(episode)
    
    for podcast_title, podcast_episodes_list in podcast_episodes.items():
        message += f"📻 **{podcast_title}** ({len(podcast_episodes_list)} episodes)\n"
        for episode in podcast_episodes_list:
            message += f"  • {episode.title} ({episode.published.strftime('%Y-%m-%d')})\n"
            message += f"    🔗 {episode.link}\n"
        message += "\n"
    
    message += f"---\n"
    message += f"*You're receiving this weekly digest because you're subscribed to these podcasts.*"
    
    return message


if __name__ == "__main__":
   app.deploy()