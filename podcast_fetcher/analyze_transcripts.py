
import argparse
from datetime import datetime, timezone
from typing import List, Tuple
import textwrap
from dotenv import load_dotenv
import os
import asyncio
from telethon import TelegramClient

from llama_index.llms.bedrock_converse import BedrockConverse
from podcast_fetcher.database import init_database, get_episodes_since
from podcast_fetcher.keys import Config
from podcast_fetcher.models import Episode

load_dotenv()

def format_summary(summary: str) -> str:
    """Format the summary with proper indentation for better readability."""
    return textwrap.indent(summary, '  ')

def generate_episode_summary(llm: BedrockConverse, episode: Episode) -> str:
    """Generate a summary for a single episode.
    
    Args:
        llm: Initialized BedrockConverse LLM instance
        episode: Episode to summarize
        
    Returns:
        str: Formatted summary with 3 bullet points
    """
    if not episode.transcript:
        return "  - No transcript available for this episode.\n"
    
    prompt = f"""Please provide a concise 3-bullet point summary of the following podcast transcript.
    Focus on the key insights, main topics, and important discussions.
    Each bullet point should be 1-2 sentences maximum.
    
    Title: {episode.title}
    Published: {episode.published.strftime('%Y-%m-%d')}
    
    Transcript:
    {episode.transcript[:8000]}... [truncated if necessary]
    
    Summary:
    - """
    
    try:
        response = llm.complete(prompt)
        return f"  - {response.text.strip()}\n"
    except Exception as e:
        return f"  - Error generating summary: {str(e)}\n"

def split_message(message: str, max_length: int = 4096) -> list[str]:
    """Split a message into chunks that don't exceed max_length.
    
    Args:
        message: The message to split
        max_length: Maximum length of each chunk
        
    Returns:
        List of message chunks
    """
    if len(message) <= max_length:
        return [message]
    
    # Split by double newlines to keep paragraphs together
    paragraphs = message.split('\n\n')
    chunks = []
    current_chunk = ""
    
    for paragraph in paragraphs:
        # If adding this paragraph would exceed the limit, start a new chunk
        if len(current_chunk) + len(paragraph) + 2 > max_length and current_chunk:
            chunks.append(current_chunk.strip())
            current_chunk = ""
        
        # Add paragraph to current chunk
        if current_chunk:
            current_chunk += '\n\n' + paragraph
        else:
            current_chunk = paragraph
    
    # Add the last chunk if not empty
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    return chunks

async def send_telegram_message(message: str, username: str = '@wiskkkk') -> None:
    """Send a message to a Telegram user, splitting it if necessary.
    
    Args:
        message: The message to send
        username: The Telegram username to send the message to (with @)
    """
    try:
        # Initialize the client
        c = Config()
        client = TelegramClient(
            'podcast_bot',
            c.TELEGRAM_APP_API_ID,
            c.TELEGRAM_APP_API_HASH
        )
        
        # Connect and authenticate
        await client.start(bot_token=c.TELEGRAM_BOT_TOKEN)
        
        # Split message if needed and send each chunk
        message_chunks = split_message(message)
        total_chunks = len(message_chunks)
        
        for i, chunk in enumerate(message_chunks, 1):
            # Add progress indicator if there are multiple chunks
            if total_chunks > 1:
                progress = f" ({i}/{total_chunks})"
            else:
                progress = ""
                
            await client.send_message(username, chunk, parse_mode='markdown')
            print(f"\nMessage part {i}{progress} sent to {username} successfully!")
        
        # Disconnect
        await client.disconnect()
    except Exception as e:
        print(f"\nError sending Telegram message: {str(e)}")
        if 'client' in locals() and client.is_connected():
            await client.disconnect()

def build_episode_message(episode: Episode, summary: str) -> str:
    """Build a formatted message for a single episode.
    
    Args:
        episode: The episode to format
        summary: The generated summary
        
    Returns:
        Formatted message string
    """
    message = f"🎧 *{episode.title}*\n"
    message += f"📅 {episode.published.strftime('%Y-%m-%d')}\n"
    message += f"🔗 {episode.link}\n\n"
    message += f"{summary}\n\n"
    return message

def analyze_episodes(days_ago: int = 7) -> Tuple[list[str], int]:
    """Analyze and summarize podcast episodes.
    
    Args:
        days_ago: Number of days to look back for episodes
        
    Returns:
        Tuple containing a list of message chunks and number of episodes processed
    """
    print(f"Analyzing podcast episodes from the last {days_ago} days...\n")
    
    # Initialize database and LLM
    engine = init_database()
    
    llm = BedrockConverse(
        model="us.amazon.nova-lite-v1:0",
        aws_access_key_id=c.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=c.AWS_SECRET_ACCESS_KEY,
        aws_session_token=c.AWS_SESSION_TOKEN,
        region_name=c.AWS_REGION,
    )
    
    # Get recent episodes
    episodes = get_episodes_since(engine, days_ago)
    
    if not episodes:
        msg = f"No episodes found from the last {days_ago} days."
        print(msg)
        return [msg], 0
    
    print(f"Found {len(episodes)} episode(s) from the last {days_ago} days.\n")
    
    # Start with a header
    messages = [f"🎙️ *Podcast Episode Summaries* (Last {days_ago} days)\n\n"]
    
    # Process each episode
    for i, episode in enumerate(episodes, 1):
        print(f"{i}. {episode.title}")
        print(f"   Published: {episode.published.strftime('%Y-%m-%d %H:%M')} UTC")
        
        # Generate summary
        summary = generate_episode_summary(llm, episode).strip()
        
        # Build episode message
        episode_message = build_episode_message(episode, summary)
        
        # Check if adding this episode would exceed the message limit
        if len(messages[-1]) + len(episode_message) > 4000:  # Leave some room for the footer
            messages.append("")  # Start a new message
        
        # Add to the last message in the list
        if messages[-1]:  # If not empty, add a separator
            messages[-1] += "\n" + "-" * 40 + "\n\n"
        messages[-1] += episode_message
        
        print(f"\nSummary:\n{summary}")
        print("-" * 80 + "\n")
    
    # Add footer to the last message
    if messages:
        messages[-1] += f"\n📊 *Total Episodes Processed:* {len(episodes)}"
    
    return messages, len(episodes)

def main(days_ago: int = 7):
    """Main function to analyze episodes and send summary via Telegram.
    
    Args:
        days_ago: Number of days to look back for episodes (default: 7)
    """
    # Analyze episodes and get message chunks
    message_chunks, num_episodes = analyze_episodes(days_ago)
    
    if num_episodes > 0:
        # Send all message chunks via Telegram
        asyncio.run(send_telegram_message("\n\n".join(message_chunks)))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Analyze and summarize podcast transcripts.')
    parser.add_argument('--days', type=int, default=7,
                      help='Number of days to look back for episodes (default: 7)')
    args = parser.parse_args()
    
    main(days_ago=args.days)