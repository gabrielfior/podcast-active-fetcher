import os
import logging
import modal
import uvicorn
import httpx
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from http import HTTPStatus
from typing import Dict, Any

from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes
from fastapi import FastAPI, Request, Response

# --- MODAL IMPORTS ---

# --- 1. Environment Setup & Logging ---
# Load environment variables for local testing (Modal handles secrets in deployment)
load_dotenv()
# These vars will be pulled from Modal Secret or local .env
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL") # This is generally ignored by Modal web deployment, but kept for clarity

# Set up basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- 2. Local Development Setup (for testing outside Modal) ---

# This section is kept for local development and testing
# The main application logic is now inside the Modal function

# Initialize the FastAPI app for local development
local_app = FastAPI()

@local_app.get("/")
async def root():
    """Simple health check endpoint for local development."""
    return {"status": "ok", "description": "FastAPI Telegram Webhook Listener is running (local dev mode)."}

@local_app.post("/")
async def process_telegram_update_local(request: Request):
    """
    Local development webhook endpoint.
    Note: This is a simplified version for local testing.
    The full implementation is in the Modal function.
    """
    return {"status": "local_dev", "message": "Use Modal deployment for full functionality"}


# --- 5. Modal Deployment Setup ---

# Define the Image (Container environment)
# We need fastapi, python-telegram-bot, httpx, and python-dotenv
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("fastapi", "python-telegram-bot[webhooks]", "uvicorn", "python-dotenv", "httpx")
)

app = modal.App("fastapi-lifespan-app")

@app.function(image=image,
              secrets=[modal.Secret.from_name("podcast-fetcher-secrets")],
              container_idle_timeout=300)
@modal.asgi_app()
def fastapi_app_with_lifespan():
    """Exposes the FastAPI application at the root of the Modal deployment URL."""
    from fastapi import FastAPI, Request, Response
    from http import HTTPStatus
    from typing import Dict, Any
    from telegram import Update, Bot
    from telegram.ext import Application, CommandHandler, ContextTypes
    import httpx
    import os
    import logging

    # Set up logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)

    # Get environment variables
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")

    # Telegram Bot Handlers
    async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handles the /start command and greets the user."""
        await update.effective_chat.send_message(
            "👋 Hello! I'm a FastAPI-powered webhook bot. Send /echo <text> to see me work."
        )

    async def echo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Echoes the text received after the /echo command."""
        if not context.args:
            await update.message.reply_text("Usage: /echo <your text>")
            return

        text_to_echo = " ".join(context.args)
        await update.message.reply_text(f"You said: {text_to_echo}")

    # Initialize python-telegram-bot Application (Webhooks mode)
    ptb_application = (
        Application.builder()
        .updater(None)
        .token(BOT_TOKEN)
        .read_timeout(7) 
        .build()
    )

    # Add handlers to the application
    ptb_application.add_handler(CommandHandler("start", start_command))
    ptb_application.add_handler(CommandHandler("echo", echo_command))

    def lifespan(wapp: FastAPI):
        """FastAPI lifespan context manager: used to start/stop the PTB application."""
        import asyncio
        
        async def _lifespan():
            logger.info("Starting PTB application...")
            async with ptb_application:
                await ptb_application.initialize()
                await ptb_application.start()
                yield
                await ptb_application.stop()
            logger.info("PTB application stopped.")
        
        return _lifespan()

    # Initialize the FastAPI app with the lifespan manager
    web_app = FastAPI(lifespan=lifespan)

    @web_app.get("/")
    async def root():
        """Simple health check endpoint."""
        return {"status": "ok", "description": "FastAPI Telegram Webhook Listener is running."}

    @web_app.post("/")
    async def process_telegram_update(request: Request):
        """
        Main webhook endpoint. Receives JSON updates from Telegram and passes them
        to the python-telegram-bot application for processing.
        """
        try:
            req_json: Dict[str, Any] = await request.json()
            
            # --- ROBUSTNESS FIX: Ensure PTB application is running (safeguard against ASGI lifespan race) ---
            if not ptb_application.running:
                # If for any reason the lifespan start() was skipped or hasn't finished, 
                # we force it to start now before processing the update.
                logger.info(f"PTB app initialized {ptb_application._initialized}")
                await ptb_application.initialize()
                await ptb_application.start()
                logger.warning("PTB application was not running; forced start() inside webhook endpoint.")
            # ---------------------------------------------------------------------------------------------
            
            
            # Convert the raw JSON into a telegram.Update object
            update = Update.de_json(req_json, ptb_application.bot)
            
            # Process the update using the PTB application's internal dispatcher
            await ptb_application.process_update(update)

        except Exception as e:
            logger.error(f"Error processing update: {e}", exc_info=True)
            # Return HTTP 200 OK to Telegram even on internal error 
            # to prevent continuous retries, unless the error is critical.
            return Response(status_code=HTTPStatus.OK)

        # Telegram expects a successful HTTP 200 OK response quickly.
        return Response(status_code=HTTPStatus.OK)

    

    return web_app

# --- 6. Additional Modal Functions ---

@app.function(image=image,
              secrets=[modal.Secret.from_name("podcast-fetcher-secrets")])
@modal.fastapi_endpoint(method="GET")
async def set_webhook(url: str = None):
    """
    Utility function called after deployment to set the Telegram webhook URL.
    Modal automatically passes its own public URL to this function if `url` is not provided.
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    
    if not bot_token:
        return {"error": "TELEGRAM_BOT_TOKEN not found. Ensure 'podcast-fetcher-secrets' is configured."}

    if not url:
        return {"error": "Webhook URL must be provided as a query parameter (e.g., /setwebhook?url=...)"}

    full_webhook_url = f"{url}/" if not url.endswith('/') else url 

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


if __name__ == "__main__":
    # If run directly, start Uvicorn (FastAPI server)
    logger.info("Starting FastAPI server...")
    uvicorn.run(local_app, host="0.0.0.0", port=8000)
