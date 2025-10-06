# Podcast Fetcher

An intelligent podcast management system that automatically fetches, transcribes, and analyzes podcast episodes, delivering personalized summaries via Telegram bot. The system uses AI to understand content and provide users with relevant episode recommendations based on their interests.

## Features

This project solves the problem of podcast discovery and content consumption by:

- **Automatically fetching** new episodes from RSS feeds
- **Transcribing audio** using AWS services for searchable content
- **Analyzing transcripts** with AI to generate intelligent summaries
- **Delivering personalized recommendations** via Telegram bot
- **Managing user subscriptions** with flexible notification preferences
- **Providing proactive content discovery** based on user interests

## 🏗️ Project Structure

```
podcast-active-fetcher/
├── 📁 bot/                          # Telegram bot implementation
│   ├── main.py                     # Bot entry point (polling mode)
│   ├── webhook_bot.py              # Webhook-based bot for production
│   └── set_webhook.py              # Webhook configuration
├── 📁 podcast_fetcher/             # Core application logic
│   ├── models.py                   # Database models (Podcast, Episode, etc.)
│   ├── database.py                 # Database operations and queries
│   ├── config.py                   # Configuration settings
│   ├── rss_parser.py               # RSS feed parsing logic
│   ├── fetch_episodes.py           # Episode fetching from RSS
│   ├── fetch_transcripts.py        # Audio transcription services
│   ├── analyze_transcripts.py      # AI-powered content analysis
│   ├── process_transcripts.py      # Transcript processing pipeline
│   ├── add_podcast.py              # Podcast management CLI
│   ├── search_podcasts.py          # Podcast discovery via Taddy API
│   └── taddy_search.py             # Taddy API integration
├── 📁 data/                        # Local data storage
├── pyproject.toml                  # Project dependencies and config
└── README.md                       # This file
```

## 🚀 Key Features

### Core Functionality
- **RSS Feed Processing**: Automatically parses and extracts episode metadata
- **Audio Transcription**: Converts podcast audio to searchable text using AWS services
- **AI-Powered Analysis**: Generates intelligent summaries using Bedrock LLM
- **Database Management**: Stores episodes, transcripts, and user preferences in Supabase
- **Scheduled Processing**: Automated workflows via Modal cron jobs

### Telegram Bot Features
- **Smart Podcast Discovery**: Search and subscribe to podcasts via Taddy API
- **Flexible Notifications**: Choose between immediate, daily, or weekly summaries
- **Subscription Management**: Easy subscribe/unsubscribe with preference settings
- **Personalized Content**: AI-driven recommendations based on user interests

### Technical Architecture
- **Modular Design**: Clean separation of concerns with independent modules
- **Cloud-Native**: Built for Modal deployment with webhook support
- **Database Agnostic**: SQLModel-based ORM supporting multiple databases
- **API Integration**: Taddy for podcast discovery, AWS for transcription
- **Scalable Processing**: Handles multiple podcasts and users efficiently

## 🛠️ Getting Started

### Prerequisites
- Python 3.11.9+
- UV package manager
- Telegram Bot Token
- Supabase database
- AWS credentials (for transcription)
- Taddy API key (for podcast search)

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/podcast-active-fetcher.git
   cd podcast-active-fetcher
   ```

2. **Install dependencies:**
   ```bash
   uv sync
   ```

3. **Configure environment variables:**
   
   Create a `.env` file in the project root:
   ```bash
   cp .env.local .env
   # Edit .env with your configuration
   ```

### Usage Options

#### Option A: Run Individual Scripts
Execute scripts independently for testing and development:

```bash
# Add a new podcast
uv run python podcast_fetcher/add_podcast.py add

# List existing podcasts
uv run python podcast_fetcher/add_podcast.py list

# Fetch episodes for all podcasts
uv run python podcast_fetcher/fetch_episodes.py fetch --all

# Analyze transcripts and generate summaries
uv run python podcast_fetcher/analyze_transcripts.py
```

#### Option B: Use the Telegram Bot
Test the interactive bot at [@PodcastFetcherBot](https://t.me/PodcastFetcherBot)

**Bot Commands:**
- `/subscribe` - Search and subscribe to podcasts
- `/my_subscriptions` - View your current subscriptions
- `/unsubscribe` - Remove podcast subscriptions
- `/subscription_settings` - Configure notification preferences

#### Option C: Deploy to Modal
The system is designed to run on Modal with scheduled cron jobs for:
- Automatic episode fetching
- Transcript processing
- AI analysis and summarization
- User notification delivery

## 🔧 Configuration

### Environment Variables
```bash
# Database
DATABASE_URL=postgresql://user:pass@host:port/db

# Telegram Bot
TELEGRAM_BOT_TOKEN=your_bot_token

# AWS (for transcription)
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_REGION=us-east-1

# Taddy API (for podcast search)
TADDY_API_KEY=your_taddy_key
TADDY_USER_ID=your_user_id
```

## 📊 Database Schema

The system uses SQLModel with the following key models:

- **Podcast**: RSS feed information and metadata
- **Episode**: Individual episode data with transcripts
- **UserSubscription**: User podcast preferences and notification settings
- **ProcessedEpisode**: Tracking for user-specific episode processing
- **TranscriptionJob**: AWS transcription job status tracking

## 🚀 Future Developments

### Bot Intelligence
- [ ] **Proactive Recommendations**: AI-driven content discovery based on user listening history
- [ ] **Smart Filtering**: Automatically assess episode relevance before sending notifications

### Transcription Enhancements
- [ ] **Multi-language Support**: Transcribe podcasts in multiple languages (Investigate whether AWS Transcribe and/or other tools can accomplish this).
- [ ] **Speaker Diarization**: Use Pyannote or AWS tools for speaker identification - this would enhance the LLM context.


## 📄 License

MIT

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.