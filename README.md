# Podcast Fetcher

A Python tool to fetch and store podcast episodes from RSS feeds, including metadata and transcripts.

## Features

- Fetches podcast episodes from RSS feeds
- Extracts episode metadata (title, published date, description, etc.)
- Downloads audio and transcript URLs when available
- Stores episodes in a local SQLite database
- Prevents duplicate entries
- Modular and extensible architecture

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/podcast-fetcher.git
   cd podcast-fetcher
   ```

2. Install the package in development mode:
   ```bash
   uv pip install -e .
   ```

3. Install development dependencies (optional):
   ```bash
   uv pip install -e ".[dev]"
   ```

## Usage

### Basic Usage

```bash
python -m podcast_fetcher.main
```

### Configuration

Create a `.env` file in the project root to customize settings:

```env
# Required
RSS_FEED=https://example.com/podcast/feed

# Optional
DB_PATH=sqlite:///path/to/your/database.db
```

## Project Structure

```
podcast_fetcher/
├── __init__.py         # Package initialization
├── config.py          # Configuration settings
├── database.py        # Database operations
├── models.py          # SQLModel definitions
├── rss_parser.py      # RSS feed parsing
└── main.py            # Main entry point
```

## Development

### Running Tests

```bash
pytest
```

### Code Formatting

```bash
black .
isort .
```

### Type Checking

```bash
mypy .
```

## License

MIT

### ToDos

Bot
- [ ] Run bot continously, reply to messages
- [ ] User should be able to register podcast series (store user in the table) (new bot function, /register)
- [ ] User should be able to get on-demand reviews from episodes from last N days (new bot function, /summaries N)

Data processing
- [ ] Schedule episode fetching every N days (using AWS)
- [ ] Schedule transcripts of episodes every N days (using AWS)

Language
- [ ] It can only process english podcast episodes. Try to use a multi-language model.

Next steps
- [ ] Use Pyannote to create diarization output instead of a simple transcript from AWS Textract (https://docs.pyannote.ai/api-reference/diarize).