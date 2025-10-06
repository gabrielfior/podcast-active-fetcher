

from loguru import logger
import os
import re
from dotenv import load_dotenv
from datetime import datetime, timezone
from sqlmodel import Session, select

load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

# Import database functionality
from podcast_fetcher.database import (
    init_database,
    subscribe_user_to_podcast, get_user_subscriptions, unsubscribe_user_from_podcast,
    update_subscription_preferences
)
from podcast_fetcher.models import Podcast
from podcast_fetcher.taddy_search import create_taddy_searcher, TaddySearchError
from podcast_fetcher.config import TADDY_API_KEY, TADDY_USER_ID




# Conversation states for subscribe command
PODCAST_TITLE, PODCAST_SELECTION, NOTIFICATION_PREFERENCES = range(3)


async def subscribe_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the subscribe conversation and ask for podcast title."""
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
        logger.error(f"Taddy search error: {e}")
        await update.message.reply_text(
            f"❌ Sorry, there was an error searching for podcasts: {e}\n\n"
            f"Please try again or use /cancel to stop."
        )
        return PODCAST_TITLE
        
    except Exception as e:
        logger.error(f"Unexpected error during podcast search: {e}")
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
        logger.error(f"Database error when adding podcast: {e}")
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
        logger.error(f"Database error when subscribing: {e}")
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
        logger.error(f"Database error when getting subscriptions: {e}")
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
        logger.error(f"Database error when getting subscriptions for unsubscribe: {e}")
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
        logger.error(f"Database error when unsubscribing: {e}")
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
            logger.error(f"Database error when getting subscriptions: {e}")
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
            logger.error(f"Database error when getting subscriptions: {e}")
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
        logger.error(f"Error getting podcast info: {e}")
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
        logger.error(f"Error updating notification preference: {e}")
        await query.edit_message_text(
            "❌ Sorry, there was an error updating your preference. Please try again later."
        )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    user = update.message.from_user
    logger.info("User %s canceled the conversation.", user.first_name)
    await update.message.reply_text(
        "Operation cancelled.",
        reply_markup=ReplyKeyboardRemove()
    )
    
    # Clear any stored data
    context.user_data.pop("search_term", None)
    context.user_data.pop("search_results", None)
    
    return ConversationHandler.END


def main() -> None:
    """Run the bot."""
    # Create the Application and pass it your bot's token.
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment variables")
        return
        
    application = Application.builder().token(token).build()

    # Add conversation handler for subscribe command (renamed from add_podcast)
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

    application.add_handler(subscribe_conv_handler)
    
    
    # Add new subscription management commands
    application.add_handler(CommandHandler("my_subscriptions", my_subscriptions))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe_start))
    application.add_handler(CommandHandler("subscription_settings", subscription_settings))
    
    # Add callback query handlers
    application.add_handler(CallbackQueryHandler(handle_unsubscribe_callback, pattern="^unsub_"))
    application.add_handler(CallbackQueryHandler(handle_settings_callback, pattern="^settings_"))
    application.add_handler(CallbackQueryHandler(handle_change_notification_callback, pattern="^change_notify_"))
    application.add_handler(CallbackQueryHandler(handle_set_notification_callback, pattern="^set_notify_"))

    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()