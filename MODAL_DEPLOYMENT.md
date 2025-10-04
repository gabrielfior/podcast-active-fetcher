# Modal Deployment for Telegram Podcast Bot

This guide explains how to deploy the Telegram podcast bot as a long-running service on Modal.

## Prerequisites

1. **Modal Account**: Sign up at [modal.com](https://modal.com)
2. **Telegram Bot Token**: Create a bot via [@BotFather](https://t.me/botfather)
3. **Taddy API Access**: Get API key from [Taddy](https://taddy.org)

## Quick Start

### 1. Install Modal

```bash
pip install modal
```

### 2. Authenticate with Modal

```bash
modal token new
```

### 3. Set up Secrets

Create a Modal secret with your bot credentials:

```bash
modal secret create telegram-bot-secrets
```

Add these variables when prompted:
- `TELEGRAM_BOT_TOKEN`: Your Telegram bot token
- `TADDY_API_KEY`: Your Taddy API key  
- `TADDY_USER_ID`: Your Taddy user ID
- `SQLALCHEMY_DATABASE_URI`: (Optional) Database connection string

### 4. Deploy the Bot

```bash
# Deploy the bot
modal deploy bot/modal_bot.py

# Run the bot
modal run bot/modal_bot.py::run_telegram_bot_with_volume
```

## Manual Deployment

### 1. Deploy the App

```bash
modal deploy bot/modal_bot.py
```

### 2. Run the Bot

```bash
# With persistent storage (recommended)
modal run bot/modal_bot.py::run_telegram_bot_with_volume

# Without persistent storage
modal run bot/modal_bot.py::run_telegram_bot
```

## Using the Deployment Script

The `deploy_bot.py` script automates the deployment process:

```bash
python deploy_bot.py
```

This script will:
1. Check if Modal is installed and authenticated
2. Guide you through secret setup
3. Deploy the bot
4. Optionally start the bot

## Configuration

### Environment Variables

The bot uses these environment variables:

- `TELEGRAM_BOT_TOKEN`: Required - Your Telegram bot token
- `TADDY_API_KEY`: Required - Your Taddy API key
- `TADDY_USER_ID`: Required - Your Taddy user ID
- `SQLALCHEMY_DATABASE_URI`: Optional - Database connection (defaults to SQLite)

### Modal Configuration

The bot is configured with:
- **CPU**: 1.0 cores
- **Memory**: 1GB
- **Timeout**: 1 hour
- **Keep Warm**: 1 instance (for faster startup)
- **Volume**: Persistent storage for database

## Monitoring

### View Logs

```bash
modal app logs telegram-podcast-bot
```

### Check Status

```bash
modal app list
```

### Stop the Bot

```bash
modal app stop telegram-podcast-bot
```

## Database Storage

The bot uses a persistent volume for database storage:
- **Volume Name**: `podcast-bot-data`
- **Database Path**: `/data/podcast_episodes.db`

This ensures your bot's data persists across restarts.

## Troubleshooting

### Common Issues

1. **Authentication Error**: Make sure you're logged in to Modal
   ```bash
   modal token current
   ```

2. **Secret Not Found**: Ensure the secret is created with the correct name
   ```bash
   modal secret list
   ```

3. **Import Errors**: Check that all dependencies are included in the Modal image

4. **Database Issues**: Verify the database URI is correct and accessible

### Debug Mode

Run the bot locally for debugging:

```bash
# Set environment variables
export TELEGRAM_BOT_TOKEN="your_token"
export TADDY_API_KEY="your_key"
export TADDY_USER_ID="your_user_id"

# Run locally
python bot/main.py
```

## Scaling

The bot is configured to keep one instance warm for fast response times. For high-traffic scenarios, you can:

1. Increase the `keep_warm` parameter
2. Use Modal's auto-scaling features
3. Deploy multiple instances

## Security

- All secrets are encrypted in Modal
- Database is stored in a private volume
- No sensitive data is logged

## Cost Optimization

- The bot uses minimal resources (1 CPU, 1GB RAM)
- Keep-warm instances may incur small costs
- Consider using scheduled functions for non-critical operations

## Support

For issues with:
- **Modal**: Check [Modal documentation](https://modal.com/docs)
- **Telegram Bot**: Check [python-telegram-bot docs](https://python-telegram-bot.readthedocs.io/)
- **This Bot**: Check the main README.md
