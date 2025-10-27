from datetime import datetime, timezone
import logging
import uvicorn
import os
import re

from dotenv import load_dotenv
from fastapi import FastAPI, Request
import modal
from sqlmodel import Session, select
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
import nest_asyncio

from podcast_fetcher.talk_to_podcast_episodes import clean_response_for_telegram, get_agent_response
nest_asyncio.apply()

from podcast_fetcher.config import TADDY_API_KEY, TADDY_USER_ID
from podcast_fetcher.database import (
    get_user_subscriptions,
    init_database,
    subscribe_user_to_podcast,
    unsubscribe_user_from_podcast,
    update_subscription_preferences,
)
from podcast_fetcher.models import Podcast
from podcast_fetcher.taddy_search import TaddySearchError, create_taddy_searcher

# --- MODAL IMPORTS ---

# Conversation states for subscribe command
PODCAST_TITLE, PODCAST_SELECTION, NOTIFICATION_PREFERENCES = range(3)

# --- 1. Environment Setup & Logging ---
# Load environment variables for local testing (Modal handles secrets in deployment)
load_dotenv()
# These vars will be pulled from Modal Secret or local .env
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Set up basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- 2. Telegram Bot Handler Functions ---

async def chat_with_agent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Simple echo handler for testing."""
    logger.info("entered chat with agent")
    print("entered chat with agent")
    text = update.message.text
    await update.message.reply_text(f"{text}")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Simple echo handler for testing."""
    text = update.message.text
    await update.message.reply_text(f"You said: {text}")

async def subscribe_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the subscribe conversation and ask for podcast title."""
    logger.info(f"Subscribe command received from user: {update.message.from_user.username}")
    await update.message.reply_text(
        "🎧 Let's subscribe you to a new podcast! Please send me the podcast title:"
    )
    return PODCAST_TITLE


async def received_podcast_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Search for podcasts using Taddy API and display results."""
    search_term = update.message.text
    context.user_data["search_term"] = search_term
    
    try:
        # Create Taddy searcher
        searcher = create_taddy_searcher(TADDY_API_KEY, TADDY_USER_ID)
        
        # Search for podcasts
        results = searcher.search_podcasts(search_term)
        
        if not results.podcasts:
            await update.message.reply_text(
                f"🔍 No podcasts found for '{search_term}'.\n\n"
                f"Please try a different search term or use /cancel to stop."
            )
            return PODCAST_TITLE
        
        # Store search results in context
        context.user_data["search_results"] = results.podcasts
        
        # Create reply keyboard with podcast options (cleaner alternative)
        keyboard = []
        for i, podcast in enumerate(results.podcasts[:8]):  # Limit to 8 results for better display
            # Truncate long names for button text
            button_text = podcast.name[:25] + "..." if len(podcast.name) > 25 else podcast.name
            keyboard.append([KeyboardButton(button_text)])
        
        # Add cancel button
        keyboard.append([KeyboardButton("❌ Cancel")])
        
        reply_markup = ReplyKeyboardMarkup(
            keyboard, 
            resize_keyboard=True, 
            one_time_keyboard=True,
            input_field_placeholder="Select a podcast..."
        )
        
        # Create message text with podcast details
        message_text = f"🔍 Found {len(results.podcasts)} podcasts for '{search_term}':\n\n"
        for i, podcast in enumerate(results.podcasts[:10]):
            message_text += f"{i+1}. **{podcast.name}**\n"
            if podcast.description:
                # Clean HTML tags and truncate description
                clean_desc = re.sub(r'<[^>]+>', '', podcast.description)
                message_text += f"   {clean_desc[:100]}{'...' if len(clean_desc) > 100 else ''}\n"
            message_text += "\n"
        
        message_text += "Please select a podcast from the keyboard below:"
        
        await update.message.reply_text(
            message_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        return PODCAST_SELECTION
        
    except TaddySearchError as e:
        logging.error(f"Taddy search error: {e}")
        await update.message.reply_text(
            f"❌ Sorry, there was an error searching for podcasts: {e}\n\n"
            f"Please try again or use /cancel to stop."
        )
        return PODCAST_TITLE
        
    except Exception as e:
        logging.error(f"Unexpected error during podcast search: {e}")
        await update.message.reply_text(
            f"❌ Sorry, there was an unexpected error. Please try again or use /cancel to stop."
        )
        return PODCAST_TITLE


async def handle_podcast_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle podcast selection from reply keyboard."""
    selected_text = update.message.text
    username = update.message.from_user.username
    
    if selected_text == "❌ Cancel":
        # Remove the keyboard by sending a message with ReplyKeyboardRemove
        await update.message.reply_text(
            "❌ Podcast selection cancelled.",
            reply_markup=ReplyKeyboardRemove()
        )
        # Clear the user data for this conversation
        context.user_data.pop("search_term", None)
        context.user_data.pop("search_results", None)
        return ConversationHandler.END
    
    try:
        search_results = context.user_data.get("search_results", [])
        
        # Find the selected podcast by matching the button text
        selected_podcast = None
        for i, podcast in enumerate(search_results[:8]):
            button_text = podcast.name[:25] + "..." if len(podcast.name) > 25 else podcast.name
            if selected_text == button_text:
                selected_podcast = podcast
                break
        
        if not selected_podcast:
            await update.message.reply_text(
                "❌ Invalid selection. Please try again.",
                reply_markup=ReplyKeyboardRemove()
            )
            return PODCAST_SELECTION
        
        # Store selected podcast in context for notification preference step
        context.user_data["selected_podcast"] = selected_podcast
        
        # Ask for notification preferences
        keyboard = [
            [
                InlineKeyboardButton("⚡ Immediate", callback_data="notify_immediate"),
                InlineKeyboardButton("📰 Daily Digest", callback_data="notify_daily"),
            ],
            [
                InlineKeyboardButton("📅 Weekly Digest", callback_data="notify_weekly"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"🔔 **Choose your notification preference for:**\n\n"
            f"📻 **{selected_podcast.name}**\n\n"
            f"**⚡ Immediate:** Get individual episode summaries as soon as they're available\n"
            f"**📰 Daily Digest:** Receive a daily summary of all new episodes\n"
            f"**📅 Weekly Digest:** Get a weekly roundup of new episodes",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        return NOTIFICATION_PREFERENCES
                
    except Exception as e:
        logging.error(f"Database error when adding podcast: {e}")
        await update.message.reply_text(
            f"❌ Sorry, there was an error saving the podcast. Please try again later.",
            reply_markup=ReplyKeyboardRemove()
        )
    
    # Clear the user data for this conversation
    context.user_data.pop("search_term", None)
    context.user_data.pop("search_results", None)
    
    return ConversationHandler.END


async def handle_notification_preference(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle notification preference selection."""
    query = update.callback_query
    await query.answer()
    
    if not query.data.startswith("notify_"):
        return ConversationHandler.END
    
    username = query.from_user.username
    selected_podcast = context.user_data.get("selected_podcast")
    
    if not selected_podcast:
        await query.edit_message_text("❌ Error: Podcast selection lost. Please try again.")
        return ConversationHandler.END
    
    # Map callback data to notification preferences
    preference_map = {
        "notify_immediate": "immediate",
        "notify_daily": "daily", 
        "notify_weekly": "weekly"
    }
    
    notification_preference = preference_map.get(query.data, "immediate")
    
    try:
        # Initialize database
        engine = init_database()
        
        with Session(engine) as session:
            # Check if podcast already exists in the database
            existing_podcast = session.exec(
                select(Podcast).where(Podcast.rss_feed == selected_podcast.rss_url)
            ).first()
            
            if existing_podcast:
                # Podcast exists, subscribe with notification preference
                success, message = subscribe_user_to_podcast(
                    engine, username, existing_podcast.id, notification_preference
                )
                if success:
                    await query.edit_message_text(
                        f"✅ {message}\n\n"
                        f"📻 **Podcast:** {selected_podcast.name}\n"
                        f"🔔 **Notifications:** {notification_preference}\n"
                        f"🔗 **RSS:** {selected_podcast.rss_url}\n\n"
                        f"You'll receive summaries based on your {notification_preference} preference!"
                    )
                else:
                    await query.edit_message_text(f"❌ {message}")
            else:
                # Create new podcast first
                podcast = Podcast(
                    title=selected_podcast.name,
                    rss_feed=selected_podcast.rss_url,
                    username=username,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                
                session.add(podcast)
                session.commit()
                
                # Now subscribe the user to the new podcast with notification preference
                success, message = subscribe_user_to_podcast(
                    engine, username, podcast.id, notification_preference
                )
                
                if success:
                    await query.edit_message_text(
                        f"✅ {message}\n\n"
                        f"📻 **Podcast:** {selected_podcast.name}\n"
                        f"🔔 **Notifications:** {notification_preference}\n"
                        f"🔗 **RSS:** {selected_podcast.rss_url}\n\n"
                        f"You'll receive summaries based on your {notification_preference} preference!"
                    )
                else:
                    await query.edit_message_text(f"❌ {message}")
                
    except Exception as e:
        logging.error(f"Database error when subscribing: {e}")
        await query.edit_message_text(
            "❌ Sorry, there was an error subscribing to the podcast. Please try again later."
        )
    
    # Clear the user data for this conversation
    context.user_data.pop("search_term", None)
    context.user_data.pop("search_results", None)
    context.user_data.pop("selected_podcast", None)
    
    return ConversationHandler.END




async def my_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display user's current subscriptions."""
    username = update.message.from_user.username
    
    try:
        # Initialize database
        engine = init_database()
        
        # Get user's subscriptions
        subscriptions = get_user_subscriptions(engine, username)
        
        if not subscriptions:
            await update.message.reply_text(
                "📭 You don't have any active subscriptions.\n\n"
                "Use /subscribe to subscribe to podcasts!"
            )
            return
        
        # Format subscriptions message
        message = f"🎧 **Your Subscriptions** ({len(subscriptions)})\n\n"
        
        for i, (subscription, podcast) in enumerate(subscriptions, 1):
            message += f"{i}. **{podcast.title}**\n"
            message += f"   📅 Subscribed: {subscription.subscribed_at.strftime('%Y-%m-%d')}\n"
            message += f"   🔔 Notifications: {subscription.notification_preferences}\n"
            message += f"   🔗 RSS: {podcast.rss_feed}\n\n"
        
        await update.message.reply_text(message, parse_mode='Markdown')
        
    except Exception as e:
        logging.error(f"Database error when getting subscriptions: {e}")
        await update.message.reply_text(
            "❌ Sorry, there was an error retrieving your subscriptions. Please try again later."
        )


async def unsubscribe_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start the unsubscribe process by showing user's subscriptions."""
    username = update.message.from_user.username
    
    try:
        # Initialize database
        engine = init_database()
        
        # Get user's subscriptions
        subscriptions = get_user_subscriptions(engine, username)
        
        if not subscriptions:
            await update.message.reply_text(
                "📭 You don't have any active subscriptions to unsubscribe from."
            )
            return
        
        # Create inline keyboard with subscription options
        keyboard = []
        for subscription, podcast in subscriptions:
            button_text = f"📻 {podcast.title[:30]}{'...' if len(podcast.title) > 30 else ''}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"unsub_{subscription.podcast_id}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = f"🎧 **Select a podcast to unsubscribe from:**\n\n"
        for i, (subscription, podcast) in enumerate(subscriptions, 1):
            message += f"{i}. **{podcast.title}**\n"
        
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
        
    except Exception as e:
        logging.error(f"Database error when getting subscriptions for unsubscribe: {e}")
        await update.message.reply_text(
            "❌ Sorry, there was an error retrieving your subscriptions. Please try again later."
        )


async def handle_unsubscribe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle unsubscribe button clicks."""
    query = update.callback_query
    await query.answer()
    
    if not query.data.startswith("unsub_"):
        return
    
    podcast_id = int(query.data.split("_")[1])
    username = query.from_user.username
    
    try:
        # Initialize database
        engine = init_database()
        
        # Unsubscribe user
        success, message = unsubscribe_user_from_podcast(engine, username, podcast_id)
        
        if success:
            await query.edit_message_text(
                f"✅ {message}\n\n"
                f"You've been unsubscribed from this podcast."
            )
        else:
            await query.edit_message_text(
                f"❌ {message}"
            )
            
    except Exception as e:
        logging.error(f"Database error when unsubscribing: {e}")
        await query.edit_message_text(
            "❌ Sorry, there was an error unsubscribing. Please try again later."
        )


async def subscription_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display subscription settings options."""
    keyboard = [
        [
            InlineKeyboardButton("🔔 Notification Preferences", callback_data="settings_notifications"),
            InlineKeyboardButton("📅 Episode Lookback", callback_data="settings_lookback"),
        ],
        [
            InlineKeyboardButton("📊 View All Subscriptions", callback_data="settings_view_all"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "⚙️ **Subscription Settings**\n\n"
        "Choose what you'd like to configure:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def handle_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle settings button clicks."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "settings_notifications":
        # Show user's current subscriptions with notification preference options
        username = query.from_user.username
        try:
            engine = init_database()
            subscriptions = get_user_subscriptions(engine, username)
            
            if not subscriptions:
                await query.edit_message_text(
                    "📭 You don't have any active subscriptions.\n\n"
                    "Use /subscribe to subscribe to podcasts!"
                )
                return
            
            # Create keyboard with subscription notification options
            keyboard = []
            for subscription, podcast in subscriptions:
                button_text = f"📻 {podcast.title[:25]}{'...' if len(podcast.title) > 25 else ''}"
                keyboard.append([InlineKeyboardButton(
                    button_text, 
                    callback_data=f"change_notify_{subscription.podcast_id}"
                )])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = f"🔔 **Change Notification Preferences**\n\n"
            message += f"Select a podcast to change its notification preference:\n\n"
            for i, (subscription, podcast) in enumerate(subscriptions, 1):
                message += f"{i}. **{podcast.title}**\n"
                message += f"   🔔 Current: {subscription.notification_preferences}\n\n"
            
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logging.error(f"Database error when getting subscriptions: {e}")
            await query.edit_message_text(
                "❌ Sorry, there was an error retrieving your subscriptions."
            )
    elif query.data == "settings_view_all":
        # Redirect to my_subscriptions
        username = query.from_user.username
        try:
            engine = init_database()
            subscriptions = get_user_subscriptions(engine, username)
            
            if not subscriptions:
                await query.edit_message_text(
                    "📭 You don't have any active subscriptions.\n\n"
                    "Use /subscribe to subscribe to podcasts!"
                )
                return
            
            message = f"🎧 **Your Subscriptions** ({len(subscriptions)})\n\n"
            for i, (subscription, podcast) in enumerate(subscriptions, 1):
                message += f"{i}. **{podcast.title}**\n"
                message += f"   📅 Subscribed: {subscription.subscribed_at.strftime('%Y-%m-%d')}\n"
                message += f"   🔔 Notifications: {subscription.notification_preferences}\n\n"
            
            await query.edit_message_text(message, parse_mode='Markdown')
            
        except Exception as e:
            logging.error(f"Database error when getting subscriptions: {e}")
            await query.edit_message_text(
                "❌ Sorry, there was an error retrieving your subscriptions."
            )


async def handle_change_notification_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle changing notification preferences for a subscription."""
    query = update.callback_query
    await query.answer()
    
    if not query.data.startswith("change_notify_"):
        return
    
    podcast_id = int(query.data.split("_")[2])
    username = query.from_user.username
    
    try:
        # Get podcast info
        engine = init_database()
        with Session(engine) as session:
            podcast = session.get(Podcast, podcast_id)
            if not podcast:
                await query.edit_message_text("❌ Podcast not found.")
                return
            
            # Show notification preference options
            keyboard = [
                [
                    InlineKeyboardButton("⚡ Immediate", callback_data=f"set_notify_immediate_{podcast_id}"),
                    InlineKeyboardButton("📰 Daily", callback_data=f"set_notify_daily_{podcast_id}"),
                ],
                [
                    InlineKeyboardButton("📅 Weekly", callback_data=f"set_notify_weekly_{podcast_id}"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"🔔 **Change notification preference for:**\n\n"
                f"📻 **{podcast.title}**\n\n"
                f"Choose your new notification preference:",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
    except Exception as e:
        logging.error(f"Error getting podcast info: {e}")
        await query.edit_message_text("❌ Sorry, there was an error. Please try again later.")


async def handle_set_notification_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle setting notification preferences."""
    query = update.callback_query
    await query.answer()
    
    if not query.data.startswith("set_notify_"):
        return
    
    # Parse the callback data: set_notify_{preference}_{podcast_id}
    parts = query.data.split("_")
    preference = parts[2]  # immediate, daily, or weekly
    podcast_id = int(parts[3])
    username = query.from_user.username
    
    try:
        engine = init_database()
        
        # Update subscription preferences
        success, message = update_subscription_preferences(engine, username, podcast_id, preference)
        
        if success:
            await query.edit_message_text(
                f"✅ {message}\n\n"
                f"Your notification preference has been updated to: **{preference}**"
            )
        else:
            await query.edit_message_text(f"❌ {message}")
            
    except Exception as e:
        logging.error(f"Error updating notification preference: {e}")
        await query.edit_message_text(
            "❌ Sorry, there was an error updating your preference. Please try again later."
        )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    user = update.message.from_user
    logging.info("User %s canceled the conversation.", user.first_name)
    await update.message.reply_text(
        "Operation cancelled.",
        reply_markup=ReplyKeyboardRemove()
    )
    
    # Clear any stored data
    context.user_data.pop("search_term", None)
    context.user_data.pop("search_results", None)
    
    return ConversationHandler.END


# --- 3. Local Development Setup (for testing outside Modal) ---

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
    print("entered process_telegram_update_local")
    return {"status": "local_dev", "message": "Use Modal deployment for full functionality"}


# --- 5. Modal Deployment Setup ---

# Define the Image (Container environment)
# We need fastapi, python-telegram-bot, httpx, python-dotenv, and all podcast_fetcher dependencies
image = (
    modal.Image.debian_slim(python_version="3.11")
    .uv_pip_install(
        "fastapi", 
        "python-telegram-bot[webhooks]", 
        "uvicorn", 
        "python-dotenv", 
        "httpx",
        "sqlmodel",
        "loguru",
        "requests",
        "feedparser",
        "beautifulsoup4",
        "lxml",
        "python-dateutil>=2.8.2",
        "psycopg2-binary>=2.9.10",
        "strands-agents>=1.12.0",
        "nest-asyncio>=1.6.0",
    )
    #.uv_pip_install("sqlmodel>=0.0.24", "beautifulsoup4>=4.13.4", "feedparser>=6.0.11", "python-dotenv>=1.1.1", "loguru>=0.7.1", "psycopg>=3.2.9", "requests>=2.31.0", "python-dateutil>=2.8.2", "psycopg2-binary>=2.9.10", "boto3>=1.34.0", "telethon>=1.35.0", "llama-index>=0.13.2", "llama-index-llms-bedrock-converse>=0.8.2")
    .add_local_python_source("podcast_fetcher")
)

app = modal.App("fastapi-bot-webhook")

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
    import os
    import logging

    # Set up logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)

    # Get environment variables
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")

    # Initialize python-telegram-bot Application (Webhooks mode)
    ptb_application = (
        Application.builder()
        .updater(None)
        .token(BOT_TOKEN)
        .read_timeout(7) 
        .build()
    )

    # Add conversation handler for subscribe command
    subscribe_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("subscribe", subscribe_start)],
        states={
            PODCAST_TITLE: [
                MessageHandler(
                    filters.TEXT & ~(filters.COMMAND), received_podcast_title
                )
            ],
            PODCAST_SELECTION: [
                MessageHandler(filters.TEXT & ~(filters.COMMAND), handle_podcast_selection)
            ],
            NOTIFICATION_PREFERENCES: [
                CallbackQueryHandler(handle_notification_preference, pattern="^notify_")
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Add all handlers to the application
    ptb_application.add_handler(subscribe_conv_handler)
    
    # chat with agent
    ptb_application.add_handler(CommandHandler("chat", chat_with_agent))
    
    # Add echo handler for testing
    ptb_application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    
    
    # Add new subscription management commands
    ptb_application.add_handler(CommandHandler("my_subscriptions", my_subscriptions))
    ptb_application.add_handler(CommandHandler("unsubscribe", unsubscribe_start))
    ptb_application.add_handler(CommandHandler("subscription_settings", subscription_settings))
    
    # Add callback query handlers
    ptb_application.add_handler(CallbackQueryHandler(handle_unsubscribe_callback, pattern="^unsub_"))
    ptb_application.add_handler(CallbackQueryHandler(handle_settings_callback, pattern="^settings_"))
    ptb_application.add_handler(CallbackQueryHandler(handle_change_notification_callback, pattern="^change_notify_"))
    ptb_application.add_handler(CallbackQueryHandler(handle_set_notification_callback, pattern="^set_notify_"))

    def lifespan(wapp: FastAPI):
        """FastAPI lifespan context manager: used to start/stop the PTB application."""
        import asyncio
        
        async def _lifespan():
            logger.info("Starting PTB application...")
            async with ptb_application:
                await ptb_application.initialize()
                await ptb_application.start()
                ptb_application.run_webhook()
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
            logger.info(f"Received update: {req_json}")
            
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
            logger.info(f"Processed update: {update}")
            
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



if __name__ == "__main__":
    # If run directly, start Uvicorn (FastAPI server)
    logger.info("Starting FastAPI server...")
    uvicorn.run(local_app, host="0.0.0.0", port=8000)
