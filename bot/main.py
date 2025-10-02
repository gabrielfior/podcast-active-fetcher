#!/usr/bin/env python
# pylint: disable=unused-argument

"""
Podcast Bot - A Telegram bot for adding podcasts.

Usage:
Send /add_podcast to start adding a new podcast.
Press Ctrl-C on the command line or send a signal to the process to stop the bot.
"""

from loguru import logger
import os
from dotenv import load_dotenv
from datetime import datetime, timezone
from sqlmodel import Session, select

load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
from podcast_fetcher.database import init_database, set_user_update_frequency, get_user_update_frequency
from podcast_fetcher.models import Podcast




# Conversation states for add_podcast command
PODCAST_TITLE, PODCAST_RSS = range(2)


async def add_podcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the add_podcast conversation and ask for podcast title."""
    await update.message.reply_text(
        "Let's add a new podcast! Please send me the podcast title:"
    )
    return PODCAST_TITLE


async def received_podcast_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store podcast title and ask for RSS URL."""
    context.user_data["podcast_title"] = update.message.text
    await update.message.reply_text(
        "Great! Now please send me the RSS URL for this podcast:"
    )
    return PODCAST_RSS


async def received_podcast_rss(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store RSS URL and save podcast to database."""
    context.user_data["podcast_rss"] = update.message.text
    
    title = context.user_data["podcast_title"]
    rss = context.user_data["podcast_rss"]
    username = update.message.from_user.username
    
    
    try:
        # Initialize database
        engine = init_database()
        
        with Session(engine) as session:
            # Check if podcast with this RSS feed already exists for this user
            existing = session.exec(
                select(Podcast).where(Podcast.rss_feed == rss, Podcast.username == username)
            ).first()
            
            if existing:
                await update.message.reply_text(
                    f"❌ A podcast with RSS feed '{rss}' already exists: {existing.title}\n\n"
                    f"Please try with a different RSS feed."
                )
            else:
                # Create new podcast
                podcast = Podcast(
                    title=title,
                    rss_feed=rss,
                    username=username,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                
                session.add(podcast)
                session.commit()
                
                await update.message.reply_text(
                    f"✅ Perfect! I've added the podcast:\n\n"
                    f"📻 **Title:** {title}\n"
                    f"🔗 **RSS:** {rss}\n\n"
                    f"Podcast added successfully to your collection!"
                )
                
    except Exception as e:
        logger.error(f"Database error when adding podcast: {e}")
        await update.message.reply_text(
            f"❌ Sorry, there was an error saving the podcast. Please try again later."
        )
    
    # Clear the user data for this conversation
    context.user_data.pop("podcast_title", None)
    context.user_data.pop("podcast_rss", None)
    
    return ConversationHandler.END


async def set_update_frequency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display inline keyboard for setting update frequency."""
    keyboard = [
        [
            InlineKeyboardButton("Last 3 days", callback_data="freq_3"),
            InlineKeyboardButton("Last 7 days", callback_data="freq_7"),
        ],
        [
            InlineKeyboardButton("Last 15 days", callback_data="freq_15"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "📅 Choose your podcast update frequency:",
        reply_markup=reply_markup
    )


async def handle_frequency_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the callback from frequency selection."""
    query = update.callback_query
    await query.answer()
    
    frequency_map = {
        "freq_3": ("3 days", 3),
        "freq_7": ("7 days", 7), 
        "freq_15": ("15 days", 15)
    }
    
    selected_frequency_text, frequency_days = frequency_map.get(query.data, ("Unknown", 0))
    username = query.from_user.username
    
    try:
        # Initialize database
        engine = init_database()
        
        # Save frequency to database
        success = set_user_update_frequency(engine, username, frequency_days)
        
        if success:
            await query.edit_message_text(
                f"✅ Update frequency set to: **{selected_frequency_text}**\n\n"
                f"Your podcasts will be updated to fetch episodes from the last {selected_frequency_text}."
            )
        else:
            await query.edit_message_text(
                f"❌ Sorry, there was an error saving your frequency preference. Please try again later."
            )
            
    except Exception as e:
        logger.error(f"Database error when setting frequency: {e}")
        await query.edit_message_text(
            f"❌ Sorry, there was an error saving your frequency preference. Please try again later."
        )


async def check_update_frequency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check and display the user's current update frequency setting."""
    username = update.message.from_user.username
    
    try:
        # Initialize database
        engine = init_database()
        
        # Get user's frequency setting
        frequency_days = get_user_update_frequency(engine, username)
        
        if frequency_days is not None:
            await update.message.reply_text(
                f"📅 Your current update frequency is: **{frequency_days} days**\n\n"
                f"Your podcasts will fetch episodes from the last {frequency_days} days."
            )
        else:
            await update.message.reply_text(
                f"❓ You haven't set an update frequency yet.\n\n"
                f"Use /set_update_frequency to configure your preference."
            )
            
    except Exception as e:
        logger.error(f"Database error when checking frequency: {e}")
        await update.message.reply_text(
            f"❌ Sorry, there was an error retrieving your frequency setting. Please try again later."
        )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    user = update.message.from_user
    logger.info("User %s canceled the conversation.", user.first_name)
    await update.message.reply_text("Operation cancelled.")
    
    # Clear any stored data
    context.user_data.pop("podcast_title", None)
    context.user_data.pop("podcast_rss", None)
    
    return ConversationHandler.END


def main() -> None:
    """Run the bot."""
    # Create the Application and pass it your bot's token.
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment variables")
        return
        
    application = Application.builder().token(token).build()

    # Add conversation handler for add_podcast command
    add_podcast_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("add_podcast", add_podcast_start)],
        states={
            PODCAST_TITLE: [
                MessageHandler(
                    filters.TEXT & ~(filters.COMMAND), received_podcast_title
                )
            ],
            PODCAST_RSS: [
                MessageHandler(
                    filters.TEXT & ~(filters.COMMAND), received_podcast_rss
                )
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(add_podcast_conv_handler)
    
    # Add command handler for set_update_frequency
    application.add_handler(CommandHandler("set_update_frequency", set_update_frequency))
    
    # Add command handler for check_update_frequency
    application.add_handler(CommandHandler("check_update_frequency", check_update_frequency))
    
    # Add callback query handler for frequency selection
    application.add_handler(CallbackQueryHandler(handle_frequency_callback, pattern="^freq_"))

    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()