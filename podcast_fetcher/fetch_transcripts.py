"""Script to fetch transcripts for podcast episodes using AWS Transcribe."""
import os
import tempfile
import uuid
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import boto3
import requests
from dotenv import load_dotenv
from sqlmodel import Session, select

from podcast_fetcher.database import init_database
from podcast_fetcher.keys import Config
from podcast_fetcher.models import Episode, TranscriptionJob


def get_s3_client():
    """Initialize and return an S3 client."""
    c = Config()
    return boto3.client(
        's3',
        aws_access_key_id=c.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=c.AWS_SECRET_ACCESS_KEY,
        region_name=c.AWS_REGION
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
        c = Config()
        # Initialize the Transcribe client
        transcribe_client = boto3.client(
            'transcribe',
            region_name=region_name,
            aws_access_key_id=c.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=c.AWS_SECRET_ACCESS_KEY
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

def main():
    """Main function to process episodes and start transcription jobs."""
    print("Initializing database...")
    init_database()
    
    # Get S3 bucket name from environment variable
    output_bucket = Config().TRANSCRIPT_S3_BUCKET
    if not output_bucket:
        print("Error: TRANSCRIPT_S3_BUCKET not set")
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
                    bucket_name=Config().EPISODE_S3_BUCKET,
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

if __name__ == "__main__":
    main()
