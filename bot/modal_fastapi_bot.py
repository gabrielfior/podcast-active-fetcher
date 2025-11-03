import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import modal
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from aiogram.utils.markdown import hbold
from botocore.config import Config
from fastapi import FastAPI, Request
from sqlmodel import Session, select

from podcast_fetcher.database import (
    get_user_subscriptions,
    init_database,
    subscribe_user_to_podcast,
    unsubscribe_user_from_podcast,
    update_subscription_preferences,
)
from podcast_fetcher.keys import Config as KeysConfig
from podcast_fetcher.models import Podcast
from podcast_fetcher.taddy_search import TaddySearchError, create_taddy_searcher

# Create Modal app
app = modal.App("aiogram-telegram-bot-fastapi")

# Global storage for search results (Modal web endpoint state persistence issue)
user_search_results = {}


def escape_markdown(text: str) -> str:
    """
    Escape Markdown special characters to prevent parsing errors.
    Escapes: *, _, [, ], `, \
    """
    if not text:
        return ""
    # Escape special Markdown characters
    escape_chars = ['*', '_', '[', ']', '`', '\\']
    for char in escape_chars:
        text = text.replace(char, f'\\{char}')
    return text


# Conversation states for subscribe command
class SubscribeStates(StatesGroup):
    PODCAST_TITLE = State()
    PODCAST_SELECTION = State()
    NOTIFICATION_PREFERENCES = State()


# Conversation states for unsubscribe command
class UnsubscribeStates(StatesGroup):
    PODCAST_SELECTION = State()


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

    from podcast_fetcher.keys import Config
    from podcast_fetcher.podcast_agent import get_agent_response

    # Bot token from Modal secrets
    API_TOKEN = Config().TELEGRAM_BOT_TOKEN

    # The path Telegram will send updates to
    WEBHOOK_PATH = "/"

    # Set up logging
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    # All handlers should be attached to the Router
    router = Router()

    @router.message(Command("help"))
    async def help_handler(message: Message) -> None:
        """
        Display all available commands with descriptions.
        """
        help_text = (
            "📚 <b>Available Commands:</b>\n\n"
            "/help - Show this help message\n"
            "/chat - Chat with the podcast agent\n"
            "/subscribe - Subscribe to a podcast\n"
            "/my_subscriptions - View your current subscriptions\n"
            "/unsubscribe - Unsubscribe from a podcast\n"
            "💡 <b>Tips:</b>\n"
            "• Use /subscribe to search and subscribe to podcasts\n"
            "• You can choose notification preferences (immediate, daily, or weekly)\n"
            "• Use 'cancel' at any time to stop the current operation"
        )
        await message.answer(help_text)

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
                escaped_title = escape_markdown(podcast.title)
                escaped_rss = escape_markdown(podcast.rss_feed)
                message_text += f"{i}. **{escaped_title}**\n"
                message_text += f"   📅 Subscribed: {subscription.subscribed_at.strftime('%Y-%m-%d')}\n"
                message_text += (
                    f"   🔔 Notifications: {subscription.notification_preferences}\n"
                )
                message_text += f"   🔗 RSS: {escaped_rss}\n\n"

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
            "Please enter the title of the podcast you want to subscribe to, or 'cancel' to stop.",
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
            escaped_search_term = escape_markdown(search_term)
            message_text = f"🔍 Found {len(results.podcasts)} podcasts for '{escaped_search_term}':\n\n"
            for i, podcast in enumerate(results.podcasts[:10]):  # Show first 10 results
                escaped_name = escape_markdown(podcast.name)
                message_text += f"{i+1}. **{escaped_name}**\n"
                if podcast.description:
                    # Clean HTML tags and truncate description
                    import re
                    clean_desc = re.sub(r'<[^>]+>', '', podcast.description)
                    escaped_desc = escape_markdown(clean_desc[:150])
                    message_text += f"   📝 {escaped_desc}{'...' if len(clean_desc) > 150 else ''}\n"
                escaped_rss = escape_markdown(podcast.rss_url)
                message_text += f"   🔗 RSS: {escaped_rss}\n\n"
            
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
            escaped_name = escape_markdown(selected_podcast['name'])
            description = selected_podcast.get('description') or ''
            escaped_desc = escape_markdown(description[:200]) if description else 'No description available'
            escaped_rss = escape_markdown(selected_podcast['rss_url'])
            desc_suffix = '...' if len(description) > 200 else ''
            await message.answer(
                f"✅ You selected: **{escaped_name}**\n\n"
                f"📝 Description: {escaped_desc}{desc_suffix}\n\n"
                f"🔗 RSS Feed: {escaped_rss}\n\n"
                f"🔔 **Choose your notification preference:**\n\n"
                f"1️⃣ **Immediate** - Get notified as soon as new episodes are published\n"
                f"2️⃣ **Daily** - Get a daily digest of new episodes\n"
                f"3️⃣ **Weekly** - Get a weekly digest of new episodes\n\n"
                f"Please type the **number** (1, 2, or 3) of your preferred notification setting, or type 'cancel' to stop:",
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
    
    # Handle notification preference selection
    @router.message(SubscribeStates.NOTIFICATION_PREFERENCES)
    async def handle_notification_preference(message: Message, state: FSMContext) -> None:
        """Handle notification preference selection."""
        print(f"handle_notification_preference called by user: {message.from_user.username}")
        print(f"User input: {message.text}")
        
        try:
            # Check if user wants to cancel
            if message.text.lower() in ['cancel', 'c', 'stop']:
                await state.clear()
                await message.answer("❌ Subscription cancelled.")
                return
            
            # Parse notification preference
            try:
                preference_number = int(message.text.strip())
            except ValueError:
                await message.answer(
                    "❌ Please enter a valid number (1, 2, or 3) or type 'cancel' to stop."
                )
                return
            
            # Map numbers to notification preferences
            preference_map = {
                1: "immediate",
                2: "daily", 
                3: "weekly"
            }
            
            if preference_number not in preference_map:
                await message.answer(
                    "❌ Please enter 1, 2, or 3 for your notification preference, or type 'cancel' to stop."
                )
                return
            
            notification_preference = preference_map[preference_number]
            print(f"Selected notification preference: {notification_preference}")
            
            # Store notification preference in state
            await state.update_data(notification_preference=notification_preference)
            
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
                        notification_preferences=notification_preference
                    )
                    
                    if success:
                        escaped_name = escape_markdown(selected_podcast['name'])
                        await message.answer(
                            f"🎉 Successfully subscribed to **{escaped_name}**!\n\n"
                            f"🔔 **Notification preference:** {notification_preference.title()}\n\n"
                            f"You'll receive notifications about new episodes based on your preference.",
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
                        notification_preferences=notification_preference
                    )
                    
                    if success:
                        escaped_name = escape_markdown(selected_podcast['name'])
                        await message.answer(
                            f"🎉 Successfully subscribed to **{escaped_name}**!\n\n"
                            f"🔔 **Notification preference:** {notification_preference.title()}\n\n"
                            f"You'll receive notifications about new episodes based on your preference.",
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
    
    # --- Unsubscribe Handler ---
    @router.message(Command("unsubscribe"))
    async def unsubscribe_start(message: Message, state: FSMContext) -> None:
        """Start the unsubscribe process by showing user's subscriptions."""
        username = message.from_user.username
        print(f"unsubscribe_start called by user: {username}")

        try:
            # Initialize database
            engine = init_database()

            # Get user's subscriptions
            subscriptions = get_user_subscriptions(engine, username)
            print(f"Found {len(subscriptions)} subscriptions for user {username}")

            if not subscriptions:
                await message.answer(
                    "📭 You don't have any active subscriptions to unsubscribe from.\n\n"
                    "Use /subscribe to subscribe to podcasts!"
                )
                return

            # Store subscriptions in state (convert to dict for serialization)
            subscriptions_dict = [
                {
                    'subscription_id': subscription.id,
                    'podcast_id': subscription.podcast_id,
                    'podcast_title': podcast.title
                }
                for subscription, podcast in subscriptions
            ]
            await state.update_data(subscriptions=subscriptions_dict)

            # Format subscriptions message with numbers
            message_text = f"🎧 **Select a podcast to unsubscribe from:**\n\n"
            for i, (subscription, podcast) in enumerate(subscriptions, 1):
                escaped_title = escape_markdown(podcast.title)
                message_text += f"{i}. **{escaped_title}**\n"
                message_text += f"   📅 Subscribed: {subscription.subscribed_at.strftime('%Y-%m-%d')}\n\n"

            message_text += "Please type the **number** of the podcast you want to unsubscribe from, or type 'cancel' to stop:"

            await message.answer(message_text, parse_mode="Markdown")
            await state.set_state(UnsubscribeStates.PODCAST_SELECTION)

        except Exception as e:
            print(f"Database error when getting subscriptions for unsubscribe: {e}")
            import traceback
            traceback.print_exc()
            await message.answer(
                "❌ Sorry, there was an error retrieving your subscriptions. Please try again later."
            )

    @router.message(UnsubscribeStates.PODCAST_SELECTION)
    async def handle_unsubscribe_selection(message: Message, state: FSMContext) -> None:
        """Handle podcast selection for unsubscribe by number input."""
        print(f"handle_unsubscribe_selection called by user: {message.from_user.username}")
        print(f"User input: {message.text}")

        try:
            # Check if user wants to cancel
            if message.text.lower() in ['cancel', 'c', 'stop']:
                await state.clear()
                await message.answer("❌ Unsubscribe cancelled.")
                return

            # Try to parse the number
            try:
                selection_number = int(message.text.strip())
            except ValueError:
                await message.answer(
                    "❌ Please enter a valid number or type 'cancel' to stop."
                )
                return

            # Get subscriptions from state
            data = await state.get_data()
            subscriptions = data.get("subscriptions", [])

            if not subscriptions:
                await message.answer("❌ No subscriptions found. Please start over with /unsubscribe.")
                await state.clear()
                return

            # Validate selection number
            if selection_number < 1 or selection_number > len(subscriptions):
                await message.answer(
                    f"❌ Please enter a number between 1 and {len(subscriptions)}, or type 'cancel' to stop."
                )
                return

            # Get selected subscription (convert from 1-based to 0-based index)
            selected_subscription = subscriptions[selection_number - 1]
            podcast_id = selected_subscription['podcast_id']
            podcast_title = selected_subscription['podcast_title']
            print(f"Unsubscribing from podcast: {podcast_title} (ID: {podcast_id})")

            # Initialize database
            engine = init_database()
            username = message.from_user.username

            # Unsubscribe user
            success, result_message = unsubscribe_user_from_podcast(
                engine=engine,
                username=username,
                podcast_id=podcast_id
            )

            if success:
                escaped_title = escape_markdown(podcast_title)
                await message.answer(
                    f"✅ Successfully unsubscribed from **{escaped_title}**!\n\n"
                    f"You'll no longer receive notifications about new episodes from this podcast.",
                    parse_mode="Markdown"
                )
            else:
                await message.answer(f"❌ {result_message}")

            # Clear state
            await state.clear()

        except Exception as e:
            print(f"Error processing unsubscribe selection: {e}")
            import traceback
            traceback.print_exc()
            await message.answer(
                "❌ Error unsubscribing. Please try again or use /cancel to stop."
            )
    
    # Handle number input for podcast selection (fallback for state issues)
    @router.message(F.text.regexp(r'^\d+$'))
    async def handle_number_input(message: Message, state: FSMContext) -> None:
        """Handle number input that might be podcast selection."""
        print(f"handle_number_input called by user: {message.from_user.username}")
        print(f"User input: {message.text}")
        current_state = await state.get_state()
        print(f"Current state: {current_state}")
        
        # If we're in unsubscribe state, let the unsubscribe handler process it
        if current_state == UnsubscribeStates.PODCAST_SELECTION:
            print("In unsubscribe state, skipping handle_number_input")
            return
        
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
            escaped_name = escape_markdown(selected_podcast['name'])
            description = selected_podcast.get('description') or ''
            escaped_desc = escape_markdown(description[:200]) if description else 'No description available'
            escaped_rss = escape_markdown(selected_podcast['rss_url'])
            desc_suffix = '...' if len(description) > 200 else ''
            await message.answer(
                f"✅ You selected: **{escaped_name}**\n\n"
                f"📝 Description: {escaped_desc}{desc_suffix}\n\n"
                f"🔗 RSS Feed: {escaped_rss}\n\n"
                f"🔔 **Choose your notification preference:**\n\n"
                f"1️⃣ **Immediate** - Get notified as soon as new episodes are published\n"
                f"2️⃣ **Daily** - Get a daily digest of new episodes\n"
                f"3️⃣ **Weekly** - Get a weekly digest of new episodes\n\n"
                f"Please type the **number** (1, 2, or 3) of your preferred notification setting, or type 'cancel' to stop:",
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
                "I didn't understand that. Use /subscribe to find podcasts, /my_subscriptions to view your subscriptions."
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
