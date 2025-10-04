import os
import sys
import asyncio
import logging
import httpx
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set up basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def set_webhook(webhook_url: str):
    """
    Set the Telegram webhook URL using the Telegram Bot API.
    
    Args:
        webhook_url: The webhook URL to set for the bot
        
    Returns:
        dict: Response with status and message
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    
    if not bot_token:
        return {"error": "TELEGRAM_BOT_TOKEN not found. Check your .env file or environment variables."}

    if not webhook_url:
        return {"error": "Webhook URL must be provided"}

    # Ensure URL ends with /
    full_webhook_url = f"{webhook_url}/" if not webhook_url.endswith('/') else webhook_url 

    # Use httpx to call the Telegram Bot API asynchronously
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.telegram.org/bot{bot_token}/setWebhook",
            params={
                "url": full_webhook_url,
                "drop_pending_updates": True
            }
        )

    response_data = response.json()
    logger.info(f"Telegram setWebhook response: {response_data}")

    if response.status_code == 200 and response_data.get("ok"):
        return {"status": "success", "message": f"Webhook successfully set to {full_webhook_url}"}
    else:
        return {"status": "error", "message": "Failed to set webhook", "details": response_data}


async def main():
    """Main function to handle command line arguments and set webhook."""
    if len(sys.argv) != 2:
        print("Usage: python set_webhook.py <webhook_url>")
        print("Example: python set_webhook.py https://your-domain.com/webhook")
        sys.exit(1)
    
    webhook_url = sys.argv[1]
    
    logger.info(f"Setting webhook to: {webhook_url}")
    result = await set_webhook(webhook_url)
    
    if result.get("status") == "success":
        print(f"✅ {result['message']}")
        sys.exit(0)
    else:
        print(f"❌ {result.get('message', 'Unknown error')}")
        if result.get("details"):
            print(f"Details: {result['details']}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
