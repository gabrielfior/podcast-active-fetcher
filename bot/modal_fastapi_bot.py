from botocore.config import Config
import modal
import os
import re
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from aiogram import F, Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    Update,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.markdown import hbold
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from sqlmodel import Session, select
from podcast_fetcher.database import (
    get_user_subscriptions,
    init_database,
    subscribe_user_to_podcast,
    unsubscribe_user_from_podcast,
    update_subscription_preferences,
)
from podcast_fetcher.models import Podcast
from podcast_fetcher.taddy_search import TaddySearchError, create_taddy_searcher
from podcast_fetcher.keys import Config as KeysConfig

# Create Modal app
app = modal.App("aiogram-telegram-bot-fastapi")

# Global storage for search results (Modal web endpoint state persistence issue)
user_search_results = {}


# Conversation states for subscribe command
class SubscribeStates(StatesGroup):
    PODCAST_TITLE = State()
    PODCAST_SELECTION = State()
    NOTIFICATION_PREFERENCES = State()


# Define the image with all necessary dependencies
image = (
    modal.Image.debian_slim(python_version="3.11")
    .uv_pip_install(
        "aiogram>=3.22.0",
        "fastapi>=0.115.0",
        "uvicorn>=0.32.0",
        "python-dotenv>=1.1.1",
        "sqlmodel>=0.0.24",
        "loguru>=0.7.1",
        "psycopg2-binary>=2.9.10",
        "python-dateutil>=2.8.2",
        "boto3>=1.39.11",
        "llama-index>=0.13.2",
        "llama-index-llms-bedrock-converse>=0.8.2",
        "strands-agents>=1.12.0",
        "strands-agents-tools>=0.2.11",
        "feedparser",
        "beautifulsoup4",
        "lxml",
        "requests",
    )
    .add_local_python_source("podcast_fetcher")
)


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("podcast-fetcher-secrets")],
    scaledown_window=300,
)
@modal.asgi_app()
def fastapi_bot():
    """
    Deploy the aiogram Telegram bot using FastAPI with @modal.asgi_app decorator.
    """
    import logging
    import sys

    from podcast_fetcher.podcast_agent import get_agent_response
    from podcast_fetcher.keys import Config

    # Bot token from Modal secrets
    API_TOKEN = Config().TELEGRAM_BOT_TOKEN

    # The path Telegram will send updates to
    WEBHOOK_PATH = "/"

    # Set up logging
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    # All handlers should be attached to the Router
    router = Router()

    @router.message(Command("chat"))
    async def chat_handler(message: Message) -> None:
        """
        This handler receives messages with `/chat` command
        """
        print(f"entered chat handler: {message.from_user.id} {message.text}")
        try:
            response = get_agent_response(message.from_user.username, message.text)
            await message.answer(response)
        except Exception as e:
            print(f"Error in chat handler: {e}")
            import traceback

            traceback.print_exc()
            await message.answer(
                "Sorry, I encountered an error processing your request. Please try again."
            )

    # --- Subscription Management Handlers ---
    @router.message(Command("my_subscriptions"))
    async def my_subscriptions(message: Message) -> None:
        """Display user's current subscriptions."""
        username = message.from_user.username
        print(f"my_subscriptions called by user: {username}")

        try:
            # Initialize database
            engine = init_database()

            # Get user's subscriptions
            subscriptions = get_user_subscriptions(engine, username)
            print(f"Found {len(subscriptions)} subscriptions for user {username}")

            if not subscriptions:
                await message.answer(
                    "📭 You don't have any active subscriptions.\n\n"
                    "Use /subscribe to subscribe to podcasts!"
                )
                return

            # Format subscriptions message
            message_text = f"🎧 **Your Subscriptions** ({len(subscriptions)})\n\n"

            for i, (subscription, podcast) in enumerate(subscriptions, 1):
                message_text += f"{i}. **{podcast.title}**\n"
                message_text += f"   📅 Subscribed: {subscription.subscribed_at.strftime('%Y-%m-%d')}\n"
                message_text += (
                    f"   🔔 Notifications: {subscription.notification_preferences}\n"
                )
                message_text += f"   🔗 RSS: {podcast.rss_feed}\n\n"

            await message.answer(message_text, parse_mode="Markdown")

        except Exception as e:
            print(f"Database error when getting subscriptions: {e}")
            import traceback

            traceback.print_exc()
            await message.answer(
                "❌ Sorry, there was an error retrieving your subscriptions. Please try again later."
            )

    @router.message(Command("subscribe"))
    async def subscribe_start(message: Message, state: FSMContext) -> None:
        """Start the subscription process."""
        print(f"subscribe_start called by user: {message.from_user.username}")
        await state.set_state(SubscribeStates.PODCAST_TITLE)
        await message.answer(
            "Please enter the title of the podcast you want to subscribe to.",
            reply_markup=ReplyKeyboardRemove()
        )
        
    
    @router.message(Command("cancel"))
    @router.message(F.text.casefold() == "cancel")
    async def cancel_handler(message: Message, state: FSMContext) -> None:
        """
        Allow user to cancel any action
        """
        current_state = await state.get_state()
        if current_state is None:
            return

        logging.info("Cancelling state %r", current_state)
        await state.clear()
        await message.answer(
            "Cancelled.",
            reply_markup=ReplyKeyboardRemove(),
        )
        
    # handle podcast title
    @router.message(SubscribeStates.PODCAST_TITLE)
    async def handle_podcast_title(message: Message, state: FSMContext) -> None:
        """
        Handle the podcast title input from the user.
        Search for podcasts using Taddy API and display results with InlineKeyboardBuilder.
        """
        print(f"handle_podcast_title called by user: {message.from_user.username}")
        search_term = message.text
        await state.update_data(podcast_title=search_term)
        
        try:
            # Create Taddy searcher
            searcher = create_taddy_searcher(KeysConfig().TADDY_API_KEY, KeysConfig().TADDY_USER_ID)
            
            # Search for podcasts
            results = searcher.search_podcasts(search_term)
            
            if not results.podcasts:
                await message.answer(
                    f"🔍 No podcasts found for '{search_term}'.\n\n"
                    f"Please try a different search term or use /cancel to stop."
                )
                return
            
            # Store search results in state (convert to dict for serialization)
            search_results_dict = [
                {
                    'uuid': podcast.uuid,
                    'name': podcast.name,
                    'rss_url': podcast.rss_url,
                    'description': podcast.description
                }
                for podcast in results.podcasts
            ]
            await state.update_data(search_results=search_results_dict)
            
            # Also store in global storage for Modal web endpoint persistence
            user_search_results[message.from_user.username] = search_results_dict
            
            # Create message text with podcast details (enumerated list)
            message_text = f"🔍 Found {len(results.podcasts)} podcasts for '{search_term}':\n\n"
            for i, podcast in enumerate(results.podcasts[:10]):  # Show first 10 results
                message_text += f"{i+1}. **{podcast.name}**\n"
                if podcast.description:
                    # Clean HTML tags and truncate description
                    import re
                    clean_desc = re.sub(r'<[^>]+>', '', podcast.description)
                    message_text += f"   📝 {clean_desc[:150]}{'...' if len(clean_desc) > 150 else ''}\n"
                message_text += f"   🔗 RSS: {podcast.rss_url}\n\n"
            
            message_text += "Please type the **number** of the podcast you want to subscribe to (1-10), or type 'cancel' to stop:"
            
            await message.answer(
                message_text,
                parse_mode="Markdown"
            )
            
            await state.set_state(SubscribeStates.PODCAST_SELECTION)
            print(f"State set to PODCAST_SELECTION for user: {message.from_user.username}")
            
        except Exception as e:
            print(f"Error searching podcasts: {e}")
            import traceback
            traceback.print_exc()
            await message.answer(
                f"❌ Sorry, there was an error searching for podcasts: {str(e)}\n\n"
                f"Please try again or use /cancel to stop."
            )
    
    # Handle podcast selection by number
    @router.message(SubscribeStates.PODCAST_SELECTION)
    async def handle_podcast_selection(message: Message, state: FSMContext) -> None:
        """Handle podcast selection by number input."""
        print(f"handle_podcast_selection called by user: {message.from_user.username}")
        print(f"User input: {message.text}")
        print(f"Current state: {await state.get_state()}")
        
        try:
            # Check if user wants to cancel
            if message.text.lower() in ['cancel', 'c', 'stop']:
                await state.clear()
                await message.answer("❌ Selection cancelled.")
                return
            
            # Try to parse the number
            try:
                selection_number = int(message.text.strip())
            except ValueError:
                await message.answer(
                    "❌ Please enter a valid number (1-10) or type 'cancel' to stop."
                )
                return
            
            # Get search results from state
            data = await state.get_data()
            search_results = data.get("search_results", [])
            
            if not search_results:
                await message.answer("❌ No search results found. Please start over with /subscribe.")
                await state.clear()
                return
            
            # Validate selection number
            if selection_number < 1 or selection_number > min(len(search_results), 10):
                await message.answer(
                    f"❌ Please enter a number between 1 and {min(len(search_results), 10)}, or type 'cancel' to stop."
                )
                return
            
            # Get selected podcast (convert from 1-based to 0-based index)
            selected_podcast = search_results[selection_number - 1]
            print(f"Selected podcast: {selected_podcast['name']}")
            
            # Store selected podcast in state
            await state.update_data(selected_podcast=selected_podcast)
            
            # Show confirmation
            await message.answer(
                f"✅ You selected: **{selected_podcast['name']}**\n\n"
                f"📝 Description: {selected_podcast['description'][:200]}{'...' if len(selected_podcast['description']) > 200 else ''}\n\n"
                f"🔗 RSS Feed: {selected_podcast['rss_url']}\n\n"
                f"Type 'yes' to subscribe or 'no' to cancel:",
                parse_mode="Markdown"
            )
            
            await state.set_state(SubscribeStates.NOTIFICATION_PREFERENCES)
            
        except Exception as e:
            print(f"Error handling podcast selection: {e}")
            import traceback
            traceback.print_exc()
            await message.answer(
                "❌ Error processing selection. Please try again or use /cancel to stop."
            )
    
    # Handle subscription confirmation
    @router.message(SubscribeStates.NOTIFICATION_PREFERENCES)
    async def handle_subscription_confirmation(message: Message, state: FSMContext) -> None:
        """Handle subscription confirmation."""
        print(f"handle_subscription_confirmation called by user: {message.from_user.username}")
        print(f"User input: {message.text}")
        
        try:
            # Check if user wants to cancel
            if message.text.lower() in ['no', 'cancel', 'c', 'stop']:
                await state.clear()
                await message.answer("❌ Subscription cancelled.")
                return
            
            # Check if user confirms
            if message.text.lower() not in ['yes', 'y', 'confirm']:
                await message.answer(
                    "❌ Please type 'yes' to subscribe or 'no' to cancel."
                )
                return
            
            # Get selected podcast from state
            data = await state.get_data()
            selected_podcast = data.get("selected_podcast")
            
            if not selected_podcast:
                await message.answer("❌ No podcast selected. Please start over with /subscribe.")
                await state.clear()
                return
            
            # Initialize database
            engine = init_database()
            username = message.from_user.username
            
            # Check if podcast already exists or create new one
            with Session(engine) as session:
                # Check if podcast with this RSS feed already exists
                existing_podcast = session.exec(
                    select(Podcast).where(Podcast.rss_feed == selected_podcast['rss_url'])
                ).first()
                
                if existing_podcast:
                    # Podcast exists, subscribe user to it
                    success, result_message = subscribe_user_to_podcast(
                        engine=engine,
                        username=username,
                        podcast_id=existing_podcast.id,
                        notification_preferences="immediate"
                    )
                    
                    if success:
                        await message.answer(
                            f"🎉 Successfully subscribed to **{selected_podcast['name']}**!\n\n"
                            f"You'll receive notifications about new episodes.",
                            parse_mode="Markdown"
                        )
                    else:
                        await message.answer(f"❌ {result_message}")
                else:
                    # Create new podcast first
                    podcast = Podcast(
                        title=selected_podcast['name'],
                        rss_feed=selected_podcast['rss_url'],
                        username=username,
                        created_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc)
                    )
                    
                    session.add(podcast)
                    session.commit()
                    
                    # Now subscribe the user to the new podcast
                    success, result_message = subscribe_user_to_podcast(
                        engine=engine,
                        username=username,
                        podcast_id=podcast.id,
                        notification_preferences="immediate"
                    )
                    
                    if success:
                        await message.answer(
                            f"🎉 Successfully subscribed to **{selected_podcast['name']}**!\n\n"
                            f"You'll receive notifications about new episodes.",
                            parse_mode="Markdown"
                        )
                    else:
                        await message.answer(f"❌ {result_message}")
            
            # Clear state
            await state.clear()
            
        except Exception as e:
            print(f"Error confirming subscription: {e}")
            import traceback
            traceback.print_exc()
            await message.answer(
                "❌ Error subscribing. Please try again or use /cancel to stop."
            )
    
    # Handle number input for podcast selection (fallback for state issues)
    @router.message(F.text.regexp(r'^\d+$'))
    async def handle_number_input(message: Message, state: FSMContext) -> None:
        """Handle number input that might be podcast selection."""
        print(f"handle_number_input called by user: {message.from_user.username}")
        print(f"User input: {message.text}")
        print(f"Current state: {await state.get_state()}")
        
        try:
            # Check if we have search results in state
            data = await state.get_data()
            search_results = data.get("search_results", [])
            
            # If no search results in state, try global storage (Modal web endpoint persistence issue)
            if not search_results:
                print("No search results in state, checking global storage")
                search_results = user_search_results.get(message.from_user.username, [])
                print(f"Search results count from global storage: {len(search_results)}")
            
            if not search_results:
                # No search results, let fallback handler deal with it
                print("No search results found anywhere, returning early")
                return
            
            # We have search results, treat this as podcast selection
            selection_number = int(message.text.strip())
            
            # Validate selection number
            if selection_number < 1 or selection_number > min(len(search_results), 10):
                await message.answer(
                    f"❌ Please enter a number between 1 and {min(len(search_results), 10)}, or type 'cancel' to stop."
                )
                return
            
            # Get selected podcast (convert from 1-based to 0-based index)
            selected_podcast = search_results[selection_number - 1]
            print(f"Selected podcast: {selected_podcast['name']}")
            
            # Store selected podcast in state
            await state.update_data(selected_podcast=selected_podcast)
            
            # Show confirmation
            await message.answer(
                f"✅ You selected: **{selected_podcast['name']}**\n\n"
                f"📝 Description: {selected_podcast['description'][:200]}{'...' if len(selected_podcast['description']) > 200 else ''}\n\n"
                f"🔗 RSS Feed: {selected_podcast['rss_url']}\n\n"
                f"Type 'yes' to subscribe or 'no' to cancel:",
                parse_mode="Markdown"
            )
            
            await state.set_state(SubscribeStates.NOTIFICATION_PREFERENCES)
            
        except Exception as e:
            print(f"Error handling number input: {e}")
            import traceback
            traceback.print_exc()
            await message.answer(
                "❌ Error processing selection. Please try again or use /cancel to stop."
            )
    
    ################

    # --- Fallback Handler (must be last) ---
    @router.message()
    async def fallback_handler(message: Message, state: FSMContext) -> None:
        """
        Fallback handler for any unhandled messages
        Only responds to text messages that are not commands
        """
        print(f"fallback handler called with message: {message.text}")
        print(f"Current state: {await state.get_state()}")
        
        # Check if this is a number input (potential podcast selection)
        if message.text and message.text.isdigit():
            await message.answer(
                "❌ It looks like you're trying to select a podcast, but I don't have any search results in memory.\n\n"
                "This can happen if the bot restarted. Please use /subscribe to search for podcasts again."
            )
            return
        
        if message.text and not message.text.startswith("/"):
            print(f"Responding to non-command text: {message.text}")
            await message.answer(
                "I didn't understand that. Use /subscribe to find podcasts, /my_subscriptions to view your subscriptions, or /help for more commands."
            )
        else:
            print(f"Ignoring command or non-text message: {message.text}")

    # Dispatcher is a root router with FSM storage
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    # ... and all other routers should be attached to Dispatcher
    dp.include_router(router)

    # Initialize Bot instance with default bot properties
    bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    # --- FastAPI Lifespan and App Setup ---

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        print("Bot started successfully on Modal")
        yield
        await bot.session.close()

    # Create the FastAPI app with the lifespan context
    fastapi_app = FastAPI(lifespan=lifespan)

    # --- Request Logging Middleware ---

    @fastapi_app.middleware("http")
    async def log_requests(request: Request, call_next):
        """Log all incoming requests"""
        print(f"========== INCOMING REQUEST ==========")
        print(f"Method: {request.method}")
        print(f"URL: {request.url}")
        print(f"Path: {request.url.path}")
        print(f"Headers: {dict(request.headers)}")

        response = await call_next(request)

        print(f"Response status: {response.status_code}")
        print(f"======================================")
        return response

    # --- Health Check Endpoint ---

    @fastapi_app.get("/")
    async def health_check():
        """Health check endpoint"""
        print("Health check endpoint called")
        return {"status": "ok", "bot": "running"}

    # --- Webhook Endpoint ---

    @fastapi_app.post(WEBHOOK_PATH)
    async def bot_webhook(update: dict):
        """
        This is the main endpoint that receives updates from Telegram.
        The update object is passed directly to the aiogram dispatcher.
        Webhook URL: POST /
        """
        print(f"========== WEBHOOK RECEIVED ==========")
        print(f"Raw update data: {update}")
        print(f"Update keys: {update.keys() if update else 'None'}")

        try:
            # The 'update' dictionary from Telegram is validated by aiogram's Update model
            telegram_update = Update.model_validate(update)
            print(f"Validated Telegram update ID: {telegram_update.update_id}")

            # Process the update with the dispatcher
            await dp.feed_update(bot, telegram_update)
            print(f"Successfully processed update {telegram_update.update_id}")

        except Exception as e:
            print(f"ERROR processing update: {e}")
            import traceback

            traceback.print_exc()
            raise

        print(f"=====================================")
        # Telegram expects a 200 OK response quickly
        return {"message": "ok"}

    print(f"Starting FastAPI bot, webhook path: {WEBHOOK_PATH}")
    print(f"Available routes: GET / (health), POST / (webhook)")

    return fastapi_app
