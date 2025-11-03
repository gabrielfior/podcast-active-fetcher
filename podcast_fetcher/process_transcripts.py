"""Script to process completed transcriptions from S3 and update the database."""
import json
from typing import Any, Dict, Optional

import boto3
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

def process_completed_jobs() -> None:
    """Process all transcription jobs that are marked as STARTED but not COMPLETED."""
    # Initialize database and S3 client
    engine = init_database()
    s3_client = get_s3_client()
    
    # Get the S3 bucket name from environment variable
    bucket_name = Config().TRANSCRIPT_S3_BUCKET
    if not bucket_name:
        print("Error: TRANSCRIPT_S3_BUCKET not set")
        return
    
    with Session(engine) as session:
        # Find all jobs that are COMPLETED but not marked as DONE
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

def main():
    """Main function to process completed transcriptions."""
    print("Starting transcription processing...")
    process_completed_jobs()
    print("Processing complete.")

if __name__ == "__main__":
    main()
