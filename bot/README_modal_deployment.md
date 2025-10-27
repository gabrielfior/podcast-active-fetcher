# Modal Deployment for aiogram Telegram Bot

This directory contains the Modal deployment for the aiogram-based Telegram bot using the `@modal.web_server` decorator.

## Files

- `modal_aiogram_bot.py` - Main Modal deployment script with `@modal.web_server` decorator
- `deploy_aiogram_modal.py` - Deployment helper script
- `bot_aiogram.py` - Original aiogram bot (for local development)

## Key Differences from Original

The Modal deployment (`modal_aiogram_bot.py`) differs from the original `bot_aiogram.py` in these important ways:

1. **Host Binding**: Uses `0.0.0.0` instead of `127.0.0.1` (required for Modal)
2. **Modal Decorators**: Uses `@modal.web_server(8000)` decorator
3. **Environment**: Runs inside Modal's container environment
4. **Dependencies**: All dependencies are installed via Modal's image system

## Deployment

### Prerequisites

1. Install Modal CLI:
   ```bash
   pip install modal
   ```

2. Set up Modal authentication:
   ```bash
   modal token new
   ```

3. Create Modal secrets for your bot token:
   ```bash
   modal secret create podcast-fetcher-secrets TELEGRAM_BOT_TOKEN=your_bot_token_here
   ```

### Deploy the Bot

Run the deployment script:
```bash
python bot/deploy_aiogram_modal.py
```

Or deploy manually:
```bash
modal deploy bot/modal_aiogram_bot.py
```

### Set Webhook URL

After deployment, you'll get a Modal app URL like:
```
https://your-username--aiogram-telegram-bot-aiogram-bot.modal.run/
```

Use this URL to set your Telegram bot's webhook:
```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
     -H "Content-Type: application/json" \
     -d '{"url": "https://your-username--aiogram-telegram-bot-aiogram-bot.modal.run/"}'
```

## Local Testing

You can test the bot locally before deploying:

```bash
# Make sure you have your .env file with TELEGRAM_BOT_TOKEN
python bot/modal_aiogram_bot.py
```

## Bot Commands

The deployed bot supports these commands:

- `/start` - Welcome message
- `/chat <message>` - Chat with the podcast agent
- Any other message - Echo handler (for testing)

## Architecture

```
Telegram → Modal App (aiogram bot) → podcast_fetcher modules
```

The bot uses:
- **aiogram** for Telegram bot framework
- **aiohttp** for web server (via aiogram's webhook support)
- **Modal** for cloud deployment with `@modal.web_server`
- **podcast_fetcher** modules for AI agent functionality

## Monitoring

View logs and monitor the deployment:
```bash
modal app logs aiogram-telegram-bot
```

## Troubleshooting

1. **Bot not responding**: Check that the webhook URL is set correctly
2. **Import errors**: Ensure all dependencies are in the Modal image
3. **Connection issues**: Verify the bot is binding to `0.0.0.0:8000`

## Development

For local development, use the original `bot_aiogram.py`:
```bash
python bot/bot_aiogram.py
```

For production deployment, use the Modal version with the deployment script.
